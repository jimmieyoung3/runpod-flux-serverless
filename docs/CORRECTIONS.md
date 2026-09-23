# Corrections

Changes made to this repository after the case study PDF was submitted. The PDF
is left as it was sent; these notes record where the repository is now more
accurate than that document.

| Item | In the submitted PDF | Corrected to |
| --- | --- | --- |
| Billing model | "`executionTime` is what RunPod bills" | Runpod bills the whole worker lifecycle: start-up including model loading, execution, and the idle timeout. `executionTime` is a job metric, not the billing unit. |
| Cost per image | $0.0103 to $0.0106, presented as the cost | That is the steady-state cost under sustained load. An isolated request on a scale-to-zero endpoint costs $0.017 to $0.068 depending on GPU and idle timeout. |
| GPU independence | Stated without qualification | Holds under sustained load (3.5% apart). For isolated requests the gap is 52%, and the cheaper tier wins. |
| Hub download | "~10 min from the Hub", in a column headed Measured effect | ~3 minutes, which is what was actually measured during the build. The improvement from baking weights in is ~25x, not ~75x. |
| Base64 ceiling | "hits the ~20 MB ceiling at about four 1024px PNGs" | Four 1024px PNGs from this endpoint measure ~7.3 MB encoded, well inside the ceiling. |
| Warm-up pass | Implied it removes the first-request penalty | A 14% residual remains: 16.0 s cold against a 14.07 s warm mean. The warm-up runs at 512px and one step, which likely misses the production kernel shapes. |
| Concurrency | "two concurrent jobs would slow each other", offered as a finding | Not tested. With one job per worker the two requests ran serially, so flat execution time is a property of the configuration, not evidence about batching. |
| Throttle diagnosis | Presented as image size rather than capacity | Single observation, no control. Leading hypothesis, not a confirmed diagnosis. |
| Images per $1, A100 | 93 | 94 |

## Why these are here rather than silently edited

The billing error is the one that matters. Getting a vendor's charging model
wrong while reasoning about cost is worth recording rather than quietly
overwriting, and the corrected analysis is more useful than the original: the
interesting result is that cost per image is GPU-independent under load but not
for sparse traffic, which reverses the practical advice.

Source for the billing model: https://docs.runpod.io/serverless/pricing

## Second pass

A further review pointed out that the corrections above had not been carried
into the rest of the repository. They now have been.

| Item | Change |
| --- | --- |
| `client/benchmark.py` | Still derived cost from `executionTime` alone, so the tool that produced the numbers used the model that was being corrected. It now reports a steady-state cost and an isolated-request cost, and takes `--idle-timeout`. |
| `docs/RESULTS.md`, `docs/DEPLOY.md`, `docs/DEMO.md` | Repeated "`executionTime` is what RunPod bills". Corrected. |
| `src/handler.py` | Quoted a "~40 s model load" estimate; the measured figure is 7.2 to 8.0 s. The rationale for loading at import is now amortisation, not avoidance. |
| `docs/kb/KB-002` | Said "roughly 10 minutes pulling from Hugging Face"; the measured figure is ~3 minutes. |
| `README.md`, `adjust_concurrency` docstring | Stated the batching claim as fact. Now stated as untested. |
| `src/predict.py` | Comment said "sequential module offload"; the code calls `enable_model_cpu_offload()`, which is model-level. Also notes the path has never run, since every worker landed on a 48 GB or 80 GB card. |

## Bugs found in the same review

| Bug | Fix |
| --- | --- |
| A seed larger than 64 bits passed validation, then failed inside `torch.manual_seed` and was reported as an `inference_error`, breaking the client-error / server-error split. | `seed` is now range-checked in the schema and rejected as a `validation_error`. |
| A misspelled action, for example `"helth"`, fell through and ran a full paid generation. | Unknown `action` values are now rejected. |
| Negative seeds were silently replaced with a random one, which was undocumented. | Now rejected, so `None` is the only path to a random seed. |
| Tracebacks were always returned to the caller. | Off by default, enabled with `RETURN_TRACEBACK=1`. |

## Two notes on the record

**Spend.** RESULTS.md now says $1.71 where the submitted PDF says $0.85. The
difference is testing done after submission, including the work that found and
fixed the Blackwell GPU incompatibility described below.

**The "copy nits" commit.** Commit `1a88893`, "Fix two copy nits in the
submission PDF", predates submission. The PDF in this repository is
byte-identical to the one that was sent, and has not been changed since.

## Known, not fixed

- The isolated-request cost uses the warm execution mean of 14.07 s rather than
  the 16.0 s measured on the cold request, and applies the A100's measured
  15.5 s start-up to the A40, which was never measured cold. Both make the
  isolated figures approximate.
- After an `inference_error` such as a CUDA out-of-memory, the worker keeps
  serving. Returning `refresh_worker` would recycle a worker left in a bad
  state, and is the right behaviour for production.
- An endpoint GPU list that includes Blackwell cards will wedge: `torch 2.5.1`
  with CUDA 12.4 has no kernels for `sm_120`, so the worker boots, reports
  healthy, and never completes a job. The deployed endpoint had this and it was
  removed. A newer torch build would be the real fix.
