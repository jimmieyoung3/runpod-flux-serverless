# Deploying the endpoint on RunPod

Everything here is done once. Steps 1–3 can run in parallel with the image build.

## 0. Prerequisites

| Item | Where |
| --- | --- |
| RunPod account + credits | runpod.io → Billing → **Credit coupons** to redeem the code |
| FLUX.1-dev licence accepted | huggingface.co/black-forest-labs/FLUX.1-dev → Agree |
| HF read token | huggingface.co/settings/tokens |
| Container registry | Docker Hub account (free private repo is enough) |
| RunPod API key | RunPod console → Settings → API Keys → **Read/Write** |

## 1. Build and push the image

**Create the Docker Hub repository first, and make it private.** A push to a
repository that does not exist creates it as *public*, which for FLUX.1-dev
would redistribute non-commercially-licensed weights.

### The path used here: build inside a RunPod CPU pod

A home uplink makes the ~30 GB push take hours, so the build runs on a pod
instead. See the constraints documented in `scripts/build_on_pod.sh` — Buildah
cannot run in a RunPod pod, and Kaniko destroys the pod it builds in.

```bash
# on a CPU pod with >= 120 GB free disk (>= 16 vCPU; vcpuCount must be a power of 2)
export HF_TOKEN=hf_...  IMAGE=docker.io/<user>/flux-runpod  TAG=v1
export DOCKERHUB_USER=<user>  DOCKERHUB_TOKEN=<access-token>
git clone <this repo> && cd runpod-flux-serverless
./scripts/build_on_pod.sh
```

SSH will drop roughly 60-90 seconds in; that is expected. Watch from your own
machine instead — the tag appearing in the registry is the completion signal.
Measured: ~3 min to fetch weights, ~26 min to build and push. Then **terminate
the pod**, which is unusable afterwards.

### Alternative: build locally

Requires ~120 GB free disk and BuildKit, and the push is bound by your uplink.
This path is provided for completeness and was not the one used here.

```bash
export HF_TOKEN=hf_xxx
export IMAGE=docker.io/<dockerhub-user>/flux-runpod
docker login
./scripts/build_and_push.sh v1
```

Keep the repository **private**. FLUX.1-dev's licence is non-commercial and does
not permit redistributing the weights, which is what a public image would do.

## 2. Create the endpoint

RunPod console → **Serverless** → **New Endpoint** → **Import from Docker Registry**.

| Setting | Value | Why |
| --- | --- | --- |
| Container image | `docker.io/<user>/flux-runpod:v1` | Tag explicitly; `latest` makes rollbacks ambiguous. |
| GPU tiers | select **several**, not one | A single-tier endpoint can sit unschedulable. 11 tiers were selected here; workers landed on A40 and A100. |
| Registry credentials | your Docker Hub user + access token | Required for a private repo. |
| GPU | 48 GB (L40S / A6000) or 80 GB (A100 / H100) | bf16 transformer + T5 needs > 40 GB to stay resident. 24 GB works but triggers CPU offload. |
| Active workers | `0` | Pay only on request. Set `1` only to eliminate cold start. |
| Max workers | `1` while testing, `3`+ for load | Each extra worker is another cold start on first use. |
| Idle timeout | `60 s` while testing | Keeps the worker warm between test calls. Drop to `5 s` for production. |
| Execution timeout | `600 s` | A cold 1024px request must fit inside it. |
| FlashBoot | enabled | RunPod's snapshot restore; materially cuts repeat cold starts. |
| Container disk | `25 GB` | Writable layer + `/tmp` scratch for image encoding. |
| Container start command | leave empty | The Dockerfile `CMD` already starts the handler. |

No environment variables are required. Optional: `WARMUP=0` to skip the warmup
pass, `LOG_LEVEL=DEBUG` for verbose logs.

Copy the **Endpoint ID** from the endpoint page — that is `RUNPOD_ENDPOINT_ID`.

## 3. First request

The very first call also pulls the image onto a fresh host, so give it room:

```bash
export RUNPOD_API_KEY=...
export RUNPOD_ENDPOINT_ID=...

python client/call_endpoint.py --health --async          # cheapest possible cold start
python client/call_endpoint.py "a red fox in a snowy forest at dawn" --seed 7
```

Use `--async` for anything that might be cold: `/runsync` holds an HTTP connection
open and can time out at the proxy before a cold worker finishes, whereas `/run`
returns a job ID immediately and `client/call_endpoint.py` polls `/status` with
backoff.

## 4. Measure

```bash
python client/benchmark.py --runs 5 --gpu-rate <$/second for your GPU tier>
```

For a true cold-start number: set **Idle timeout** low, wait for the worker count
to fall to zero on the endpoint's Workers tab, then run the benchmark. The
`delayTime` field on the first job is the cold-start tax; `executionTime` is what
RunPod bills.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Worker exits immediately, logs show `403` / `gated repo` | Build ran without an accepted licence | Accept the licence, rebuild with a valid `HF_TOKEN`. |
| `CUDA out of memory` | GPU tier too small and offload did not engage | Pick a 48 GB+ GPU, or confirm `--health` reports `cpu_offload: true`. |
| First request times out, later ones work | Image pull + model load exceeded the client timeout | Use `--async`; raise Execution timeout. |
| `No CUDA device visible` | Endpoint scheduled on a CPU worker | Re-check the GPU selection on the endpoint. |
| Response truncated / 502 on large batches | Base64 payload past RunPod's ~20 MB limit | Use `JPEG`, fewer images, or configure `BUCKET_ENDPOINT_URL`. |
| Push fails partway | Uplink dropped | `docker push` again; completed layers are skipped. |

## Expect a throttle on the first request

A ~30 GB image means a worker host must cache it before starting, which is a
smaller pool than "any host with a free GPU". The first request here sat in
`throttled` for about 10 minutes; widening from 7 to 11 GPU tiers did not help.
It cleared on its own. Workers at zero are not billed while this happens.
