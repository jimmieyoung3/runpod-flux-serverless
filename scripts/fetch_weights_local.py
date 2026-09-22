#!/usr/bin/env python3
"""Download the model weights into the build context, outside the image build.

Kaniko cannot consume BuildKit secrets, so authenticating inside the Dockerfile
would mean passing the HF token as a build arg and persisting it in the image
history. Fetching here instead keeps the token on the build host.

    HF_TOKEN=hf_... python scripts/fetch_weights_local.py ./weights
"""

import os
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

# Root-level single-file checkpoints duplicate the sharded diffusers folders
# that FluxPipeline actually loads; skipping them saves ~24 GB.
IGNORE_PATTERNS = [
    "flux1-dev.safetensors", "flux1-schnell.safetensors", "ae.safetensors",
    "*.bin", "*.pth", "*.onnx", "*.msgpack", "*.gguf", "*_grid.jpg", "*_grid.jpeg",
]


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "weights")
    model_id = os.environ.get("MODEL_ID", "black-forest-labs/FLUX.1-dev")
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("error: set HF_TOKEN (FLUX.1 is a gated repository)", file=sys.stderr)
        return 1

    print(f"Downloading {model_id} -> {target}", flush=True)
    snapshot_download(
        repo_id=model_id,
        local_dir=str(target),
        token=token,
        ignore_patterns=IGNORE_PATTERNS,
        max_workers=8,
    )

    files = [f for f in target.rglob("*") if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    print(f"Done. {len(files)} files, {total / 1e9:.1f} GB", flush=True)

    if not (target / "model_index.json").exists():
        print("error: model_index.json missing - the download is incomplete", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
