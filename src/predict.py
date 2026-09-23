"""Model wrapper: owns the FLUX pipeline and turns a validated request into images.

Kept separate from handler.py so the request plumbing can be unit-tested without
a GPU, and so the pipeline is loaded exactly once per worker (at import time,
which RunPod bills as worker start-up rather than as request time).
"""

from __future__ import annotations

import io
import logging
import os
import time
from dataclasses import dataclass, field

import torch
from diffusers import FluxPipeline
from PIL import Image

log = logging.getLogger("flux")

MODEL_DIR = os.environ.get("MODEL_DIR", "/models/flux")
MODEL_ID = os.environ.get("MODEL_ID", "black-forest-labs/FLUX.1-dev")

# FLUX.1-schnell is timestep-distilled: it is trained to run without classifier-free
# guidance in ~4 steps. FLUX.1-dev is guidance-distilled and expects an embedded
# guidance scale around 3.5 over ~28 steps. Defaults follow whichever is baked in.
IS_SCHNELL = "schnell" in MODEL_ID.lower()
DEFAULT_STEPS = 4 if IS_SCHNELL else 28
DEFAULT_GUIDANCE = 0.0 if IS_SCHNELL else 3.5
MAX_SEQUENCE_LENGTH = 256 if IS_SCHNELL else 512

# Below this much VRAM the bf16 transformer (~23.8 GB) plus the T5 text encoder
# (~9.5 GB) will not co-reside on the card, so we stream modules from host RAM.
CPU_OFFLOAD_THRESHOLD_GB = 40


def ensure_weights() -> None:
    """No-op when the weights are baked into the image (the default).

    In the network-volume variant MODEL_DIR points at /runpod-volume/... and is
    empty on the very first worker: fetch once, and every later worker on the
    same volume starts from local disk. Guarded by a lock file so two workers
    racing on a shared volume cannot half-write the same tree.
    """
    marker = os.path.join(MODEL_DIR, "model_index.json")
    if os.path.exists(marker):
        return

    if os.environ.get("HF_HUB_OFFLINE") == "1":
        raise RuntimeError(
            f"No weights at {MODEL_DIR} and HF_HUB_OFFLINE=1. The image was built "
            "without baked weights - unset HF_HUB_OFFLINE and set HF_TOKEN."
        )

    from huggingface_hub import snapshot_download

    lock = os.path.join(os.path.dirname(MODEL_DIR.rstrip("/")) or "/tmp", ".flux-download.lock")
    os.makedirs(os.path.dirname(lock) or "/tmp", exist_ok=True)

    for attempt in range(180):  # wait up to ~30 min for a peer worker to finish
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if os.path.exists(marker):
                return
            log.info("another worker is fetching weights, waiting (%d)", attempt)
            time.sleep(10)
    else:
        raise RuntimeError(f"Timed out waiting for the weight download lock at {lock}")

    try:
        log.warning("Cold volume: downloading %s to %s (~34 GB, one time)", MODEL_ID, MODEL_DIR)
        started = time.perf_counter()
        snapshot_download(
            repo_id=MODEL_ID,
            local_dir=MODEL_DIR,
            token=os.environ.get("HF_TOKEN"),
            ignore_patterns=[
                "flux1-dev.safetensors", "flux1-schnell.safetensors", "ae.safetensors",
                "*.bin", "*.pth", "*.onnx", "*.msgpack", "*.gguf", "*_grid.jpg", "*_grid.jpeg",
            ],
            max_workers=8,
        )
        log.warning("Weights ready in %.0fs", time.perf_counter() - started)
    finally:
        try:
            os.unlink(lock)
        except FileNotFoundError:
            pass


@dataclass
class GenerationResult:
    images: list[Image.Image]
    seed: int
    timings: dict[str, float] = field(default_factory=dict)


class FluxPredictor:
    """Loads once, generates many."""

    def __init__(self) -> None:
        self.pipe: FluxPipeline | None = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.gpu_name = "cpu"
        self.offloaded = False
        self.load_seconds = 0.0

    def load(self) -> None:
        if self.pipe is not None:
            return

        started = time.perf_counter()
        ensure_weights()
        if self.device == "cpu":
            raise RuntimeError(
                "No CUDA device visible. FLUX needs a GPU worker; check the "
                "endpoint's GPU selection in the RunPod console."
            )

        props = torch.cuda.get_device_properties(0)
        self.gpu_name = props.name
        vram_gb = props.total_memory / 1e9
        log.info("Loading %s from %s on %s (%.0f GB VRAM)", MODEL_ID, MODEL_DIR, props.name, vram_gb)

        pipe = FluxPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)

        if vram_gb < CPU_OFFLOAD_THRESHOLD_GB:
            # Model-level CPU offload: whole submodules move to the GPU as they are
            # needed and back afterwards. Slower per image, but the difference
            # between running and OOMing on a 24 GB card such as an A5000 or L4.
            # Untested: every worker so far has landed on a 48 GB or 80 GB card.
            pipe.enable_model_cpu_offload()
            self.offloaded = True
            log.warning("VRAM below %d GB - enabling model CPU offload", CPU_OFFLOAD_THRESHOLD_GB)
        else:
            pipe.to("cuda")

        pipe.set_progress_bar_config(disable=True)
        self.pipe = pipe
        self.load_seconds = time.perf_counter() - started
        log.info("Pipeline ready in %.1fs (offload=%s)", self.load_seconds, self.offloaded)

    def warmup(self) -> None:
        """One throwaway 512px image so the first *billed* request is not paying
        for CUDA kernel autotuning and lazy module init."""
        self.load()
        assert self.pipe is not None
        self.pipe(
            prompt="warmup",
            width=512,
            height=512,
            num_inference_steps=1,
            guidance_scale=DEFAULT_GUIDANCE,
            max_sequence_length=MAX_SEQUENCE_LENGTH,
            generator=torch.Generator(device="cpu").manual_seed(0),
        )
        log.info("Warmup pass complete")

    def generate(self, params: dict) -> GenerationResult:
        self.load()
        assert self.pipe is not None

        # Schema rejects negative seeds, so None is the only path to a random one.
        seed = params["seed"]
        if seed is None:
            seed = int(torch.randint(0, 2**31 - 1, (1,)).item())

        # The generator must live on CPU when modules are being offloaded, otherwise
        # diffusers and the offload hooks disagree about where the latents start.
        generator = torch.Generator(device="cpu").manual_seed(seed)

        started = time.perf_counter()
        output = self.pipe(
            prompt=params["prompt"],
            width=params["width"],
            height=params["height"],
            num_inference_steps=params["num_inference_steps"],
            guidance_scale=params["guidance_scale"],
            num_images_per_prompt=params["num_images"],
            max_sequence_length=MAX_SEQUENCE_LENGTH,
            generator=generator,
        )
        elapsed = time.perf_counter() - started

        return GenerationResult(
            images=output.images,
            seed=seed,
            timings={
                "inference_seconds": round(elapsed, 3),
                "seconds_per_image": round(elapsed / max(params["num_images"], 1), 3),
            },
        )

    def info(self) -> dict:
        return {
            "model_id": MODEL_ID,
            "model_dir": MODEL_DIR,
            "device": self.device,
            "gpu": self.gpu_name,
            "loaded": self.pipe is not None,
            "cpu_offload": self.offloaded,
            "load_seconds": round(self.load_seconds, 2),
            "defaults": {
                "num_inference_steps": DEFAULT_STEPS,
                "guidance_scale": DEFAULT_GUIDANCE,
                "max_sequence_length": MAX_SEQUENCE_LENGTH,
            },
        }


def encode_image(image: Image.Image, fmt: str, quality: int) -> bytes:
    buffer = io.BytesIO()
    fmt = fmt.upper()
    if fmt == "PNG":
        image.save(buffer, format="PNG", optimize=True)
    elif fmt == "JPEG":
        image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    elif fmt == "WEBP":
        image.save(buffer, format="WEBP", quality=quality, method=4)
    else:
        raise ValueError(f"Unsupported image format: {fmt}")
    return buffer.getvalue()
