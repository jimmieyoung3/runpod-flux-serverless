# FLUX.1 on RunPod Serverless

A text-to-image serverless endpoint: POST a prompt, get a PNG back. Built for the
RunPod Serverless Endpoint case study.

The worker runs [`black-forest-labs/FLUX.1-dev`](https://huggingface.co/black-forest-labs/FLUX.1-dev)
with the weights **baked into the Docker image**, so a cold worker starts from local
disk instead of pulling ~34 GB from the Hugging Face Hub on first request.

```
        POST /runsync                  ┌──────────────── RunPod Serverless ────────────────┐
client ──── {"input": {prompt}} ─────▶ │ queue ──▶ worker (GPU)                            │
       ◀─── {"output": {images[]}} ─── │           ├─ import: FluxPipeline.from_pretrained  │
                                       │           │          /models/flux   (baked in)     │
                                       │           └─ request: validate ▸ generate ▸ encode │
                                       └───────────────────────────────────────────────────┘
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/handler.py` | RunPod entrypoint: job in, JSON out. Owns error handling and delivery. |
| `src/predict.py` | Pipeline wrapper. Loads FLUX once per worker, generates images. |
| `src/schema.py` | Request validation. Dependency-free, so it unit-tests without a GPU. |
| `builder/fetch_model.py` | Downloads the weights during `docker build`, as its own cache layer. |
| `Dockerfile` | Reference image: deps ▸ weights ▸ source, HF token via BuildKit secret. |
| `Dockerfile.kaniko` | **The image that was actually built and deployed.** Weights pre-fetched, no secret. |
| `Dockerfile.volume` | Fallback image (~9 GB): weights fetched to a network volume on first boot. |
| `client/call_endpoint.py` | CLI to call the endpoint and save images (`/runsync` or `/run`+poll). |
| `client/benchmark.py` | Cold start, warm latency, concurrency and $/image measurements. |
| `tests/test_schema.py` | 25 unit tests for input handling. |
| `scripts/build_and_push.sh` | Local build + push. |
| `scripts/fetch_weights_local.py` | Downloads weights into the build context, keeping the token out of the image. |
| `scripts/build_on_pod.sh` | Daemonless build from inside a RunPod CPU pod (Kaniko). |
| `docs/DEPLOY.md` | Step-by-step RunPod console runbook. |
| `docs/kb/` | Knowledge base articles written from the failures hit while building this. |

## API

`POST https://api.runpod.ai/v2/<ENDPOINT_ID>/runsync`
with header `Authorization: Bearer <RUNPOD_API_KEY>`.

### Request

```json
{
  "input": {
    "prompt": "a cinematic photograph of a glass terrarium at golden hour, 85mm",
    "width": 1024,
    "height": 1024,
    "num_inference_steps": 28,
    "guidance_scale": 3.5,
    "seed": 42,
    "num_images": 1,
    "output_format": "PNG",
    "quality": 92
  }
}
```

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `prompt` | string | required | Required, ≤ 2000 chars. |
| `width`, `height` | int | 1024 | Snapped to a multiple of 16, clamped to 256-1536. |
| `num_inference_steps` | int | 28 (dev) / 4 (schnell) | 1-50. |
| `guidance_scale` | float | 3.5 (dev) / 0.0 (schnell) | 0-20. FLUX is guidance-distilled; 3.5 is the sweet spot. |
| `seed` | int | random | Omit for a random seed; the one used is always returned. |
| `num_images` | int | 1 | 1-4. |
| `output_format` | string | `PNG` | `PNG`, `JPEG`, `WEBP`. |
| `quality` | int | 92 | JPEG/WEBP only. |
| `action` | string | none | `"health"` returns model/GPU info without generating. |

There is deliberately **no `negative_prompt`**: FLUX.1 is distilled to run without
classifier-free guidance, so `FluxPipeline` has no negative conditioning to apply.
Silently accepting the field would be worse than rejecting it.

### Response

```json
{
  "images": ["<base64 PNG>"],
  "delivery": "base64",
  "mime_type": "image/png",
  "seed": 42,
  "parameters": { "width": 1024, "height": 1024, "num_inference_steps": 28, "...": "..." },
  "prompt": "...",
  "metrics": { "inference_seconds": 0.0, "seconds_per_image": 0.0, "total_seconds": 0.0, "cold_start": 0.0 }
}
```

Errors come back as `{"error": "...", "error_type": "validation_error" | "inference_error"}`
with HTTP 200. RunPod reserves non-2xx for platform failures, so application
errors are reported in the body.

## Quick start

```bash
# 1. Build (needs an accepted FLUX.1-dev licence + an HF read token)
export HF_TOKEN=hf_xxx
export IMAGE=docker.io/<dockerhub-user>/flux-runpod
./scripts/build_and_push.sh v1

# 2. Deploy: see docs/DEPLOY.md for the console walkthrough

# 3. Call it
export RUNPOD_API_KEY=... RUNPOD_ENDPOINT_ID=...
python client/call_endpoint.py "a red fox in a snowy forest at dawn" --seed 7
python client/call_endpoint.py --health          # model + GPU report, no generation
python client/benchmark.py --runs 5 --gpu-rate 0.000339   # A40 $/s; A100 is 0.000756
```

Or with plain curl:

```bash
curl -s -X POST "https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/runsync" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d @test_input.json | python -c "import json,sys,base64;\
d=json.load(sys.stdin)['output'];open('out.png','wb').write(base64.b64decode(d['images'][0]))"
```

Run the tests with no GPU and no network:

```bash
python -m venv .venv && .venv/bin/pip install pytest && .venv/bin/python -m pytest tests/ -q
```

## Two build paths

The weights are 33.7 GB, which makes *where you build* an engineering decision
rather than a detail.

| | `Dockerfile` (primary) | `Dockerfile.volume` (fallback) |
| --- | --- | --- |
| Image size | **29.87 GB** compressed (~45 GB on disk) | ~9 GB |
| Weights | baked into the image | downloaded once onto a RunPod network volume |
| Cold start, first ever worker | image pull | image pull + ~10 min download |
| Cold start, subsequent workers | image pull (host-cached) + model load | volume read + model load |
| Runtime Hub dependency | none (`HF_HUB_OFFLINE=1`) | first boot only |
| Needs `HF_TOKEN` on the endpoint | no | yes |

The primary image is what the brief asks for and what removes the Hub from the
critical path. The fallback exists because a 30 GB image is not always buildable
or pushable, and shipping a smaller image with a warm shared volume is a normal
production answer at this model size.

### Building the image without a fast uplink

A home connection makes the push, not the build, the bottleneck: ~30 GB at a
typical residential ~15 Mbit uplink is over 4 hours. `scripts/build_on_pod.sh`
builds from inside a RunPod CPU pod instead, on a datacenter link, where the
same work takes minutes.

Two platform constraints shape that script, both found by hitting them:

**Buildah and Podman cannot run in a RunPod pod.** Pods have no `CAP_SYS_ADMIN`,
and the hosts set `apparmor_restrict_unprivileged_userns=1`, so
`unshare(CLONE_NEWUSER)` is denied. Both tools re-exec into a user namespace at
startup, *before* they honour `--isolation chroot`, so even `buildah containers`
fails. [Kaniko](https://github.com/GoogleContainerTools/kaniko) uses no
namespaces and is the only workable builder. RunPod's own
[in-pod build tutorial](https://docs.runpod.io/tutorials/pods/build-docker-images)
reaches for Bazel + crane for the same underlying reason.

**Kaniko destroys the pod it runs in.** It extracts the base image over `/`,
deleting the Ubuntu userland `sshd` depends on. SSH drops ~60-90 s into the build
and never recovers - `--ignore-path` for `/etc/ssh` and `/usr/sbin/sshd` is not
enough, because sshd's PAM and libc dependencies go too. So Kaniko must **push
the image itself**: building to a local tarball strands the result on a pod you
can no longer reach. The build runs detached under `setsid`, and progress is
tracked from outside against the registry (`crane manifest`).

**The token never enters the image.** Kaniko does not implement
`RUN --mount=type=secret`, and demoting the HF token to a build arg would persist
it in the image history. Instead `scripts/fetch_weights_local.py` downloads the
weights into the build context beforehand and the Dockerfile just `COPY`s them,
so the token stays on the build host. The cost is peak disk: the weights exist
twice during the build, hence the ~120 GB requirement.

RunPod's [GitHub integration](https://docs.runpod.io/serverless/github-integration)
would otherwise be the obvious choice, and it is ruled out on two counts: it caps
`docker build` at 30 minutes, and it exposes no build-time secret, which a gated
repository like FLUX.1-dev requires.

## Design decisions

**Weights in the image, not downloaded at boot.** RunPod bills worker time, and a
cold worker that pulls 34 GB from the Hub pays for that download on every scale-up
and it inherits the Hub's availability. Baking them in moves the cost to build time
and makes cold start a function of image pull (cached on the host after the first
pull) plus `from_pretrained`. The trade is a 29.87 GB image and a slow first deploy.
`HF_HUB_OFFLINE=1` at runtime enforces that nothing reaches for the network.

**Load at import, not per request.** The pipeline is constructed at module import,
which RunPod attributes to worker start-up. Loading inside the handler would put a
~40 s model load inside billed execution time on every cold request.

**A one-step warmup pass.** The first real generation otherwise absorbs CUDA kernel
autotuning and lazy init. Warming with a throwaway 512px image moves that off the
first paying request. Set `WARMUP=0` to skip it.

**Layer ordering.** Dependencies, then weights, then source. Editing the handler
rebuilds only the last layer, so iteration costs seconds rather than a re-download.

**BuildKit secret for the HF token.** `--secret id=hf_token` mounts the token only
for the download step. An `ARG` or `ENV` would persist it in the image history for
anyone who pulls the image.

**Automatic CPU offload below 40 GB VRAM.** The bf16 transformer (~23.8 GB) plus
the T5-XXL text encoder (~9.5 GB) will not co-reside on a 24 GB card. The worker
detects this and calls `enable_model_cpu_offload()`: slower per image, but it runs
instead of OOMing, so the endpoint tolerates a cheaper GPU tier.

**One job per worker.** Generation saturates the GPU; batching two 1024px requests
onto one card is slower end-to-end than running them back to back. Concurrency
belongs at the worker-count level, which is what RunPod autoscaling does.

**Base64 by default, S3 optional.** Base64 keeps the endpoint dependency-free for
the reviewer. Setting `BUCKET_ENDPOINT_URL` (+ credentials) on the endpoint switches
to presigned URLs, which is the right choice past RunPod's ~20 MB response ceiling,
roughly four 1024px PNGs.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `MODEL_ID` | `black-forest-labs/FLUX.1-dev` | Baked at build time; also picks runtime defaults. |
| `MODEL_DIR` | `/models/flux` | Where the weights live in the image. |
| `WARMUP` | `1` | Run the one-step warmup at worker start. |
| `LOG_LEVEL` | `INFO` | Handler log level. |
| `BUCKET_ENDPOINT_URL` | unset | Set to return S3 URLs instead of base64. |

Building the ungated, 4-step variant is a one-value change:

```bash
MODEL_ID=black-forest-labs/FLUX.1-schnell ./scripts/build_and_push.sh schnell-v1
```

The handler picks up schnell's defaults (4 steps, guidance 0.0, 256-token sequence
length) automatically from `MODEL_ID`.

## What was actually exercised

Being explicit, since the repository carries three Dockerfiles:

| Path | Status |
| --- | --- |
| `Dockerfile.kaniko` | **Built and deployed.** Produced `flux-runpod:v1`, 29.87 GB. |
| `Dockerfile` | Not run. It is the BuildKit-secret reference for environments where BuildKit works. |
| `Dockerfile.volume` | Not built. Written as the fallback when the throttling described above looked terminal. |

The measured results below all come from the deployed Kaniko image.

## Results

See [`docs/RESULTS.md`](docs/RESULTS.md) for the deployed endpoint, measured cold
start and warm latency, cost per image, and sample generations.

## Licence

Code: MIT (`LICENSE`). FLUX.1-dev weights are covered by the
[FLUX.1-dev Non-Commercial Licence](https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/LICENSE.md)
which is non-commercial use only, and is why the image is not published publicly.
FLUX.1-schnell is Apache-2.0.
