"""Question language detection (EA-37, R7)."""

import pytest

from ei_ai.vn_text.language import detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Kết hôn được nghỉ mấy ngày?", "vi"),
        ("Đi", "vi"),
        ("How many days?", "en"),
        ("ket hon duoc nghi", "en"),
        ("", "en"),
    ],
)
def test_detect_language(text: str, expected: str) -> None:
    assert detect_language(text) == expected
