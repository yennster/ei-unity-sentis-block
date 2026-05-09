#!/usr/bin/env python3
"""
Edge Impulse Custom Deployment Block — VR Explorer (Sentis ONNX bundle).

Reads the project's TFLite + impulse metadata, converts the model to ONNX
via tflite2onnx, and writes deploy.zip with the bundle Unity Sentis expects:

    deploy.zip/
    ├── model.onnx              <-- main inference model
    ├── metadata.json           <-- classes, DSP block config, sensor info
    └── README.md               <-- short instructions

The Quest VR Explorer app downloads this zip, extracts the ONNX, and
reads metadata.json to configure its client-side DSP and class names.

Block contract (per https://docs.edgeimpulse.com/studio/organizations/custom-blocks/custom-deployment-blocks):

    python build.py --metadata <deployment-metadata.json> [--include-eon yes|no] [--quantization float32|int8]

The metadata file tells us:
    folders.input  — where the TFLite + impulse files live
    folders.output — where to write deploy.zip
    tfliteModels[] — pre-built TFLite variants (float32, int8, EON)
    impulse.dspBlocks[] — DSP block configs (Spectral Analysis, MFCC, etc.)
    classes[]      — class names in model output order
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--include-eon", default="no", choices=["yes", "no"])
    parser.add_argument("--quantization", default="float32", choices=["float32", "int8"])
    args = parser.parse_args()

    metadata_path = Path(args.metadata)
    if not metadata_path.exists():
        die(f"--metadata file not found: {metadata_path}")

    metadata = json.loads(metadata_path.read_text())
    input_dir = Path(metadata["folders"]["input"])
    output_dir = Path(metadata["folders"]["output"])
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pick the right TFLite variant.
    tflite_path = pick_tflite(metadata, input_dir, args.quantization)
    if not tflite_path or not tflite_path.exists():
        die(f"No matching TFLite model found for quantization={args.quantization}")
    log(f"Using TFLite: {tflite_path}")

    # Convert TFLite → ONNX.
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        onnx_path = td / "model.onnx"
        try:
            import tflite2onnx
            tflite2onnx.convert(str(tflite_path), str(onnx_path))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            die(f"tflite2onnx conversion failed: {e}")
        log(f"Converted ONNX: {onnx_path} ({onnx_path.stat().st_size} bytes)")

        # Build the bundle's metadata.json.
        bundle_meta = build_bundle_metadata(metadata)
        meta_path = td / "metadata.json"
        meta_path.write_text(json.dumps(bundle_meta, indent=2, sort_keys=True))

        readme_path = td / "README.md"
        readme_path.write_text(README_TEMPLATE.format(
            project_name=metadata.get("project", {}).get("name", "Unknown project"),
            sensor=metadata.get("sensor", "?"),
            classes=", ".join(bundle_meta.get("classes", []) or []) or "(none)",
        ))

        # Optionally include EON-compiled headers.
        eon_dir = None
        if args.include_eon == "yes":
            eon_dir = td / "eon"
            eon_dir.mkdir()
            copied = copy_eon_artifacts(input_dir, eon_dir)
            log(f"Bundled {copied} EON artifact files")

        # Zip it.
        out_zip = output_dir / "deploy.zip"
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(onnx_path, arcname="model.onnx")
            zf.write(meta_path, arcname="metadata.json")
            zf.write(readme_path, arcname="README.md")
            if eon_dir and any(eon_dir.iterdir()):
                for p in eon_dir.rglob("*"):
                    if p.is_file():
                        zf.write(p, arcname=str(Path("eon") / p.relative_to(eon_dir)))
        log(f"Wrote {out_zip} ({out_zip.stat().st_size} bytes)")

    return 0


# ---------- helpers ---------------------------------------------------------


def pick_tflite(metadata: dict, input_dir: Path, quantization: str) -> Path | None:
    """Pick a TFLite variant from metadata.tfliteModels matching the requested
    quantization. Falls back to scanning the input dir for *.tflite if needed."""
    models = metadata.get("tfliteModels") or []
    wanted = quantization.lower()
    for m in models:
        details = m.get("details") or {}
        mtype = (details.get("modelType") or details.get("variant") or "").lower()
        if wanted in mtype or (wanted == "float32" and mtype in {"", "float", "fp32"}):
            mp = m.get("modelPath")
            if mp:
                p = (input_dir / mp).resolve() if not Path(mp).is_absolute() else Path(mp)
                if p.exists():
                    return p
    # Fallback: any .tflite file at the top level.
    for p in [input_dir / "trained.tflite", input_dir / "tflite-model" / "trained.tflite"]:
        if p.exists():
            return p
    for candidate in input_dir.rglob("*.tflite"):
        return candidate
    return None


def build_bundle_metadata(metadata: dict) -> dict[str, Any]:
    """Project the chunk of EI's deployment metadata that the headset needs."""
    project = metadata.get("project") or {}
    impulse = metadata.get("impulse") or {}
    return {
        "project": {
            "id": project.get("id"),
            "name": project.get("name"),
            "studioHost": project.get("studioHost"),
        },
        "deployCounter": metadata.get("deployCounter"),
        "frequency": metadata.get("frequency"),
        "samplesPerInference": metadata.get("samplesPerInference"),
        "axesCount": metadata.get("axesCount"),
        "sensor": metadata.get("sensor"),
        "classes": metadata.get("classes") or [],
        "inputBlocks": impulse.get("inputBlocks") or [],
        "dspBlocks": [_compact_dsp(b) for b in (impulse.get("dspBlocks") or [])],
        "learnBlocks": [_compact_learn(b) for b in (impulse.get("learnBlocks") or [])],
    }


def _compact_dsp(b: dict) -> dict:
    keep = ("id", "name", "type", "implementationVersion", "axes", "input", "title")
    out = {k: b.get(k) for k in keep if k in b}
    if "metadata" in b and isinstance(b["metadata"], dict):
        # `metadata.parameters` holds the user-facing DSP knobs (frame size,
        # filter count, FFT length, etc.) — exactly what the Unity inspector
        # configs need. Pass them through verbatim.
        out["parameters"] = b["metadata"].get("parameters") or {}
    return out


def _compact_learn(b: dict) -> dict:
    keep = ("id", "name", "type", "title")
    return {k: b.get(k) for k in keep if k in b}


def copy_eon_artifacts(input_dir: Path, dest: Path) -> int:
    count = 0
    for src in input_dir.rglob("*"):
        if src.is_file() and ("trained" in src.name.lower() and src.suffix in {".h", ".cpp", ".c"}):
            target = dest / src.name
            shutil.copy2(src, target)
            count += 1
    return count


def log(msg: str) -> None:
    print(f"[deploy-block] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[deploy-block] error: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


README_TEMPLATE = """# Quest VR Explorer deploy bundle

Built for **{project_name}** (sensor: `{sensor}`).

Contents:
- `model.onnx` — converted ONNX model (Unity Sentis-loadable).
- `metadata.json` — classes, DSP block config, sensor / sample-rate info
  the headset needs to apply matching client-side preprocessing.
- (optional) `eon/` — EON-compiled `.h/.cpp` artifacts for native-plugin paths.

Classes (in model output order): {classes}

Drop into the Edge Impulse VR Explorer Quest app — it auto-fetches this zip
on retrain.
"""


if __name__ == "__main__":
    sys.exit(main())
