"""Every business cache key starts with ``org:<org_id>:`` and a part can never forge that prefix."""

import itertools
import uuid

import pytest

from ei_ai.cache.keys import TENANT_KEY_PATTERN, is_tenant_key, tenant_key

ORG = uuid.UUID("0190a000-0000-7000-8000-00000000000a")
OTHER = uuid.UUID("0190a000-0000-7000-8000-00000000000b")


def test_key_is_org_namespace_and_parts() -> None:
    assert tenant_key(ORG, "rate-limit", "widget", "42") == (
        "org:0190a000-0000-7000-8000-00000000000a:rate-limit:widget:42"
    )


def test_key_without_parts_is_org_and_namespace() -> None:
    assert tenant_key(ORG, "counter") == f"org:{ORG}:counter"


def test_every_key_matches_the_tenant_pattern() -> None:
    assert TENANT_KEY_PATTERN.match(tenant_key(ORG, "x", "a", "b"))
    assert is_tenant_key(tenant_key(OTHER, "x"))


@pytest.mark.parametrize(
    "key", ["probe:raw", "org:not-a-uuid:x", f"xorg:{ORG}:x", "", f"org:{ORG}"]
)
def test_other_keys_are_not_tenant_keys(key: str) -> None:
    assert not is_tenant_key(key)


@pytest.mark.parametrize("org_id", ["0190a000-0000-7000-8000-00000000000a", None, 7])
def test_organization_must_be_a_uuid_object(org_id: object) -> None:
    with pytest.raises(TypeError, match="org_id must be a uuid.UUID"):
        tenant_key(org_id, "x")  # type: ignore[arg-type]


@pytest.mark.parametrize("namespace", ["", "Upper", "1abc", "a:b", "a b", "a/b", "a%b", "abc\n"])
def test_malformed_namespace_is_refused(namespace: str) -> None:
    with pytest.raises(ValueError, match="namespace"):
        tenant_key(ORG, namespace)


def test_empty_part_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        tenant_key(ORG, "x", "a", "")


def test_an_ipv6_address_part_keeps_its_colons_out_of_the_key_structure() -> None:
    key = tenant_key(ORG, "rate-limit", "2001:db8::1")

    assert key == f"org:{ORG}:rate-limit:2001%3Adb8%3A%3A1"
    assert key.count(":") == 3  # org, uuid, namespace, one part: three separators


def test_a_part_cannot_forge_another_organizations_prefix() -> None:
    forged = tenant_key(ORG, "x", f"y:org:{OTHER}:z")

    assert forged.startswith(f"org:{ORG}:x:")
    assert f":org:{OTHER}:" not in forged
    assert is_tenant_key(forged)


def test_different_part_lists_never_give_the_same_key() -> None:
    candidates = [("a:b",), ("a", "b"), ("a%3Ab",), ("a%253Ab",), ("a:", "b"), ("a", ":b")]
    keys = [tenant_key(ORG, "x", *parts) for parts in candidates]

    assert len(set(keys)) == len(candidates)
    for first, second in itertools.combinations(keys, 2):
        assert first != second


def test_the_same_logical_key_differs_per_organization() -> None:
    assert tenant_key(ORG, "x", "1") != tenant_key(OTHER, "x", "1")
