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

```bash
export HF_TOKEN=hf_xxx
export IMAGE=docker.io/<dockerhub-user>/flux-runpod
docker login
./scripts/build_and_push.sh v1
```

Expect ~34 GB of weights on top of a ~7 GB CUDA/PyTorch base. The download is
bandwidth-bound; the push is bound by your uplink and is the slowest step.

Keep the repository **private**. FLUX.1-dev's licence is non-commercial and does
not permit redistributing the weights, which is what a public image would do.

## 2. Create the endpoint

RunPod console → **Serverless** → **New Endpoint** → **Import from Docker Registry**.

| Setting | Value | Why |
| --- | --- | --- |
| Container image | `docker.io/<user>/flux-runpod:v1` | Tag explicitly; `latest` makes rollbacks ambiguous. |
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
