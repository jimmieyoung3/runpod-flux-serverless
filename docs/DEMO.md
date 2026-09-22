# Running the live demo

A runbook for demonstrating the endpoint in a meeting. Every command is
copy-paste; nothing needs editing except the prompt.

---

## T-30 minutes: pre-warm

**This is the step that prevents a disaster.** With no worker running, the first
request takes 15-30 s, and occasionally much longer: a ~30 GB image means the
scheduler needs a host that can cache it, and that took ~10 minutes once.

In the RunPod console:

1. **Serverless** → **flux-dev-txt2img**
2. **Edit Endpoint**
3. Set **Active Workers** to **1**
4. Save

That pins a warm worker, so responses are instant. It costs $1.22-2.72/hr
depending on the GPU. **Set it back to 0 after the meeting.**

---

## T-5 minutes: smoke test

Open a terminal and run all four lines:

```bash
cd ~/runpod/flux-serverless
export RUNPOD_API_KEY=$(cat ~/.runpod_key)
export RUNPOD_ENDPOINT_ID=ux61jghq0twkgq
./scripts/demo.sh "a copper teapot on a windowsill, morning light"
```

You should see worker state, then metrics, then the image opens in the Windows
viewer. Expect `executionTime` of 14-30 s depending on the GPU.

If `workers` shows `idle: 0, ready: 0`, the pre-warm did not take effect, so go
back and check Active Workers is 1.

**Leave this terminal open.** Do not close it; the two `export` lines are lost
if you do.

---

## During the meeting

### 1. Lead with the result, not the code

Show an image from `docs/assets/` and give the headline:

> Text prompt in, image out. 14 seconds on an A100, about one cent an image,
> and it scales to zero when nobody is using it.

### 2. Ask them for a prompt

This is the most convincing thing you can do, because it proves nothing is pre-baked.

```bash
./scripts/demo.sh "whatever they say"
```

While it runs, narrate what is happening: the request goes to RunPod's queue, a
warm worker picks it up, the model is already resident in GPU memory because the
weights are baked into the image, 28 denoising steps, image comes back as base64.

### 3. Point at the metrics

```
"delayTime_ms": 22          <- queue time; near zero because the worker is warm
"executionTime_ms": 14070   <- what RunPod actually bills
"cold_start": 7.25          <- seconds to load 33.7 GB from local disk
```

The line worth saying out loud: *"loading those weights from Hugging Face instead
would take about ten minutes, and that 7.2 seconds is why they are baked into the
image."*

### 4. Show the console

RunPod → Serverless → the endpoint. Show **Workers** and **Logs**. This proves it
is real infrastructure rather than something running on your laptop.

### 5. Offer the story

The Buildah/Kaniko constraints in §3 of the PDF. Anyone can follow a tutorial;
far fewer have hit `CAP_SYS_ADMIN` restrictions on a provider and worked around
them.

---

## Useful one-liners

Health check, no image generated, costs ~nothing:

```bash
.venv/bin/python client/call_endpoint.py --health
```

Raw curl, if someone wants to see the bare API:

```bash
curl -s -X POST "https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/runsync" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"prompt":"a red fox in a snowy forest","seed":7}}' \
  | head -c 400
```

Worker state at a glance:

```bash
curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" \
  "https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/health"
```

Non-square output, to show dimension handling:

```bash
./scripts/demo.sh "a lighthouse in a storm" && \
  .venv/bin/python client/call_endpoint.py "a tall waterfall in a canyon" \
    --size 832x1216 --out demo-output
```

---

## If something breaks

| Symptom | Do this |
| --- | --- |
| Request hangs past ~60 s | Say "this is a cold start, it is pulling a 30 GB image", then switch to `docs/assets/` images while it finishes. |
| `error: set RUNPOD_API_KEY` | The terminal was closed. Re-run the two `export` lines. |
| Image does not open | It is still saved. Run `explorer.exe .` in `demo-output/`. |
| Endpoint returns an error body | Show it, since the handler returns structured errors on purpose. Then fall back to saved images. |
| Network dies entirely | Play the backup recording (see below). |

**Record a backup.** Before the meeting, screen-record one successful run. If the
venue's network fails, you still have a demo. This costs five minutes and has
saved many people.

---

## After the meeting

1. RunPod console → endpoint → **Active Workers back to 0**
2. Confirm nothing is billing:

```bash
curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" \
  "https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/health"
```

`idle`, `ready` and `running` should all fall to 0 within a minute or two.

3. When the process is fully over: delete the endpoint, delete the container
   registry credential in RunPod settings, and remove the `runpod-casestudy` SSH
   key from your RunPod account.
