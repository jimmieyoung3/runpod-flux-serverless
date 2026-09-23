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
