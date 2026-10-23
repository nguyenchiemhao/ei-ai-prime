"""EA-36: the access rule and the vector filter built from it. Fail closed: a principal never
gets the ``restricted`` level and never an unscoped (None) collection list."""

import uuid

import pytest

from ei_ai.knowledge.retrieval.access import can_read, permission_filter
from ei_ai.knowledge.retrieval.principal import (
    AnonymousPrincipal,
    AuthenticatedPrincipal,
    RetrievalPrincipal,
)
from ei_ai.vectors.search import VectorFilter

ANON = AnonymousPrincipal()
MEMBER = AuthenticatedPrincipal(user_id=uuid.uuid4())
MANAGER = AuthenticatedPrincipal(user_id=uuid.uuid4(), groups=("managers",), simulated=True)
COLLECTION = uuid.uuid4()
FOLDER = uuid.uuid4()


def test_access_table() -> None:
    assert permission_filter(ANON, (COLLECTION,), ()) == VectorFilter(
        (COLLECTION,), ("public",), (), ()
    )
    assert permission_filter(MEMBER, (COLLECTION,), (FOLDER,)) == VectorFilter(
        (COLLECTION,), ("public", "authenticated"), (), (FOLDER,)
    )
    assert permission_filter(MANAGER, (COLLECTION,), ()) == VectorFilter(
        (COLLECTION,), ("public", "authenticated"), ("managers",), ()
    )


@pytest.mark.parametrize("principal", [ANON, MEMBER, MANAGER])
def test_permission_filter_never_allows_restricted_level(principal: RetrievalPrincipal) -> None:
    assert "restricted" not in permission_filter(principal, (COLLECTION,), ()).access_levels


def test_permission_filter_never_returns_none_collections() -> None:
    for principal in (ANON, MEMBER, MANAGER):
        assert permission_filter(principal, (), ()).collection_ids == ()


@pytest.mark.parametrize("principal", [ANON, MEMBER, MANAGER])
@pytest.mark.parametrize(
    ("level", "groups"),
    [
        ("public", []),
        ("authenticated", []),
        ("restricted", ["managers"]),
        ("restricted", ["hr"]),
    ],
)
def test_can_read_matches_filter_rule(
    principal: RetrievalPrincipal, level: str, groups: list[str]
) -> None:
    rule = permission_filter(principal, (COLLECTION,), ())
    expected = level in rule.access_levels or bool(set(groups) & set(rule.groups))

    assert can_read(principal, level, groups) is expected


def test_can_read_concrete_cases() -> None:
    assert can_read(ANON, "public", []) is True
    assert can_read(ANON, "authenticated", []) is False
    assert can_read(MEMBER, "restricted", ["managers"]) is False
    assert can_read(MANAGER, "restricted", ["managers"]) is True
    assert can_read(MANAGER, "restricted", ["hr"]) is False
