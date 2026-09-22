# Results

All numbers below were measured against the live endpoint on 22 September 2026.
Raw benchmark output: [`benchmark-results.json`](benchmark-results.json) (A40)
and [`benchmark-a100.json`](benchmark-a100.json) (A100).

## Deployed endpoint

| | |
| --- | --- |
| Endpoint ID | `ux61jghq0twkgq` (`flux-dev-txt2img`) |
| Image | `docker.io/jimmieyoung3/flux-runpod:v1`, **29.87 GB**, private |
| Layers | 6; the weights layer is 26.53 GB compressed |
| Model | `black-forest-labs/FLUX.1-dev`, bfloat16, baked into the image |
| GPU tiers | 11 selected; workers landed on **A40 48 GB** and **A100-SXM4 80 GB** |
| Workers | 0 min / 2 max, 60 s idle timeout, FlashBoot enabled |
| CPU offload | not triggered; both GPUs are above the 40 GB threshold |

## Latency

1024×1024, 28 steps, guidance 3.5. `executionTime` is what RunPod bills;
`delayTime` is queue plus worker start-up.

| Scenario | delayTime | executionTime | Wall |
| --- | --- | --- | --- |
| First-ever cold start, health call only | **609 s** | 0.04 s | 650 s |
| Cold start, image cached on host (A100) | **15.5 s** | 16.0 s | 35.2 s |
| Warm, A40 (mean of 5) | 0.69 s | **30.32 s** (σ 0.06) | 33.1 s |
| Warm, A100 (mean of 4) | 0.80 s | **14.07 s** (σ 0.04) | 16.0 s |
| 2 concurrent, A40 | 16.42 s | 30.40 s | 49.9 s (burst 66.6 s) |

The first row is a health call, which reports model and GPU information without
generating, so its executionTime covers only the round trip. It is listed because
its delayTime captures the one-time cost of scheduling a worker and pulling a
30 GB image onto a host that had never seen it.

Model load from the baked-in weights: **7.2 to 8.0 s**. The same weights fetched
from the Hugging Face Hub take roughly 10 minutes, so baking them in is a ~75×
improvement on the part of cold start that the worker actually controls.

The 0.06 s standard deviation across warm runs confirms the pipeline is resident
and nothing is re-loaded or re-fetched per request.

## Cost

| GPU | $/hr | s/image | $/image | Images per $1 |
| --- | --- | --- | --- | --- |
| A40 48 GB | $1.22 | 30.32 | **$0.0103** | 97 |
| A100-SXM4 80 GB | $2.72 | 14.07 | **$0.0106** | 93 |

The most useful finding here: **cost per image is nearly GPU-independent**. A
2.2× faster card costs 2.2× more per second, so the two differ by 3%. Pick the
GPU tier for the latency you need, not to save money. What actually moves cost is
step count, resolution, and not leaving workers idling.

Total spend for the whole exercise, including two build pods and all testing:
**$0.85**.

## Concurrency

Two simultaneous requests left `executionTime` flat at 30.4 s but pushed mean
queue delay to 16.4 s, and the burst took 66.6 s wall. That is the intended
behaviour of `adjust_concurrency` returning 1: generation saturates the GPU, so
a second in-flight job would slow both rather than overlap usefully. Throughput
scales by adding workers, not by batching onto one card.

## The cost of a 30 GB image

The first request sat in `throttled` for ~10 minutes before a worker was placed.
Widening from 7 to 11 GPU tiers did not help, which points at the image rather
than GPU scarcity: a worker host must cache ~30 GB before it can start, and that
is a smaller pool of hosts than "any host with a free GPU".

So the baked-weights decision has a measurable cost as well as a measurable
benefit:

| | Baked weights (deployed) | Network volume (`Dockerfile.volume`) |
| --- | --- | --- |
| Model available in | 7.2 s | ~10 min first boot, then volume read |
| First scheduling | ~10 min throttle | fast, ~9 GB image |
| Runtime Hub dependency | none | first boot only |

For a steady endpoint the baked image is the better trade. For one that scales
from zero often, or across many regions, the volume variant schedules faster.

## Sample generations

All images are unmodified endpoint output, 28 steps, guidance 3.5.

| Prompt | Seed | Size | Output |
| --- | --- | --- | --- |
| a cinematic photograph of a glass terrarium on a windowsill at golden hour, shallow depth of field, 85mm | 42 | 1024² | `assets/flux-20260922-122015-42-0.png` |
| a hand-lettered enamel shop sign reading FLUX ON RUNPOD, brushed brass on deep teal, studio product photograph | 7 | 1024² | `assets/flux-20260922-122546-7-0.png` |
| an isometric cutaway of a tiny mechanical workshop, warm tungsten lighting, miniature diorama, tilt-shift | 1234 | 1024² | `assets/flux-20260922-122620-1234-0.png` |
| portrait of an elderly Basque fisherman mending nets at dawn, weathered hands, overcast north light, medium format film | 99 | 832×1216 | `assets/flux-20260922-122650-99-0.png` |
| a lone lighthouse on a basalt cliff during a winter storm, dramatic sea spray, overcast | 2026 | 1024² | `assets/flux-20260922-122955-2026-0.png` |

The enamel-sign image renders its lettering correctly, and the portrait was
generated at a non-square 832×1216 to exercise the dimension snapping in
`src/schema.py`.
