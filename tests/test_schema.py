"""Unit tests for request validation. No GPU, no model, no network.

    python -m pytest tests/ -q      (or: python tests/test_schema.py)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from schema import ValidationError, validate  # noqa: E402

DEFAULTS = {"num_inference_steps": 28, "guidance_scale": 3.5}


def test_minimal_request_gets_defaults():
    out = validate({"prompt": "a cat"}, DEFAULTS)
    assert out["prompt"] == "a cat"
    assert out["width"] == out["height"] == 1024
    assert out["num_inference_steps"] == 28
    assert out["guidance_scale"] == 3.5
    assert out["num_images"] == 1
    assert out["seed"] is None
    assert out["output_format"] == "PNG"


@pytest.mark.parametrize("bad", [None, {}, {"prompt": ""}, {"prompt": "   "}, {"prompt": 5}])
def test_prompt_is_required(bad):
    with pytest.raises(ValidationError):
        validate(bad, DEFAULTS)


def test_prompt_length_capped():
    with pytest.raises(ValidationError, match="exceeds"):
        validate({"prompt": "x" * 2001}, DEFAULTS)


@pytest.mark.parametrize("given,expected", [
    (1000, 1008),   # snapped up to the nearest multiple of 16
    (1023, 1024),
    (100, 256),     # clamped to the floor
    (4096, 1536),   # clamped to the ceiling
    (768, 768),     # already valid, untouched
])
def test_dimensions_snap_to_multiple_of_16(given, expected):
    out = validate({"prompt": "p", "width": given, "height": given}, DEFAULTS)
    assert out["width"] == expected and out["height"] == expected
    assert out["width"] % 16 == 0


@pytest.mark.parametrize("field,value", [
    ("num_inference_steps", 0),
    ("num_inference_steps", 51),
    ("guidance_scale", -1),
    ("guidance_scale", 21),
    ("num_images", 0),
    ("num_images", 5),
    ("quality", 0),
    ("quality", 101),
])
def test_out_of_range_values_rejected(field, value):
    with pytest.raises(ValidationError):
        validate({"prompt": "p", field: value}, DEFAULTS)


def test_booleans_are_not_numbers():
    # bool is a subclass of int in Python; steps=True must not silently mean 1.
    with pytest.raises(ValidationError):
        validate({"prompt": "p", "num_inference_steps": True}, DEFAULTS)


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError, match="negative_prompt"):
        validate({"prompt": "p", "negative_prompt": "blurry"}, DEFAULTS)


def test_jpg_alias_and_case_insensitivity():
    assert validate({"prompt": "p", "output_format": "jpg"}, DEFAULTS)["output_format"] == "JPEG"
    assert validate({"prompt": "p", "output_format": "webp"}, DEFAULTS)["output_format"] == "WEBP"


def test_unsupported_format_rejected():
    with pytest.raises(ValidationError):
        validate({"prompt": "p", "output_format": "gif"}, DEFAULTS)


def test_schnell_defaults_flow_through():
    out = validate({"prompt": "p"}, {"num_inference_steps": 4, "guidance_scale": 0.0})
    assert out["num_inference_steps"] == 4 and out["guidance_scale"] == 0.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
