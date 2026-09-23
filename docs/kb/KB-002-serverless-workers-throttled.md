# KB-002: Serverless workers stay "throttled" and jobs sit in the queue

**Applies to:** Serverless endpoints, particularly those using container images
larger than about 20 GB.

## Symptoms

Your endpoint accepts requests but nothing runs. The health endpoint shows jobs
queued and a worker in `throttled`:

```bash
curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" \
  "https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/health"
```

```json
{"jobs":{"completed":0,"inQueue":2,"inProgress":0},
 "workers":{"idle":0,"initializing":0,"ready":0,"running":0,"throttled":1}}
```

The endpoint is not failing. Jobs are not erroring. Nothing is moving.

## What "throttled" means

Runpod has accepted your endpoint but cannot currently place a worker that
matches its requirements. Billing runs from when a worker starts until it fully
stops, so while nothing has been placed there is nothing to bill.

## Cause

Two things cause this, and it is worth telling them apart.

**1. No capacity in your selected GPU tiers.** The usual cause, and the first
thing to rule out.

**2. Your image is too large for most hosts to cache.** Less obvious. A worker
host has to pull and cache your entire image before it can start a worker. A
30 GB image narrows the eligible pool from "hosts with a free GPU" to "hosts
with a free GPU *and* room to cache 30 GB", which is a much smaller set.

## How to tell them apart

Add more GPU types to the endpoint and watch what happens.

If throttling clears, it was capacity. If it does not change, the image size is
the more likely constraint. In the case that produced this article, widening
from 7 GPU tiers to 11, including H100 and H200, made no difference to a 29.87 GB
image, and the throttle cleared on its own after roughly 10 minutes.

To be clear about confidence: this rests on a single observation with no control.
Widening the GPU list did not clear the throttle, which makes plain capacity an
unlikely sole explanation, but the image-size account was not confirmed from the
scheduler's side and no small-image comparison was run on the same tier list.
Treat it as the leading hypothesis, not a diagnosis.

## Resolution

**First, wait.** Throttling is often transient, and with no worker placed there is
nothing accruing. Give it 10 to 15 minutes before changing anything.

**Select more GPU types.** A single-tier endpoint can sit unschedulable whenever
that tier is busy. Pick every tier your model actually fits on, in priority
order. If your model needs 40 GB or more of VRAM, that means the 48 GB and 80 GB
classes rather than one specific card.

**Reduce your image size.** This is the durable fix for a large image:

- Check for duplicate weights. Many model repositories ship both a single-file
  checkpoint and the sharded folders your loader actually reads. Excluding the
  duplicates cut one FLUX.1-dev download from 57.8 GB to 33.7 GB.
- Move the weights to a network volume and ship a small image. The first worker
  populates the volume, later workers read from it. The trade is a slower first
  boot in exchange for scheduling that is no longer image-bound.
- Consider quantised weights (fp8, NF4) where the quality cost is acceptable.

**Keep one active worker** if you need predictable start times and can accept
the cost. An idle active worker bills continuously, so this is a latency
decision, not a default.

## Prevention

Before deploying a large image, decide whether the weights belong inside it.
Baking them in gives a fast model load, measured at 7.2 seconds from local disk
against roughly 3 minutes to fetch the same 33.7 GB from Hugging Face on Runpod's
network. The cost
is the scheduling friction described above. For a steady endpoint the trade is
usually worth it. For one that scales from zero frequently, or across several
regions, a smaller image plus a network volume schedules far more reliably.

## Related

- KB-003: the first request to a new endpoint times out
