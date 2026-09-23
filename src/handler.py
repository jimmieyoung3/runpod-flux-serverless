"""RunPod serverless entrypoint for FLUX text-to-image.

Lifecycle
---------
Import time  : the pipeline is loaded (and optionally warmed) once per worker.
               RunPod treats this as worker start-up / cold start.
Per request  : validate -> generate -> encode -> return base64 (or an S3 URL).

The module-level load is intentional. RunPod bills the whole worker lifecycle
(start-up, execution and idle timeout), so start-up is billed either way; doing
it here pays the measured 7.2 to 8.0 s once per worker rather than once per
request.
"""

from __future__ import annotations

import base64
import logging
import os
import time
import traceback
import uuid
from pathlib import Path

import runpod
from runpod.serverless.utils import rp_upload

from predict import DEFAULT_GUIDANCE, DEFAULT_STEPS, FluxPredictor, encode_image
from schema import ValidationError, validate

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("handler")

DEFAULTS = {"num_inference_steps": DEFAULT_STEPS, "guidance_scale": DEFAULT_GUIDANCE}

# Set BUCKET_ENDPOINT_URL (plus BUCKET_ACCESS_KEY_ID / BUCKET_SECRET_ACCESS_KEY)
# on the endpoint to get presigned URLs back instead of base64. Large PNGs blow
# past RunPod's ~20 MB /runsync response ceiling, so this is the escape hatch.
UPLOAD_TO_BUCKET = bool(os.environ.get("BUCKET_ENDPOINT_URL"))

predictor = FluxPredictor()

# Fail fast and loudly: a worker that cannot load the model should crash at
# start-up so RunPod's logs show it, rather than failing every request in turn.
predictor.load()
if os.environ.get("WARMUP", "1") == "1":
    try:
        predictor.warmup()
    except Exception:  # noqa: BLE001 - a failed warmup must not kill the worker
        log.warning("Warmup failed, continuing:\n%s", traceback.format_exc())


def _deliver(job_id: str, images, fmt: str, quality: int) -> tuple[list[str], str]:
    """Return (payload, delivery_mode) - either base64 strings or bucket URLs."""
    encoded = [encode_image(img, fmt, quality) for img in images]

    if not UPLOAD_TO_BUCKET:
        return [base64.b64encode(blob).decode("utf-8") for blob in encoded], "base64"

    urls, workdir = [], Path(f"/tmp/{job_id}")
    workdir.mkdir(parents=True, exist_ok=True)
    for blob in encoded:
        path = workdir / f"{uuid.uuid4().hex}.{fmt.lower()}"
        path.write_bytes(blob)
        urls.append(rp_upload.upload_image(job_id, str(path)))
    return urls, "s3_url"


def handler(job: dict) -> dict:
    """Entry point invoked by the RunPod SDK for every queued job."""
    started = time.perf_counter()
    job_id = job.get("id", "local")
    job_input = job.get("input") or {}

    try:
        if job_input.get("action") == "health":
            return {"status": "ok", **predictor.info()}

        params = validate(job_input, DEFAULTS)
        log.info(
            "job=%s %dx%d steps=%d guidance=%.1f n=%d prompt=%r",
            job_id, params["width"], params["height"], params["num_inference_steps"],
            params["guidance_scale"], params["num_images"], params["prompt"][:80],
        )

        result = predictor.generate(params)
        payload, delivery = _deliver(
            job_id, result.images, params["output_format"], params["quality"]
        )

        return {
            "images": payload,
            "delivery": delivery,
            "mime_type": f"image/{params['output_format'].lower()}",
            "seed": result.seed,
            "parameters": {k: v for k, v in params.items() if k != "prompt"},
            "prompt": params["prompt"],
            "metrics": {
                **result.timings,
                "total_seconds": round(time.perf_counter() - started, 3),
                "cold_start": predictor.load_seconds,
            },
        }

    except ValidationError as exc:
        # A client mistake: report it plainly instead of burning a retry.
        log.warning("job=%s rejected: %s", job_id, exc)
        return {"error": str(exc), "error_type": "validation_error"}

    except Exception as exc:  # noqa: BLE001 - surface the traceback to the caller
        log.exception("job=%s failed", job_id)
        # The traceback is useful while developing and is noise, or an
        # information leak, for an end user. Off unless explicitly enabled.
        payload = {
            "error": f"{type(exc).__name__}: {exc}",
            "error_type": "inference_error",
        }
        if os.environ.get("RETURN_TRACEBACK", "0") == "1":
            payload["traceback"] = traceback.format_exc(limit=5)
        return payload


def adjust_concurrency(_current: int) -> int:
    """One in-flight job per worker.

    Generation is GPU-bound, so the expectation is that two concurrent 1024px
    requests would contend rather than overlap usefully. That was not measured
    here: the concurrency test ran with this modifier in place, so the jobs were
    serialised by configuration. Throughput comes from more workers."""
    return 1


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler, "concurrency_modifier": adjust_concurrency})
