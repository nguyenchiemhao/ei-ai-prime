import pytest

from ei_ai.knowledge.errors import InvalidGroup
from ei_ai.knowledge.groups import normalise_groups


def test_trims_and_lower_cases() -> None:
    assert normalise_groups([" Managers "]) == ["managers"]


def test_removes_duplicates_in_first_seen_order() -> None:
    assert normalise_groups(["b", "a", "B", "A"]) == ["b", "a"]
    assert normalise_groups(["a", "A"]) == ["a"]


def test_keeps_diacritics_in_nfc() -> None:
    decomposed = "Ké toán"

    assert normalise_groups(["Kế toán"]) == ["kế toán"]
    assert normalise_groups([decomposed]) == ["ké toán"]
    assert normalise_groups(["Kế toán", "KẾ TOÁN"]) == ["kế toán"]


def test_empty_list_is_allowed() -> None:
    assert normalise_groups([]) == []


@pytest.mark.parametrize("bad", ["x,y", "", "   ", "a" * 65, "\x07", "a\tb"])
def test_rejects_an_unacceptable_group(bad: str) -> None:
    with pytest.raises(InvalidGroup):
        normalise_groups([bad])


def test_accepts_the_length_limits() -> None:
    assert normalise_groups(["a", "b" * 64]) == ["a", "b" * 64]


def test_rejects_more_than_twenty_groups() -> None:
    assert len(normalise_groups([f"g{i}" for i in range(20)])) == 20
    with pytest.raises(InvalidGroup):
        normalise_groups([f"g{i}" for i in range(21)])


def test_duplicates_do_not_count_towards_the_limit() -> None:
    assert len(normalise_groups([f"g{i % 20}" for i in range(40)])) == 20
