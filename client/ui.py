#!/usr/bin/env python3
"""Browser UI for the deployed RunPod endpoint.

    pip install -r client/requirements-ui.txt
    export RUNPOD_API_KEY=...  RUNPOD_ENDPOINT_ID=...
    python client/ui.py                  # http://127.0.0.1:7860

A Gradio front end over the same POST /runsync call as call_endpoint.py. The
browser only ever talks to this process; the API key is read from the
environment here and attached server-side, so it never reaches the page.

Binds to localhost by default. --share publishes a public Gradio link, and
anyone holding it can spend GPU time on your key, so use it deliberately.
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import sys
import tempfile
import time
from pathlib import Path

import gradio as gr
import requests
from PIL import Image

BASE = "https://api.runpod.ai/v2"

# Mirrors src/schema.py. The UI enforces the same ranges so a bad value is
# caught before it costs a round trip to a GPU worker.
SIZE_MULTIPLE = 16
MIN_SIZE, MAX_SIZE = 256, 1536
MAX_STEPS = 50
MAX_IMAGES = 4
MAX_PROMPT_CHARS = 2000
MAX_SEED = 2**63 - 1
FORMATS = ["PNG", "JPEG", "WEBP"]

# The handler's step/guidance defaults depend on MODEL_ID. These are FLUX.1-dev's,
# which is what is deployed; for schnell use 4 steps and guidance 0.
DEFAULT_STEPS = 28
DEFAULT_GUIDANCE = 3.5

# A cold worker can sit IN_QUEUE for minutes while the 30 GB image is pulled, so
# the UI waits as long as the CLI does before giving up.
TIMEOUT = 900

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}

API_KEY = os.environ.get("RUNPOD_API_KEY")
ENDPOINT = os.environ.get("RUNPOD_ENDPOINT_ID")

# Generated files are written here so the gallery serves the exact bytes the
# worker returned, in the requested format, rather than a re-encoded copy.
OUT_DIR = Path(tempfile.mkdtemp(prefix="flux-ui-"))


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"})
    return session


def _http_error(exc: requests.HTTPError) -> gr.Error:
    code = exc.response.status_code if exc.response is not None else None
    if code == 401:
        return gr.Error("RunPod rejected the API key (401). Check RUNPOD_API_KEY.")
    if code == 404:
        return gr.Error("Endpoint not found (404). Check RUNPOD_ENDPOINT_ID.")
    # Non-2xx is reserved for platform failures; application errors come back as 200.
    return gr.Error(f"RunPod returned HTTP {code}: {exc.response.text[:300] if exc.response is not None else exc}")


def call(payload: dict, progress: gr.Progress) -> dict:
    """POST to /runsync and, if the job outlives the sync window, poll /status.

    Same contract as call_endpoint.run_sync, but raises gr.Error instead of
    exiting so a failure shows up in the browser and the server keeps running.
    """
    session = _session()
    deadline = time.time() + TIMEOUT
    try:
        progress(0, desc="Submitting to /runsync")
        resp = session.post(f"{BASE}/{ENDPOINT}/runsync", json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        body = resp.json()

        delay = 1.0
        while body.get("status") in {"IN_QUEUE", "IN_PROGRESS"} and body.get("id"):
            if time.time() > deadline:
                raise gr.Error(f"Job {body['id']} did not finish within {TIMEOUT}s. It may still complete on RunPod.")
            hint = " (a cold worker can queue for minutes)" if body["status"] == "IN_QUEUE" else ""
            progress(None, desc=f"{body['status']}{hint}, job {body['id']}")
            time.sleep(delay)
            delay = min(delay * 1.5, 5.0)  # back off so polling does not spam the API
            resp = session.get(f"{BASE}/{ENDPOINT}/status/{body['id']}", timeout=60)
            resp.raise_for_status()
            body = resp.json()
    except requests.HTTPError as exc:
        raise _http_error(exc) from None
    except requests.Timeout:
        raise gr.Error(f"No response from RunPod within {TIMEOUT}s.") from None
    except requests.RequestException as exc:
        raise gr.Error(f"Could not reach RunPod: {exc}") from None
    except ValueError:
        raise gr.Error("RunPod returned a response that is not JSON.") from None

    status = body.get("status")
    if status not in TERMINAL | {None}:
        raise gr.Error(f"Unexpected job status {status!r}.")
    if status not in {"COMPLETED", None}:
        raise gr.Error(f"Job {status}: {body.get('error') or 'no error message returned'}")

    result = body.get("output", body)
    # Application errors (validation_error / inference_error) arrive as HTTP 200
    # with an "error" field, so they have to be checked for explicitly.
    if isinstance(result, dict) and result.get("error"):
        kind = result.get("error_type", "error").replace("_", " ")
        raise gr.Error(f"{kind}: {result['error']}")
    if not isinstance(result, dict):
        raise gr.Error(f"Unexpected output from the worker: {str(result)[:300]}")
    return {"body": body, "result": result}


def _materialise(result: dict) -> list[str]:
    """Turn the worker's images into local files, whichever delivery mode is on.

    base64 is the default. With BUCKET_ENDPOINT_URL set on the endpoint the
    worker returns presigned S3 URLs instead, which are fetched here.
    """
    fmt = result.get("parameters", {}).get("output_format", "PNG").lower()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    paths = []
    for index, item in enumerate(result.get("images") or []):
        try:
            if result.get("delivery") == "s3_url":
                resp = requests.get(item, timeout=120)
                resp.raise_for_status()
                blob = resp.content
            else:
                blob = base64.b64decode(item)
            Image.open(io.BytesIO(blob)).verify()  # fail here, not as a broken thumbnail
        except Exception as exc:  # noqa: BLE001 - report any decode/fetch failure to the user
            raise gr.Error(f"Image {index} could not be loaded: {exc}") from None
        path = OUT_DIR / f"flux-{stamp}-{result.get('seed', 'na')}-{index}.{fmt}"
        path.write_bytes(blob)
        paths.append(str(path))
    return paths


def generate(prompt, width, height, steps, guidance, seed, num_images, output_format,
             progress=gr.Progress()):
    prompt = (prompt or "").strip()
    if not prompt:
        raise gr.Error("Enter a prompt.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise gr.Error(f"Prompt exceeds {MAX_PROMPT_CHARS} characters.")

    payload: dict = {
        "prompt": prompt,
        "width": int(width),
        "height": int(height),
        "num_inference_steps": int(steps),
        "guidance_scale": float(guidance),
        "num_images": int(num_images),
        "output_format": output_format,
    }
    # A textbox rather than a number field: seeds go up to 2**63 - 1, beyond the
    # 2**53 that a JavaScript number can hold exactly.
    seed = (seed or "").strip()
    if seed:
        try:
            payload["seed"] = int(seed)
        except ValueError:
            raise gr.Error("Seed must be a whole number, or blank for random.") from None
        if not 0 <= payload["seed"] <= MAX_SEED:
            raise gr.Error(f"Seed must be between 0 and {MAX_SEED}.")

    wall_start = time.perf_counter()
    response = call({"input": payload}, progress)
    wall = time.perf_counter() - wall_start
    body, result = response["body"], response["result"]

    paths = _materialise(result)

    summary = {
        "seed": result.get("seed"),
        # RunPod reports its own queue/execution split alongside the output.
        "delayTime_ms": body.get("delayTime"),
        "executionTime_ms": body.get("executionTime"),
        "client_wall_seconds": round(wall, 2),
        "metrics": result.get("metrics"),
        "parameters": result.get("parameters"),
        "delivery": result.get("delivery"),
    }
    if result.get("delivery") == "s3_url":
        summary["urls"] = result.get("images")
    return paths, str(result.get("seed", "")), summary


def health(progress=gr.Progress()):
    return call({"input": {"action": "health"}}, progress)["result"]


def build() -> gr.Blocks:
    with gr.Blocks(title="FLUX.1 on RunPod Serverless", analytics_enabled=False) as ui:
        gr.Markdown(
            "# FLUX.1 on RunPod Serverless\n"
            f"Calling endpoint `{ENDPOINT}` via `/runsync`. "
            "The first request after scale-to-zero waits for a cold worker."
        )
        with gr.Row():
            with gr.Column(scale=2):
                prompt = gr.Textbox(
                    label="Prompt", lines=3, max_length=MAX_PROMPT_CHARS,
                    placeholder="a cinematic photograph of a glass terrarium at golden hour, 85mm",
                )
                with gr.Row():
                    width = gr.Slider(MIN_SIZE, MAX_SIZE, value=1024, step=SIZE_MULTIPLE, label="Width")
                    height = gr.Slider(MIN_SIZE, MAX_SIZE, value=1024, step=SIZE_MULTIPLE, label="Height")
                with gr.Row():
                    steps = gr.Slider(1, MAX_STEPS, value=DEFAULT_STEPS, step=1, label="Inference steps")
                    guidance = gr.Slider(0.0, 20.0, value=DEFAULT_GUIDANCE, step=0.1, label="Guidance scale",
                                         info="FLUX is guidance-distilled; 3.5 is the sweet spot.")
                with gr.Row():
                    seed = gr.Textbox(label="Seed", placeholder="blank = random")
                    num_images = gr.Slider(1, MAX_IMAGES, value=1, step=1, label="Images")
                    output_format = gr.Dropdown(FORMATS, value="PNG", label="Output format")
                with gr.Row():
                    run = gr.Button("Generate", variant="primary")
                    check = gr.Button("Health check")
            with gr.Column(scale=3):
                gallery = gr.Gallery(label="Output", columns=2, height=560)
                used_seed = gr.Textbox(label="Seed used", interactive=False)
                details = gr.JSON(label="Timing and metrics")

        run.click(
            generate,
            inputs=[prompt, width, height, steps, guidance, seed, num_images, output_format],
            outputs=[gallery, used_seed, details],
        )
        prompt.submit(
            generate,
            inputs=[prompt, width, height, steps, guidance, seed, num_images, output_format],
            outputs=[gallery, used_seed, details],
        )
        check.click(health, outputs=details)
    return ui


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1", help="interface to bind (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=7860)
    p.add_argument("--share", action="store_true", help="create a public Gradio link (spends your key)")
    args = p.parse_args()

    if not API_KEY or not ENDPOINT:
        sys.exit("error: set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID")

    build().queue().launch(server_name=args.host, server_port=args.port, share=args.share,
                           allowed_paths=[str(OUT_DIR)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
