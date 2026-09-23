#!/usr/bin/env python3
"""Measure the endpoint: cold start, warm latency, throughput and $/image.

    export RUNPOD_API_KEY=... RUNPOD_ENDPOINT_ID=...
    python client/benchmark.py --runs 5 --gpu-rate 0.00076   # $/s for the GPU tier

RunPod returns `delayTime` (queue + worker start, ms) and `executionTime`
(handler wall time, ms) on every job. Neither is the bill on its own: RunPod
charges for the whole worker lifecycle, meaning start-up, execution and the idle
timeout, from worker start until it fully stops.

So this reports two costs. The steady-state cost charges execution only, which is
what each image adds under sustained load once start-up is amortised. The
isolated-request cost adds worker start-up and the endpoint's idle timeout, which
is what a single request against a scale-to-zero endpoint actually costs. Pass
--idle-timeout to match your endpoint; the RunPod default is 5 seconds.

Run it once with the endpoint scaled to zero active workers for a true cold
number, then again immediately for warm numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "https://api.runpod.ai/v2"


def submit(session: requests.Session, endpoint: str, payload: dict, timeout: int) -> dict:
    started = time.perf_counter()
    resp = session.post(f"{BASE}/{endpoint}/runsync", json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    body["_wall"] = time.perf_counter() - started
    return body


def summarise(label: str, samples: list[dict], gpu_rate: float, idle_timeout: float = 5.0) -> dict:
    ok = [s for s in samples if s.get("status") == "COMPLETED"]
    if not ok:
        return {"label": label, "runs": len(samples), "completed": 0}

    delay = [s.get("delayTime", 0) / 1000 for s in ok]
    exec_ = [s.get("executionTime", 0) / 1000 for s in ok]
    wall = [s["_wall"] for s in ok]

    row = {
        "label": label,
        "runs": len(samples),
        "completed": len(ok),
        "delay_s_mean": round(statistics.mean(delay), 2),
        "exec_s_mean": round(statistics.mean(exec_), 2),
        "exec_s_min": round(min(exec_), 2),
        "exec_s_max": round(max(exec_), 2),
        "wall_s_mean": round(statistics.mean(wall), 2),
    }
    if len(ok) > 1:
        row["exec_s_stdev"] = round(statistics.stdev(exec_), 2)
    if gpu_rate:
        mean_exec = statistics.mean(exec_)
        # Under sustained load the worker is already up, so each image adds only
        # its execution time.
        row["cost_per_image_steady_usd"] = round(mean_exec * gpu_rate, 5)
        row["images_per_usd_steady"] = round(1 / (mean_exec * gpu_rate))
        # A single request against a scale-to-zero endpoint also pays for the
        # worker start-up it triggered and the idle timeout before it stops.
        mean_delay = statistics.mean(delay)
        isolated = (mean_delay + mean_exec + idle_timeout) * gpu_rate
        row["cost_per_image_isolated_usd"] = round(isolated, 5)
        row["isolated_assumes"] = (f"start-up {round(mean_delay, 1)}s "
                                   f"+ exec {round(mean_exec, 1)}s "
                                   f"+ idle {idle_timeout}s")
    return row


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=int, default=5, help="sequential warm requests (default 5)")
    p.add_argument("--concurrency", type=int, default=0, help="also fire this many requests at once")
    p.add_argument("--size", default="1024x1024")
    p.add_argument("--steps", type=int, default=28)
    p.add_argument("--gpu-rate", type=float, default=0.0,
                   help="GPU $/second from the RunPod pricing page (e.g. 0.000756 for A100 80GB)")
    p.add_argument("--idle-timeout", type=float, default=5.0,
                   help="the endpoint's idle timeout in seconds, used for the isolated-request cost (default 5, RunPod's default)")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--out", default="benchmark-results.json")
    args = p.parse_args()

    api_key = os.environ.get("RUNPOD_API_KEY")
    endpoint = os.environ.get("RUNPOD_ENDPOINT_ID")
    if not api_key or not endpoint:
        sys.exit("error: set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID")

    width, height = (int(v) for v in args.size.lower().split("x"))
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {api_key}"})

    def payload(i: int) -> dict:
        return {"input": {
            "prompt": f"benchmark frame {i}: an isometric miniature city block, soft studio light",
            "width": width, "height": height,
            "num_inference_steps": args.steps,
            "seed": 1000 + i,
            "output_format": "JPEG", "quality": 85,
        }}

    report: dict = {"endpoint": endpoint, "size": args.size, "steps": args.steps, "runs": []}

    print(f"first request (cold if no worker is running)...", flush=True)
    first = submit(session, endpoint, payload(0), args.timeout)
    report["runs"].append(summarise("first_request", [first], args.gpu_rate, args.idle_timeout))
    print(json.dumps(report["runs"][-1], indent=2), flush=True)

    warm = []
    for i in range(1, args.runs + 1):
        print(f"warm request {i}/{args.runs}...", flush=True)
        warm.append(submit(session, endpoint, payload(i), args.timeout))
    if warm:
        report["runs"].append(summarise(f"warm_sequential_x{len(warm)}", warm, args.gpu_rate, args.idle_timeout))
        print(json.dumps(report["runs"][-1], indent=2), flush=True)

    if args.concurrency:
        print(f"firing {args.concurrency} concurrent requests...", flush=True)
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            burst = list(pool.map(
                lambda i: submit(session, endpoint, payload(100 + i), args.timeout),
                range(args.concurrency),
            ))
        row = summarise(f"concurrent_x{args.concurrency}", burst, args.gpu_rate, args.idle_timeout)
        row["burst_wall_s"] = round(time.perf_counter() - started, 2)
        report["runs"].append(row)
        print(json.dumps(row, indent=2), flush=True)

    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
