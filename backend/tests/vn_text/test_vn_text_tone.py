"""Canonical tone placement: one rule, case kept by position, foreign words untouched (R1, R9)."""

import unicodedata

import pytest

from ei_ai.vn_text import normalize
from ei_ai.vn_text.letters import BASE_VOWELS, TONED_CHARS, VOWEL_NUCLEI, join_char, split_char
from ei_ai.vn_text.tone import place_tones
from vn_text.cases import TONE_CASES


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


@pytest.mark.parametrize(("src", "expected"), TONE_CASES)
def test_tone_rule_table(src: str, expected: str) -> None:
    assert normalize(src) == expected
    assert normalize(_nfd(src)) == expected


def test_ticket_pairs_normalise_to_one_form() -> None:
    assert normalize("hoà") == normalize("hòa") == "hòa"
    assert normalize("thuỷ") == normalize("thủy") == "thủy"
    assert normalize("quả") == normalize("qủa") == "quả"


def test_tone_move_keeps_case_by_position() -> None:
    assert normalize("HOÀ") == "HÒA"
    assert normalize("Thuỷ") == "Thủy"
    assert normalize("Qủa") == "Quả"
    assert normalize("HoÀ") == "HòA"


@pytest.mark.parametrize(
    "word",
    ["café", "résumé", "José", "Pokémon", "naïve", "né", "où", "leí", "ciò", "può", "tío", "dúo"],
)
def test_foreign_words_are_left_unchanged(word: str) -> None:
    assert normalize(word) == word
    assert normalize(_nfd(word)) == word


def test_place_tones_rewrites_only_vietnamese_syllables() -> None:
    assert place_tones("hoà café thuỷ") == "hòa café thủy"


def test_letter_run_touching_a_leftover_combining_mark_is_left_unchanged() -> None:
    assert place_tones("hoà\u0308") == "hoà\u0308"
    assert place_tones("x\u0308hoà") == "x\u0308hoà"


def test_words_in_other_scripts_are_left_unchanged() -> None:
    assert place_tones("Приветà 東京hoà") == "Приветà 東京hoà"


def test_letter_tables_cover_every_vowel_tone_and_case() -> None:
    assert len(BASE_VOWELS) == 12
    assert len(TONED_CHARS) == 12 * 5 * 2
    assert split_char("Ỡ") == ("ơ", 4, True)
    assert split_char("b") is None
    for base in BASE_VOWELS:
        for tone in range(6):
            for upper in (False, True):
                char = join_char(base, tone, upper)
                assert len(char) == 1
                assert split_char(char) == (base, tone, upper)


@pytest.mark.parametrize("nucleus", sorted(VOWEL_NUCLEI))
def test_every_vietnamese_vowel_nucleus_is_accepted(nucleus: str) -> None:
    variants = {
        normalize("h" + nucleus[:i] + join_char(nucleus[i], 2, False) + nucleus[i + 1 :])
        for i in range(len(nucleus))
    }
    assert len(variants) == 1, variants
