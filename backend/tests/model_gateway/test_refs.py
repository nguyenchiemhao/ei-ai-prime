"""Model refs ``<model_id>@<version>`` (EA-24): the same patterns as the catalog CHECKs."""

import pytest

from ei_ai.model_gateway.refs import InvalidModelRef, ModelRef


def test_parses_model_id_and_version() -> None:
    ref = ModelRef.parse("qwen3-4b-instruct-2507@2026.10")

    assert ref == ModelRef("qwen3-4b-instruct-2507", "2026.10")
    assert str(ref) == "qwen3-4b-instruct-2507@2026.10"


def test_surrounding_whitespace_is_ignored() -> None:
    assert ModelRef.parse("  bge-m3@2026.10 ") == ModelRef("bge-m3", "2026.10")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "qwen3",
        "@2026.10",
        "qwen3@",
        "qwen3@2026@10",
        "Qwen3@2026.10",
        "qwen3@2026 10",
        "-qwen@1",
        "qwen3@.1",
        "a" * 101 + "@1",
        "a@" + "1" * 41,
        "http://evil/v1@1",
    ],
)
def test_rejects_anything_else(raw: str) -> None:
    with pytest.raises(InvalidModelRef):
        ModelRef.parse(raw)


def test_constructor_validates_too() -> None:
    with pytest.raises(InvalidModelRef):
        ModelRef("UPPER", "1")
