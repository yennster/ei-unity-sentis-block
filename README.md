# Edge Impulse VR Explorer — Custom Deployment Block

A [custom deployment block](https://docs.edgeimpulse.com/studio/organizations/custom-blocks/custom-deployment-blocks)
for Edge Impulse Enterprise organizations that builds a Unity Sentis-ready
**`deploy.zip`** for the [Quest VR Explorer app](https://github.com/yennster/ei-vr-explorer-unity).

## What it does

When triggered from any project in your organization:

1. Reads the project's trained TFLite model + impulse metadata.
2. Converts TFLite → ONNX with `tflite2onnx` (no TensorFlow dep).
3. Bundles a `metadata.json` with class names, DSP block parameters,
   sensor type, and frequency — everything the Quest app needs to apply
   matching client-side DSP (Spectral Analysis / MFE / MFCC) before
   inference.
4. Writes the result as `deploy.zip` for download.

```
deploy.zip
├── model.onnx        ← Sentis loads this directly
├── metadata.json     ← classes, DSP config, sensor info
├── README.md
└── (optional) eon/   ← EON-compiled .h/.cpp if the build option is on
```

## Why this exists

Without this block, the Quest VR Explorer app does a multi-hop dance: download
the `arduino`/`android-cpp` deploy zip → extract the embedded TFLite from a C
byte-array → call a Vercel Python function to run `tflite2onnx` → stream the
ONNX bytes to the headset. With this block enabled on the org, the EI Studio
runs the exact same conversion in its own infrastructure, and the companion
just downloads the prebuilt `deploy.zip` — no extraction, no proxy.

For non-Enterprise users the companion's fallback path still works.

## Install (Enterprise)

In the Edge Impulse organization that owns your project:

1. **Organizations → Custom blocks → Add → Deployment block**.
2. Either point it at this GitHub repo (Studio clones + builds the
   `Dockerfile`) or push a prebuilt image to a registry and reference that.
3. Tick the projects (or the whole org) that should see it as a
   deployment option.

Once enabled, every project's **Deployment** page lists
**"Quest VR Explorer (Sentis ONNX bundle)"**.

## Local testing

You can exercise the same Docker contract locally with a downloaded
`deployment-metadata.json` from any project:

```bash
docker build -t ei-vr-explorer-block .

# Replace these with paths from your local checkout
docker run --rm \
  -v "$PWD/test-input:/data/input:ro" \
  -v "$PWD/test-output:/data/output:rw" \
  ei-vr-explorer-block \
  --metadata /data/input/deployment-metadata.json \
  --quantization float32 \
  --include-eon no

ls test-output/   # → deploy.zip
unzip -l test-output/deploy.zip
```

The `deployment-metadata.json` should have `folders.input` pointing at
`/data/input` and `folders.output` at `/data/output`.

## Block parameters (parameters.json)

| Parameter | Default | Meaning |
|---|---|---|
| `quantization` | `float32` | Which TFLite variant to convert. `int8` works if the project has int8 quant available; Sentis loads both. |
| `include-eon` | `no` | Bundle the EON-compiled `.h/.cpp` headers alongside the ONNX. Optional — useful if you also build a native plugin path. |

## Companion app & headset app

- Web companion: <https://github.com/yennster/ei-vr-explorer-web>
- Unity app: <https://github.com/yennster/ei-vr-explorer-unity>

## License

MIT.
