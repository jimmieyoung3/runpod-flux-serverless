#!/usr/bin/env bash
# Build the full 36 GB image from inside a RunPod CPU pod and push it, using the
# pod's datacenter uplink instead of a home connection.
#
# Why not `docker build`? RunPod pods cannot run a Docker daemon - Docker-in-Docker
# was removed with the Kata-based pods. RunPod's own tutorial builds images in a
# pod with a daemonless builder; this uses Buildah, which does the same job for a
# plain Dockerfile. `--isolation chroot` avoids the user-namespace and mount
# syscalls an unprivileged container cannot make; `--storage-driver vfs` avoids
# overlayfs-on-overlayfs.
#
# Pod requirements:
#   - CPU pod, Ubuntu-based image with a shell (e.g. runpod/base:*-cpu)
#   - >= 150 GB container disk or network volume mounted at /workspace
#     (vfs storage keeps a full copy per layer, so it needs headroom)
#
# Usage, from inside the pod:
#   export HF_TOKEN=hf_...
#   export IMAGE=docker.io/<user>/flux-runpod
#   export DOCKERHUB_USER=<user> DOCKERHUB_TOKEN=<access-token>
#   git clone <this repo> && cd flux-serverless
#   ./scripts/build_on_pod.sh v1
set -euo pipefail

TAG="${1:-v1}"
IMAGE="${IMAGE:?set IMAGE, e.g. docker.io/yourname/flux-runpod}"
MODEL_ID="${MODEL_ID:-black-forest-labs/FLUX.1-dev}"
: "${HF_TOKEN:?set HF_TOKEN - FLUX.1 is a gated repository}"
: "${DOCKERHUB_USER:?set DOCKERHUB_USER}"
: "${DOCKERHUB_TOKEN:?set DOCKERHUB_TOKEN (a Docker Hub access token, not your password)}"

ROOT="${BUILDAH_ROOT:-/workspace/containers}"

echo "==> checking disk headroom at $(dirname "$ROOT")"
avail_gb=$(df -BG --output=avail "$(dirname "$ROOT")" | tail -1 | tr -dc '0-9')
if (( avail_gb < 120 )); then
  echo "error: only ${avail_gb} GB free at $(dirname "$ROOT"); vfs storage needs ~120 GB." >&2
  echo "       Resize the pod's container disk or attach a network volume." >&2
  exit 1
fi

if ! command -v buildah >/dev/null; then
  echo "==> installing buildah"
  apt-get update -qq
  apt-get install -y -qq buildah ca-certificates
fi

mkdir -p "$ROOT"
export BUILDAH_ISOLATION=chroot
BUILDAH=(buildah --root "$ROOT" --storage-driver vfs)

echo "==> logging in to Docker Hub"
printf '%s' "$DOCKERHUB_TOKEN" | "${BUILDAH[@]}" login --username "$DOCKERHUB_USER" --password-stdin docker.io

cd "$(dirname "$0")/.."

# Buildah's --secret reads from a file, so stage the token in one that is
# owner-only and removed on any exit path.
SECRET_FILE="$(mktemp)"
chmod 600 "$SECRET_FILE"
trap 'rm -f "$SECRET_FILE"' EXIT INT TERM
printf '%s' "$HF_TOKEN" > "$SECRET_FILE"

echo "==> building ${IMAGE}:${TAG} (expect ~20-40 min: 34 GB of weights)"
"${BUILDAH[@]}" bud \
  --isolation chroot \
  --secret "id=hf_token,src=${SECRET_FILE}" \
  --build-arg "MODEL_ID=${MODEL_ID}" \
  -t "${IMAGE}:${TAG}" \
  -f Dockerfile \
  .

echo "==> pushing"
"${BUILDAH[@]}" push "${IMAGE}:${TAG}"

echo "==> done: ${IMAGE}:${TAG}"
echo "    Remember to stop/terminate the pod so it stops billing."
