"""``normalize``: one stable NFC form for every encoding of the same text (AC1, AC4, R10, R16)."""

import ast
import random
import unicodedata
from pathlib import Path

import pytest

import ei_ai.vn_text
from ei_ai.vn_text import normalize
from ei_ai.vn_text.letters import VOWEL_NUCLEI
from vn_text.cases import (
    CLEANUP_CASES,
    MIXED_CASES,
    NFC_NFD_SENTENCES,
    TONE_CASES,
    UNCHANGED_CASES,
)

_INITIALS = "ngh ng gh gi qu ch kh nh ph th tr b c d đ g h k l m n p q r s t v x".split() + [""]
_CLUSTERS = sorted(VOWEL_NUCLEI)
_FINALS = ["", "", "c", "ch", "m", "n", "ng", "nh", "p", "t"]
_TONES = ["", "\u0300", "\u0301", "\u0309", "\u0303", "\u0323"]
_OTHERS = ["VPN", "report.pdf", "Q3", "2026", "email", "OK!", "?", ",", "(x)", "👍🏽", "🇻🇳"]


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


def _syllable(rng: random.Random) -> str:
    cluster = rng.choice(_CLUSTERS)
    spot = rng.randrange(len(cluster))
    toned = cluster[:spot] + cluster[spot] + rng.choice(_TONES) + cluster[spot + 1 :]
    word = rng.choice(_INITIALS) + toned + rng.choice(_FINALS)
    word = unicodedata.normalize("NFC", word)
    return rng.choice([word, word.upper(), word.capitalize()])


def _generated(count: int) -> list[str]:
    rng = random.Random(2028)
    texts = []
    for _ in range(count):
        parts = [
            _syllable(rng) if rng.random() < 0.7 else rng.choice(_OTHERS)
            for _ in range(rng.randint(1, 8))
        ]
        texts.append(rng.choice([" ", "  ", "\t", "-"]).join(parts))
    return texts


_ALL_INPUTS = (
    [src for src, _ in TONE_CASES + CLEANUP_CASES + MIXED_CASES]
    + NFC_NFD_SENTENCES
    + UNCHANGED_CASES
    + _generated(300)
)


def test_nghi_phep_nfc_and_nfd_are_byte_identical() -> None:
    nfc = unicodedata.normalize("NFC", "Nghỉ phép")
    nfd = unicodedata.normalize("NFD", "Nghỉ phép")
    assert nfc != nfd
    assert normalize(nfc).encode("utf-8") == normalize(nfd).encode("utf-8")


@pytest.mark.parametrize("sentence", NFC_NFD_SENTENCES)
def test_nfc_and_nfd_sentences_are_byte_identical(sentence: str) -> None:
    nfc = unicodedata.normalize("NFC", sentence)
    expected = normalize(sentence).encode("utf-8")
    assert normalize(nfc).encode("utf-8") == expected
    assert normalize(_nfd(sentence)).encode("utf-8") == expected


@pytest.mark.parametrize("text", UNCHANGED_CASES)
def test_english_emoji_and_code_change_only_by_nfc(text: str) -> None:
    assert normalize(text) == unicodedata.normalize("NFC", text)


@pytest.mark.parametrize(("src", "expected"), MIXED_CASES)
def test_mixed_sentences(src: str, expected: str) -> None:
    assert normalize(src) == expected
    assert normalize(_nfd(src)) == expected


def test_nfd_input_gives_the_same_result() -> None:
    for text in _ALL_INPUTS:
        assert normalize(_nfd(text)) == normalize(text), text


def test_normalize_is_idempotent() -> None:
    for text in _ALL_INPUTS:
        once = normalize(text)
        assert normalize(once) == once, text
        assert once == unicodedata.normalize("NFC", once), text


def test_rejects_non_str() -> None:
    with pytest.raises(TypeError):
        normalize(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        normalize(b"x")  # type: ignore[arg-type]
    assert normalize("") == ""


def test_case_tables_keep_their_minimum_sizes() -> None:
    assert len(TONE_CASES) >= 45
    assert len(NFC_NFD_SENTENCES) >= 10
    assert len(UNCHANGED_CASES) >= 15
    assert len(CLEANUP_CASES) >= 14
    assert len(MIXED_CASES) >= 12


def test_package_keeps_no_cache_and_no_logging() -> None:
    package = Path(ei_ai.vn_text.__file__).parent
    sources = sorted(package.glob("*.py"))
    assert sources
    for source in sources:
        problems = _forbidden_uses(source.read_text(encoding="utf-8"))
        assert not problems, f"{source.name} uses {problems}"


_CACHE_NAMES = frozenset({"cache", "lru_cache", "cached_property"})


def _forbidden_uses(code: str) -> list[str]:
    """Imports of ``logging`` or a ``functools`` cache, ``functools.*cache`` use, and ``print``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "logging"]
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module == "logging":
                found.append("logging")
            elif module == "functools":
                found += [f"functools.{a.name}" for a in node.names if a.name in _CACHE_NAMES]
        elif isinstance(node, ast.Attribute):
            if node.attr in _CACHE_NAMES and getattr(node.value, "id", "") == "functools":
                found.append(f"functools.{node.attr}")
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print":
            found.append("print")
    return found


@pytest.mark.parametrize(
    "planted",
    [
        "from functools import cache\n",
        "from functools import lru_cache as c\n",
        "import functools\n@functools.cache\ndef f(): ...\n",
        "from logging import getLogger\n",
        "import logging\n",
        "print(1)\n",
    ],
)
def test_no_cache_guard_detects_planted_uses(planted: str) -> None:
    assert _forbidden_uses(planted)


def test_no_cache_guard_accepts_clean_code() -> None:
    assert not _forbidden_uses("import re\nfrom functools import reduce\nx = re\n")
