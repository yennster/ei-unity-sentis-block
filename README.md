# Edge Impulse → Unity Sentis Custom Deployment Block

A [custom deployment block](https://docs.edgeimpulse.com/studio/organizations/custom-blocks/custom-deployment-blocks)
for Edge Impulse Enterprise organizations that builds a **Unity Sentis-ready
`deploy.zip`** for any Unity project — Quest 2 / Quest 3 / mobile XR / desktop.

## What it does

When triggered from any project in your organization:

1. Reads the project's trained TFLite model + impulse metadata.
2. Converts TFLite → ONNX with `tflite2onnx` (no TensorFlow dep).
3. Selects matching C# DSP extractors based on the impulse's DSP block types
   (Spectral Analysis for motion, MFE / MFCC for audio).
4. Bundles a `metadata.json` with class names, sensor type, sample rate, and
   the DSP block parameters — so the client-side preprocessing matches
   exactly what the model was trained on.

```
deploy.zip
├── model.onnx              ← Unity Sentis loads this directly
├── metadata.json           ← classes, DSP params, sensor info
├── README.md
├── unity/Scripts/          ← C# DSP scripts matching this impulse only
│   ├── Fft.cs
│   ├── SpectralAnalysisExtractor.cs   (motion impulses)
│   ├── MFEExtractor.cs                (audio MFE impulses)
│   └── MFCCExtractor.cs               (audio MFCC impulses)
└── (optional) eon/         ← EON-compiled .h/.cpp if --include-eon yes
```

The C# scripts are **selected per impulse** — an audio-only project doesn't
ship the motion DSP code and vice-versa.

## Why this exists

EI doesn't expose ONNX as a deploy block for most projects, and the TFLite
it does expose is just the neural net (DSP block runs separately in EI's
C++ code). Without this block, a Unity Sentis consumer has to:

1. Pick a TFLite-bearing deploy (`arduino` / `android-cpp` / `wasm`).
2. Extract the embedded TFLite from the C byte-array inside the zip.
3. Run `tflite2onnx` somewhere (server-side function or a one-off CLI).
4. Hand-write or copy in C# DSP code matching the impulse.

This block does steps 1–4 inside EI's infrastructure and hands you a
self-contained zip you drop into Unity.

## Drop-in usage in any Unity Sentis project

After downloading the `deploy.zip` produced by this block (paths below are
inside that zip — they don't exist in this repo):

1. Add `com.unity.sentis` to `Packages/manifest.json` (Unity 6 LTS or later).
2. Extract `unity/Scripts/*.cs` from the zip into your project's
   `Assets/Scripts/`.
3. Drop `model.onnx` into `Assets/Resources/Models/` (or load via stream
   from disk if it's user-supplied).
4. Read `metadata.json` at runtime to configure the DSP extractor's
   parameters (frame size, FFT length, num filters, etc.) so client-side
   preprocessing matches what the model was trained on.

> **Where the C# scripts come from:** they're checked in here under
> [`unity-dsp/`](unity-dsp/). Canonical source still lives in
> [`yennster/ei-vr-explorer-unity`](https://github.com/yennster/ei-vr-explorer-unity/tree/main/Assets/Scripts);
> when those upstream files change, run `./tools/sync-from-unity.sh` and
> commit the diff. The Dockerfile just `COPY`s the snapshot — deterministic
> builds, no network needed at image build time.

## Install (Enterprise)

In the Edge Impulse organization that owns your project:

1. **Organizations → Custom blocks → Add → Deployment block**.
2. Either point it at this GitHub repo (Studio clones + builds the
   `Dockerfile`) or push a prebuilt image to a registry and reference that.
3. Tick the projects (or the whole org) that should see it.

Once enabled, every project's **Deployment** page lists
**"Unity Sentis (ONNX + C# DSP bundle)"**.

## Local testing

```bash
docker build -t ei-unity-sentis-block .

# Replace these with paths from your local checkout
docker run --rm \
  -v "$PWD/test-input:/data/input:ro" \
  -v "$PWD/test-output:/data/output:rw" \
  ei-unity-sentis-block \
  --metadata /data/input/deployment-metadata.json \
  --quantization float32 \
  --include-eon no

ls test-output/         # → deploy.zip
unzip -l test-output/deploy.zip
```

## Block parameters (parameters.json)

| Parameter | Default | Meaning |
|---|---|---|
| `quantization` | `float32` | Which TFLite variant to convert. `int8` works if the project has int8 quant available; Sentis loads both. |
| `include-eon` | `no` | Bundle the EON-compiled `.h/.cpp` headers alongside the ONNX. Optional — useful for native plugin paths. |

## Updating the bundled C# scripts

The four `.cs` files in [`unity-dsp/`](unity-dsp/) are committed copies of
the canonical source in `yennster/ei-vr-explorer-unity`. Refresh them when
upstream changes:

```bash
./tools/sync-from-unity.sh             # default: main
./tools/sync-from-unity.sh <commit>    # or pin to a specific commit/tag
git diff unity-dsp/                    # review
git commit unity-dsp/ -m "Sync unity-dsp from ei-vr-explorer-unity@<ref>"
```

Each Docker build then ships exactly that snapshot — fully deterministic.

## Companion repos

- Unity reference app (Quest 2, includes scenes + collect/retrain UI):
  <https://github.com/yennster/ei-vr-explorer-unity>
- Web companion (pairing UI + fallback TFLite→ONNX path for non-Enterprise users):
  <https://github.com/yennster/ei-vr-explorer-web>

## License

MIT.
