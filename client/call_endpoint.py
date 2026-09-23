#!/usr/bin/env python3
"""Call the deployed RunPod endpoint and save the generated image(s).

    export RUNPOD_API_KEY=...  RUNPOD_ENDPOINT_ID=...
    python client/call_endpoint.py "a red fox in a snowy forest, golden hour"
    python client/call_endpoint.py "..." --async --steps 28 --size 1024x1024

Uses /runsync by default (blocks up to ~90 s, which covers a warm 1024px
request) and falls back to the /run + /status polling pattern with --async,
which is what you want when a cold worker has to load 34 GB of weights first.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BASE = "https://api.runpod.ai/v2"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("prompt", nargs="?", help="text prompt; omit when using --health")
    p.add_argument("--size", default="1024x1024", help="WxH, each a multiple of 16 (default 1024x1024)")
    p.add_argument("--steps", type=int, help="inference steps (default: model-appropriate)")
    p.add_argument("--guidance", type=float, help="guidance scale (dev: 3.5, schnell: 0)")
    p.add_argument("--seed", type=int, help="seed for reproducible output")
    p.add_argument("--n", type=int, default=1, dest="num_images", help="images per request (1-4)")
    p.add_argument("--format", default="PNG", choices=["PNG", "JPEG", "WEBP"])
    p.add_argument("--out", default="outputs", help="directory for saved images")
    p.add_argument("--async", dest="use_async", action="store_true", help="submit to /run and poll /status")
    p.add_argument("--timeout", type=int, default=900, help="seconds to wait when polling (default 900)")
    p.add_argument("--health", action="store_true", help="ask the worker to report model/GPU info only")
    return p.parse_args()


def build_payload(args: argparse.Namespace) -> dict:
    if args.health:
        return {"input": {"action": "health"}}

    if not args.prompt:
        sys.exit("error: a prompt is required (or pass --health)")

    try:
        width, height = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        sys.exit(f"error: --size must look like 1024x1024, got {args.size!r}")

    payload: dict = {
        "prompt": args.prompt,
        "width": width,
        "height": height,
        "num_images": args.num_images,
        "output_format": args.format,
    }
    for key, value in (
        ("num_inference_steps", args.steps),
        ("guidance_scale", args.guidance),
        ("seed", args.seed),
    ):
        if value is not None:
            payload[key] = value
    return {"input": payload}


def run_sync(session: requests.Session, endpoint: str, payload: dict, timeout: int) -> dict:
    """POST to /runsync, then keep waiting if the job outlives the sync window.

    /runsync does not block indefinitely. When a job takes longer than RunPod's
    synchronous window it returns the job envelope with status IN_QUEUE or
    IN_PROGRESS instead of the output, and the caller is expected to poll
    /status from there. Treating that as a failure loses a job that is about to
    succeed, which is exactly what it looked like the first time this ran.
    """
    resp = session.post(f"{BASE}/{endpoint}/runsync", json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()

    if body.get("status") in {"IN_QUEUE", "IN_PROGRESS"} and body.get("id"):
        print(f"still running after the sync window, polling job {body['id']}", flush=True)
        return poll(session, endpoint, body["id"], timeout)
    return body


def run_async(session: requests.Session, endpoint: str, payload: dict, timeout: int) -> dict:
    resp = session.post(f"{BASE}/{endpoint}/run", json=payload, timeout=60)
    resp.raise_for_status()
    job_id = resp.json()["id"]
    print(f"queued job {job_id}", flush=True)
    return poll(session, endpoint, job_id, timeout)


def poll(session: requests.Session, endpoint: str, job_id: str, timeout: int) -> dict:
    """Poll /status until the job reaches a terminal state, backing off as it waits."""
    deadline = time.time() + timeout
    delay, last_status = 1.0, None
    while time.time() < deadline:
        status = session.get(f"{BASE}/{endpoint}/status/{job_id}", timeout=60).json()
        state = status.get("status")
        if state != last_status:
            print(f"  status: {state}", flush=True)
            last_status = state
        if state in {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}:
            return status
        time.sleep(delay)
        delay = min(delay * 1.5, 5.0)  # back off so polling does not spam the API

    sys.exit(f"error: job {job_id} did not finish within {timeout}s")


def save_images(result: dict, out_dir: Path, fmt: str) -> list[Path]:
    images = result.get("images") or []
    if not images:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    saved = []

    for index, item in enumerate(images):
        if result.get("delivery") == "s3_url":
            print(f"  image {index}: {item}")
            continue
        path = out_dir / f"flux-{stamp}-{result.get('seed', 'na')}-{index}.{fmt.lower()}"
        path.write_bytes(base64.b64decode(item))
        saved.append(path)
    return saved


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("RUNPOD_API_KEY")
    endpoint = os.environ.get("RUNPOD_ENDPOINT_ID")
    if not api_key or not endpoint:
        sys.exit("error: set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID")

    payload = build_payload(args)
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    wall_start = time.perf_counter()
    body = run_async(session, endpoint, payload, args.timeout) if args.use_async \
        else run_sync(session, endpoint, payload, args.timeout)
    wall = time.perf_counter() - wall_start

    if body.get("status") not in {"COMPLETED", None}:
        print(json.dumps(body, indent=2))
        return 1

    result = body.get("output", body)
    if isinstance(result, dict) and result.get("error"):
        print(json.dumps(result, indent=2))
        return 1

    saved = save_images(result, Path(args.out), args.format)

    summary = {k: v for k, v in result.items() if k != "images"}
    summary["client_wall_seconds"] = round(wall, 2)
    # RunPod reports its own queue/execution split alongside the output.
    for key in ("delayTime", "executionTime"):
        if key in body:
            summary[key + "_ms"] = body[key]
    print(json.dumps(summary, indent=2))

    for path in saved:
        print(f"saved {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
