# syntax=docker/dockerfile:1.6
FROM python:3.11-slim

# tflite2onnx parses the TFLite flatbuffer directly and doesn't pull in
# TensorFlow, so the image stays small (~150 MB).
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY build.py .

ENTRYPOINT ["python", "/app/build.py"]
