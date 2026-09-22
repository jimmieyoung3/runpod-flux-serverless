#!/usr/bin/env bash
# Run the worker locally against test_input.json before spending a deploy cycle.
# Needs a GPU with enough VRAM (>=24 GB with offload, >=48 GB without) and the
# nvidia container toolkit. On a smaller card this is expected to OOM - that is
# what the RunPod endpoint is for.
set -euo pipefail
IMAGE="${IMAGE:?set IMAGE}"
TAG="${1:-v1}"

# The RunPod SDK detects test_input.json and runs the handler once, offline,
# printing the job output - no API key and no endpoint required.
docker run --rm --gpus all \
  -e WARMUP=0 \
  "${IMAGE}:${TAG}" \
  python -u /app/src/handler.py --test_input "$(cat test_input.json)"
