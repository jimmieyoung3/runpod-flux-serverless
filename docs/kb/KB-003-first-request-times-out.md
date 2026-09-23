# KB-003: The first request to a new endpoint times out, later requests work

**Applies to:** Serverless endpoints, first request after deployment or after
scaling to zero.

## Symptoms

Your first call to `/runsync` hangs and eventually times out, or your HTTP
client gives up. Calling again a few minutes later works normally and returns in
seconds.

## Cause

This is cold start, and on a brand new endpoint it includes work that only ever
happens once:

| Phase | Typical time | Happens |
| --- | --- | --- |
| Scheduling a worker | seconds, or minutes for a large image | first request, see KB-002 |
| Pulling the image to the host | minutes for a large image | once per host |
| Container start and model load | seconds | every cold worker |
| Inference | seconds | every request |

Measured on a 29.87 GB image serving FLUX.1-dev: the very first request reported
a `delayTime` of 609 seconds. Once the image was cached on that host, a later
cold start reported 15.5 seconds, of which 7.2 seconds was loading the model from
local disk.

`/runsync` holds an HTTP connection open for the whole of that, which is why it
is the wrong call to make against a cold endpoint.

## Resolution

**Use `/run` and poll `/status` for anything that might be cold.** `/run`
returns a job ID immediately, so no connection has to stay open:

```bash
JOB=$(curl -s -X POST "https://api.runpod.ai/v2/$ENDPOINT/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"prompt":"a red fox in a snowy forest"}}' | jq -r .id)

# poll until COMPLETED, backing off between checks
curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" \
  "https://api.runpod.ai/v2/$ENDPOINT/status/$JOB"
```

**Raise the endpoint's execution timeout** so a cold request has room to finish.

**Read `delayTime` and `executionTime` separately.** Every job returns both.
`delayTime` is queue plus worker start-up; `executionTime` is your handler's own
time. A slow first request with a normal `executionTime` is a cold start, not a
slow handler.

Note that `executionTime` is a job metric, not your bill. Runpod charges for the
worker's whole lifecycle: start-up including model loading, execution, and the
idle timeout before it scales down. Cold starts therefore cost you twice, once in
latency and once on the invoice.

## Making cold starts shorter

- **Enable FlashBoot** on the endpoint.
- **Load your model once, at import**, not inside the handler. Start-up is billed
  either way, but at import it is paid once per worker instead of once per
  request.
- **Add a warm-up pass** at start-up: one cheap, low-step inference so the first
  real request does not absorb CUDA kernel autotuning and lazy initialisation.
- **Keep the model local to the worker**, either baked into the image or on a
  network volume, so no cold worker waits on an external download.
- **Keep one active worker** if predictable latency matters more than cost. An
  idle active worker bills continuously.

## Before a live demo

Set active workers to 1 about thirty minutes beforehand, confirm with one real
request, then set it back to 0 afterwards. Cold start is the most common reason
a working endpoint looks broken in front of an audience.

## Related

- KB-002: workers stay throttled and jobs sit in the queue
