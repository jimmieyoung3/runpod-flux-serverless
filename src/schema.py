"""Request validation.

Deliberately dependency-free (no torch, no diffusers) so it can be unit-tested
on any machine, including CI runners without a GPU.
"""

from __future__ import annotations

# FLUX packs latents 2x2, on top of the VAE's 8x downscale, so every side must be
# a multiple of 16. Anything else silently produces a differently-sized image.
SIZE_MULTIPLE = 16
MIN_SIZE, MAX_SIZE = 256, 1536
MAX_STEPS = 50
MAX_IMAGES = 4
MAX_PROMPT_CHARS = 2000
VALID_FORMATS = {"PNG", "JPEG", "WEBP"}


class ValidationError(ValueError):
    """Raised for any client-supplied value the worker will not accept."""


def _as_int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"'{name}' must be a number, got {type(value).__name__}")
    if isinstance(value, float) and not value.is_integer():
        raise ValidationError(f"'{name}' must be a whole number, got {value}")
    return int(value)


def _snap(value: int) -> int:
    """Round to the nearest allowed dimension rather than rejecting the request.

    Integer half-up rather than round(), whose banker's rounding would send
    1000 down to 992 and 1016 up to 1024 - the same tie resolved two ways."""
    snapped = (value + SIZE_MULTIPLE // 2) // SIZE_MULTIPLE * SIZE_MULTIPLE
    return max(MIN_SIZE, min(MAX_SIZE, snapped))


def validate(job_input: dict | None, defaults: dict) -> dict:
    """Normalise a job payload into the exact kwargs FluxPredictor.generate wants.

    `defaults` carries the model-dependent step count and guidance scale so that
    the same handler serves FLUX.1-dev and FLUX.1-schnell without edits.
    """
    if not isinstance(job_input, dict):
        raise ValidationError("'input' must be a JSON object")

    unknown = set(job_input) - {
        "prompt", "width", "height", "num_inference_steps", "guidance_scale",
        "seed", "num_images", "output_format", "quality", "action",
    }
    if unknown:
        raise ValidationError(f"Unknown field(s): {', '.join(sorted(unknown))}")

    prompt = job_input.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValidationError("'prompt' is required and must be a non-empty string")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValidationError(f"'prompt' exceeds {MAX_PROMPT_CHARS} characters")

    width = _snap(_as_int(job_input.get("width", 1024), "width"))
    height = _snap(_as_int(job_input.get("height", 1024), "height"))

    steps = _as_int(job_input.get("num_inference_steps", defaults["num_inference_steps"]), "num_inference_steps")
    if not 1 <= steps <= MAX_STEPS:
        raise ValidationError(f"'num_inference_steps' must be between 1 and {MAX_STEPS}")

    guidance = job_input.get("guidance_scale", defaults["guidance_scale"])
    if isinstance(guidance, bool) or not isinstance(guidance, (int, float)):
        raise ValidationError("'guidance_scale' must be a number")
    if not 0.0 <= float(guidance) <= 20.0:
        raise ValidationError("'guidance_scale' must be between 0 and 20")

    num_images = _as_int(job_input.get("num_images", 1), "num_images")
    if not 1 <= num_images <= MAX_IMAGES:
        raise ValidationError(f"'num_images' must be between 1 and {MAX_IMAGES}")

    seed = job_input.get("seed")
    if seed is not None:
        seed = _as_int(seed, "seed")

    fmt = str(job_input.get("output_format", "PNG")).upper()
    if fmt == "JPG":
        fmt = "JPEG"
    if fmt not in VALID_FORMATS:
        raise ValidationError(f"'output_format' must be one of {sorted(VALID_FORMATS)}")

    quality = _as_int(job_input.get("quality", 92), "quality")
    if not 1 <= quality <= 100:
        raise ValidationError("'quality' must be between 1 and 100")

    return {
        "prompt": prompt.strip(),
        "width": width,
        "height": height,
        "num_inference_steps": steps,
        "guidance_scale": float(guidance),
        "num_images": num_images,
        "seed": seed,
        "output_format": fmt,
        "quality": quality,
    }
