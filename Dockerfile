# syntax=docker/dockerfile:1.6
FROM python:3.11-slim

# tflite2onnx parses the TFLite flatbuffer directly and doesn't pull in
# TensorFlow, so the image stays small (~150 MB).

# Bake in the C# DSP scripts from the unity-app repo at image build time.
# We use a fixed branch (main) so build artefacts are reproducible per image
# tag. To pin to a specific commit, override UNITY_REF when building:
#   docker build --build-arg UNITY_REF=<sha> ...
ARG UNITY_REPO=yennster/ei-vr-explorer-unity
ARG UNITY_REF=main
ARG UNITY_RAW=https://raw.githubusercontent.com

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pull the four C# DSP scripts the bundle ships to consumers.
RUN mkdir -p /app/unity-dsp \
 && for f in Fft.cs SpectralAnalysisExtractor.cs MFEExtractor.cs MFCCExtractor.cs; do \
      curl -fsSL "${UNITY_RAW}/${UNITY_REPO}/${UNITY_REF}/Assets/Scripts/${f}" -o "/app/unity-dsp/${f}"; \
    done

COPY build.py .

ENTRYPOINT ["python", "/app/build.py"]
