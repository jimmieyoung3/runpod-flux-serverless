# syntax=docker/dockerfile:1.7
#
# FLUX text-to-image worker for RunPod Serverless.
#
# Layers are ordered cheapest-to-invalidate last: deps, then the ~34 GB weight
# layer, then the source. Editing handler.py therefore rebuilds in seconds.
#
#   docker build --secret id=hf_token,env=HF_TOKEN -t <user>/flux-runpod:v1 .

FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# --- dependencies -----------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- model weights ----------------------------------------------------------
# MODEL_ID is a build arg so the same Dockerfile produces a FLUX.1-schnell image
# (no gating, 4-step inference) by overriding one value.
ARG MODEL_ID=black-forest-labs/FLUX.1-dev
ENV MODEL_ID=${MODEL_ID} \
    MODEL_DIR=/models/flux \
    HF_HUB_ENABLE_HF_TRANSFER=1

COPY builder/fetch_model.py /app/builder/fetch_model.py
RUN --mount=type=secret,id=hf_token \
    python /app/builder/fetch_model.py

# --- runtime ----------------------------------------------------------------
# Weights are local and complete; refuse any network call to the Hub at runtime
# so a Hub outage can never turn into a cold-start failure.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    WARMUP=1

COPY src/ /app/src/
COPY test_input.json /app/test_input.json

CMD ["python", "-u", "/app/src/handler.py"]
