"""AC5 / R17: the case tables hold at least 100 cases, at least 10 of them mixed."""

from vn_text.cases import (
    CLEANUP_CASES,
    MIXED_CASES,
    NFC_NFD_SENTENCES,
    STRIP_CASES,
    TONE_CASES,
    UNCHANGED_CASES,
)


def test_case_tables_have_at_least_100_cases() -> None:
    total = sum(
        len(table)
        for table in (
            TONE_CASES,
            NFC_NFD_SENTENCES,
            UNCHANGED_CASES,
            CLEANUP_CASES,
            MIXED_CASES,
            STRIP_CASES,
        )
    )
    assert total >= 100
    assert len(MIXED_CASES) >= 10
    assert len(STRIP_CASES) >= 20
