#!/usr/bin/env python3
"""
Edge Impulse Custom Deployment Block — Unity Sentis Bundle.

Reads the project's TFLite + impulse metadata, converts the model to ONNX
via tflite2onnx, and writes deploy.zip with everything a Unity Sentis
project needs to run the model on a Quest 2 / Quest 3 / any Unity target:

    deploy.zip/
    ├── model.onnx              <-- main inference model
    ├── metadata.json           <-- classes, DSP block params, sensor info
    ├── README.md               <-- short usage instructions
    └── unity/Scripts/          <-- C# DSP extractors matching the impulse
        ├── Fft.cs                  (always; shared FFT utility)
        ├── SpectralAnalysisExtractor.cs   (impulses with Spectral Analysis)
        ├── MFEExtractor.cs                (impulses with Audio MFE)
        └── MFCCExtractor.cs               (impulses with Audio MFCC)

The extractors are general implementations of EI's DSP blocks — they handle
any impulse using the block, with parameters read at runtime from
metadata.json. The bundling step just trims the zip to the .cs files this
impulse actually needs.

Block contract (per https://docs.edgeimpulse.com/studio/organizations/custom-blocks/custom-deployment-blocks):

    python build.py --metadata <deployment-metadata.json> [--quantization float32|int8]

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

        # Pick which Unity DSP scripts to include based on detected DSP blocks.
        unity_scripts = pick_unity_scripts(metadata)
        log(f"Bundling Unity DSP scripts: {sorted(unity_scripts) or '(none)'}")

        # Zip it.
        out_zip = output_dir / "deploy.zip"
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(onnx_path, arcname="model.onnx")
            zf.write(meta_path, arcname="metadata.json")
            zf.write(readme_path, arcname="README.md")
            for script in sorted(unity_scripts):
                src = UNITY_DSP_DIR / script
                if src.exists():
                    zf.write(src, arcname=str(Path("unity/Scripts") / script))
                else:
                    log(f"warning: expected Unity script {src} not found in image")
        log(f"Wrote {out_zip} ({out_zip.stat().st_size} bytes)")

    return 0


# ---------- constants -------------------------------------------------------

# Directory where the Dockerfile drops the Unity DSP .cs files at image
# build time. Override with EI_UNITY_DSP_DIR for local testing.
UNITY_DSP_DIR = Path(os.environ.get("EI_UNITY_DSP_DIR", "/app/unity-dsp"))

# Maps EI dsp block `type` (lowercased) to the Unity Scripts/*.cs file that
# implements it client-side. Anything not in this map is skipped — image
# DSP is built into Sentis via the ONNX itself, raw/flatten don't need
# preprocessing, etc.
DSP_TYPE_TO_SCRIPT: dict[str, str] = {
    "spectral-analysis": "SpectralAnalysisExtractor.cs",
    "spectral_analysis": "SpectralAnalysisExtractor.cs",
    "audio-mfe": "MFEExtractor.cs",
    "audio_mfe": "MFEExtractor.cs",
    "mfe": "MFEExtractor.cs",
    "audio-mfcc": "MFCCExtractor.cs",
    "audio_mfcc": "MFCCExtractor.cs",
    "mfcc": "MFCCExtractor.cs",
}


# ---------- helpers ---------------------------------------------------------


def pick_unity_scripts(metadata: dict) -> set[str]:
    """Return the set of .cs filenames to bundle, keyed off the impulse's
    DSP block types. Always include Fft.cs since Spectral / MFE / MFCC all
    depend on it; if no DSP scripts are needed (image projects, raw input)
    we drop Fft.cs too so the bundle stays minimal."""
    impulse = metadata.get("impulse") or {}
    blocks = impulse.get("dspBlocks") or []
    scripts: set[str] = set()
    for b in blocks:
        bt = (b.get("type") or "").lower()
        script = DSP_TYPE_TO_SCRIPT.get(bt)
        if script:
            scripts.add(script)
    if scripts:
        scripts.add("Fft.cs")
    return scripts


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


def log(msg: str) -> None:
    print(f"[deploy-block] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[deploy-block] error: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


README_TEMPLATE = """# Edge Impulse → Unity Sentis bundle

Built for **{project_name}** (sensor: `{sensor}`).

## Drop-in usage in any Unity Sentis project

1. Add `com.unity.sentis` to `Packages/manifest.json` (Unity 6 LTS or later).
2. Copy `unity/Scripts/*.cs` into your project's `Assets/Scripts/`.
3. Copy `model.onnx` into `Assets/Resources/Models/` (or anywhere; load via
   `ModelLoader.Load(stream)`).
4. Read `metadata.json` at runtime to configure the DSP extractor's
   parameters (frame size, FFT length, num filters, etc.) so the
   client-side preprocessing matches what the model was trained on.

## Contents

- `model.onnx` — converted ONNX model (Unity Sentis-loadable).
- `metadata.json` — classes, sensor type, sample rate, and the impulse's
  DSP block parameters.
- `unity/Scripts/` — general C# implementations of the EI DSP blocks this
  impulse uses (parameters read from `metadata.json` at runtime). Only the
  extractors needed for this impulse's blocks are included.

Classes (in model output order): {classes}
"""


if __name__ == "__main__":
    sys.exit(main())
