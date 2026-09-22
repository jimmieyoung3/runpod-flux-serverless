#!/usr/bin/env bash
# Build the ~30 GB image from inside a RunPod CPU pod and push it, using the
# pod's datacenter uplink instead of a home connection.
#
# ---------------------------------------------------------------------------
# Two constraints drive every odd-looking choice below. Both were found the
# hard way; please read before "simplifying" this script.
#
# 1. Buildah and Podman cannot run here at all.
#    RunPod pods have no CAP_SYS_ADMIN, and the hosts set
#    apparmor_restrict_unprivileged_userns=1, so unshare(CLONE_NEWUSER) is
#    denied. Both tools re-exec into a user namespace at startup - before they
#    honour --isolation chroot - so even `buildah containers` fails. Kaniko
#    uses no namespaces, so it is the only workable builder.
#
# 2. Kaniko destroys the pod it runs in.
#    It extracts the base image over `/`, which deletes the Ubuntu userland
#    that sshd depends on. SSH dies mid-build and does NOT recover, even with
#    --ignore-path for /etc/ssh and /usr/sbin/sshd, because sshd's PAM and libc
#    dependencies go with it. Therefore:
#       - Kaniko must PUSH the image itself (--no-push + --tarPath would strand
#         the result on an unreachable pod),
#       - it must run detached via setsid so losing SSH cannot kill it,
#       - and progress must be tracked from OUTSIDE, against the registry.
#    Expect to lose SSH roughly 60-90 seconds in. That is normal.
#
# The Docker Hub repository MUST already exist and be PRIVATE. Kaniko creates
# a missing repo as PUBLIC, which for FLUX.1-dev would redistribute
# non-commercially-licensed weights.
# ---------------------------------------------------------------------------
#
# Usage, from inside the pod:
#   export HF_TOKEN=hf_...  IMAGE=docker.io/<user>/flux-runpod  TAG=v1
#   ./scripts/build_on_pod.sh
set -euo pipefail

TAG="${TAG:-${1:-v1}}"
IMAGE="${IMAGE:?set IMAGE, e.g. docker.io/yourname/flux-runpod}"
MODEL_ID="${MODEL_ID:-black-forest-labs/FLUX.1-dev}"
: "${HF_TOKEN:?set HF_TOKEN - FLUX.1 is a gated repository}"

CTX="$(cd "$(dirname "$0")/.." && pwd)"
KANIKO_VERSION="${KANIKO_VERSION:-v1.23.2}"
CRANE_VERSION="${CRANE_VERSION:-v0.20.2}"

echo "==> disk check"
avail_gb=$(df -BG --output=avail /root | tail -1 | tr -dc '0-9')
# Peak usage: weights in the context (34) + base rootfs (8) + weights copied
# into the image filesystem (34) + the snapshot layer (~34).
if (( avail_gb < 120 )); then
  echo "error: ${avail_gb} GB free; the build peaks near 120 GB." >&2
  echo "       RunPod caps CPU-pod disk at 15 GB/vCPU (cpu5) or 10 GB/vCPU (cpu3)," >&2
  echo "       and vcpuCount must be a power of 2, so size the pod accordingly." >&2
  exit 1
fi

echo "==> installing crane + kaniko (no daemon, no namespaces)"
if ! command -v crane >/dev/null; then
  curl -sL "https://github.com/google/go-containerregistry/releases/download/${CRANE_VERSION}/go-containerregistry_Linux_x86_64.tar.gz" \
    | tar -xz -C /usr/local/bin crane
  chmod +x /usr/local/bin/crane
fi
# Kaniko ships only as an image, and we cannot run images here - so unpack it.
if [[ ! -x /kaniko-src/kaniko/executor ]]; then
  mkdir -p /kaniko-src
  crane export "gcr.io/kaniko-project/executor:${KANIKO_VERSION}" - | tar -xC /kaniko-src
fi

echo "==> fetching weights into the build context"
# Deliberately OUTSIDE the image build: Kaniko cannot consume BuildKit secrets,
# and passing the token as a build arg would persist it in the image history.
if [[ ! -f "${CTX}/weights/model_index.json" ]]; then
  pip install -q --break-system-packages huggingface_hub==0.26.2 hf_transfer==0.1.8
  HF_HUB_ENABLE_HF_TRANSFER=1 MODEL_ID="${MODEL_ID}" \
    python3 "${CTX}/scripts/fetch_weights_local.py" "${CTX}/weights"
else
  echo "    (already present, skipping)"
fi

echo "==> writing registry auth"
: "${DOCKERHUB_USER:?set DOCKERHUB_USER}"
: "${DOCKERHUB_TOKEN:?set DOCKERHUB_TOKEN}"
umask 077
mkdir -p /root/.docker
printf '{"auths":{"https://index.docker.io/v1/":{"auth":"%s"}}}' \
  "$(printf '%s:%s' "$DOCKERHUB_USER" "$DOCKERHUB_TOKEN" | base64 -w0)" > /root/.docker/config.json

echo "==> launching kaniko (SSH will die shortly; that is expected)"
DOCKER_CONFIG=/root/.docker SSL_CERT_DIR=/kaniko-src/ssl/certs \
setsid nohup /kaniko-src/kaniko/executor \
  --force \
  --context "dir://${CTX}" \
  --dockerfile "${CTX}/Dockerfile.kaniko" \
  --destination "${IMAGE}:${TAG}" \
  --build-arg "MODEL_ID=${MODEL_ID}" \
  --single-snapshot \
  --compressed-caching=false \
  --ignore-path=/root \
  --ignore-path=/kaniko-src \
  --ignore-path=/usr/local/bin \
  --verbosity=info \
  > /root/kaniko.log 2>&1 < /dev/null &

echo "==> kaniko detached as pid $!"
echo "    Watch from your workstation, not from here:"
echo "      crane manifest ${IMAGE}:${TAG}    # succeeds once the push lands"
echo "    Then TERMINATE the pod - it is unusable after this point."
