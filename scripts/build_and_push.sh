#!/usr/bin/env bash
# Build the worker image with the weights baked in, then push it.
#
#   export HF_TOKEN=hf_...            # needs FLUX.1-dev licence accepted
#   export IMAGE=docker.io/<user>/flux-runpod
#   ./scripts/build_and_push.sh v1
#
# Override MODEL_ID to build the ungated 4-step variant instead:
#   MODEL_ID=black-forest-labs/FLUX.1-schnell ./scripts/build_and_push.sh schnell-v1
set -euo pipefail

TAG="${1:-v1}"
IMAGE="${IMAGE:?set IMAGE, e.g. docker.io/yourname/flux-runpod}"
MODEL_ID="${MODEL_ID:-black-forest-labs/FLUX.1-dev}"

if [[ "$MODEL_ID" == *dev* && -z "${HF_TOKEN:-}" ]]; then
  echo "error: FLUX.1-dev is gated - export HF_TOKEN (read scope) first" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

echo "==> building ${IMAGE}:${TAG} with ${MODEL_ID}"
# The token is passed as a BuildKit secret: mounted only for the RUN that needs
# it, and never written into a layer or into `docker history`.
DOCKER_BUILDKIT=1 docker build \
  --progress=plain \
  --secret id=hf_token,env=HF_TOKEN \
  --build-arg "MODEL_ID=${MODEL_ID}" \
  -t "${IMAGE}:${TAG}" \
  -t "${IMAGE}:latest" \
  .

echo "==> image size"
docker images "${IMAGE}" --format '{{.Repository}}:{{.Tag}}  {{.Size}}'

echo "==> pushing (this is the slow part: ~35 GB over your uplink)"
docker push "${IMAGE}:${TAG}"
docker push "${IMAGE}:latest"

echo "==> done: ${IMAGE}:${TAG}"
