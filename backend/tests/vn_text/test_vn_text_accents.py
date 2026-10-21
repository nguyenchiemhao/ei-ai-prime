"""``strip_accents``: Latin diacritics off, other scripts untouched (AC3, R7, R16)."""

import random
import unicodedata

import pytest

from ei_ai.vn_text import normalize, strip_accents
from ei_ai.vn_text.letters import VOWEL_NUCLEI
from vn_text.cases import (
    CLEANUP_CASES,
    MIXED_CASES,
    NFC_NFD_SENTENCES,
    STRIP_CASES,
    TONE_CASES,
    UNCHANGED_CASES,
)

_TONES = ["", "\u0300", "\u0301", "\u0309", "\u0303", "\u0323"]
_CLUSTERS = sorted(VOWEL_NUCLEI)
_OTHERS = ["VPN", "café", "Ñandú", "report.pdf", "Q3", "đ", "Đ", "👍🏽", "Привет", "ภาษาไทย"]


def _generated(count: int) -> list[str]:
    rng = random.Random(2028)
    texts = []
    for _ in range(count):
        parts = []
        for _ in range(rng.randint(1, 8)):
            if rng.random() < 0.7:
                cluster = rng.choice(_CLUSTERS)
                spot = rng.randrange(len(cluster))
                toned = cluster[:spot] + cluster[spot] + rng.choice(_TONES) + cluster[spot + 1 :]
                word = rng.choice(["", "ng", "đ", "th", "qu"]) + toned + rng.choice(["", "n", "t"])
                parts.append(rng.choice([word, word.upper()]))
            else:
                parts.append(rng.choice(_OTHERS))
        texts.append(" ".join(parts))
    return texts


_ALL_INPUTS = (
    [src for src, _ in TONE_CASES + CLEANUP_CASES + MIXED_CASES + STRIP_CASES]
    + NFC_NFD_SENTENCES
    + UNCHANGED_CASES
    + _generated(300)
)


def test_don_xin_nghi_phep() -> None:
    assert strip_accents("Đơn xin nghỉ phép") == "Don xin nghi phep"
    nfd = unicodedata.normalize("NFD", "Đơn xin nghỉ phép")
    assert strip_accents(nfd) == "Don xin nghi phep"


@pytest.mark.parametrize(("src", "expected"), STRIP_CASES)
def test_strip_accents_table(src: str, expected: str) -> None:
    assert strip_accents(src) == expected
    assert strip_accents(unicodedata.normalize("NFD", src)) == expected


@pytest.mark.parametrize(
    "text",
    ["Привет", "Ελληνικά", "日本語", "ภาษาไทย", "العربية", "👨\u200d👩\u200d👧", "x = 1  # ok\n"],
)
def test_other_scripts_are_unchanged(text: str) -> None:
    assert strip_accents(text) == unicodedata.normalize("NFC", text)


def test_keyword_pipeline_matches_unaccented_typing() -> None:
    assert strip_accents(normalize("Huỷ đơn nghỉ phép thế nào")) == "Huy don nghi phep the nao"
    assert strip_accents(normalize("hoà")) == strip_accents(normalize("hòa")) == "hoa"


def test_strip_accents_property() -> None:
    for text in _ALL_INPUTS:
        result = strip_accents(text)
        decomposed = unicodedata.normalize("NFD", result)
        for i, ch in enumerate(decomposed):
            if "\u0300" <= ch <= "\u036f" and i:
                assert not decomposed[i - 1].isascii() or not decomposed[i - 1].isalpha(), text
        assert strip_accents(result) == result, text


def test_strip_accents_rejects_non_str() -> None:
    with pytest.raises(TypeError):
        strip_accents(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        strip_accents(b"x")  # type: ignore[arg-type]
    assert strip_accents("") == ""
