"""Bake the diffusion weights into the Docker image at build time.

Running this as its own layer (before the source is copied) means editing the
handler rebuilds in seconds instead of re-pulling ~34 GB of weights.

The HF token is read from a BuildKit secret mount, never an ARG or ENV, so it
does not end up in the image history.
"""

import os
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

# The root-level single-file checkpoints (flux1-dev.safetensors, ae.safetensors)
# are byte-for-byte duplicates of the sharded diffusers folders that
# FluxPipeline.from_pretrained actually loads. Skipping them saves ~24 GB.
IGNORE_PATTERNS = [
    "flux1-dev.safetensors",
    "flux1-schnell.safetensors",
    "ae.safetensors",
    "*.bin",
    "*.pth",
    "*.onnx",
    "*.msgpack",
    "*.gguf",
    "dev_grid.jpg",
    "schnell_grid.jpeg",
]


def read_token() -> str | None:
    """Prefer the BuildKit secret mount, fall back to the environment."""
    secret = Path("/run/secrets/hf_token")
    if secret.is_file():
        token = secret.read_text().strip()
        if token:
            return token
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def main() -> int:
    model_id = os.environ.get("MODEL_ID", "black-forest-labs/FLUX.1-dev")
    target = os.environ.get("MODEL_DIR", "/models/flux")
    token = read_token()

    if token is None and "dev" in model_id:
        print(
            f"ERROR: {model_id} is a gated repository. Accept the licence at\n"
            f"       https://huggingface.co/{model_id}\n"
            "       and pass a token:  docker build --secret id=hf_token,env=HF_TOKEN ...",
            file=sys.stderr,
        )
        return 1

    print(f"Downloading {model_id} -> {target}", flush=True)
    snapshot_download(
        repo_id=model_id,
        local_dir=target,
        token=token,
        ignore_patterns=IGNORE_PATTERNS,
        max_workers=8,
    )

    total = sum(f.stat().st_size for f in Path(target).rglob("*") if f.is_file())
    print(f"Done. {total / 1e9:.1f} GB on disk at {target}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
