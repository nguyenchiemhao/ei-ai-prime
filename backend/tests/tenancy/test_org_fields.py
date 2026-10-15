"""``is_org_field``: the one definition of "this request field names an Organization" (D32)."""

import pytest

from ei_ai.tenancy.context import ORG_HEADERS, ORG_QUERY_PARAMS, is_org_field


@pytest.mark.parametrize(
    "name",
    ["org_id", "orgId", "ORGANIZATION_ID", "X-Tenant-Id", "x_org_id", "OrgID", "tenant-id"],
)
def test_names_that_spell_an_organization_id_are_org_fields(name: str) -> None:
    assert is_org_field(name)


@pytest.mark.parametrize("name", ["workspace_id", "organ", "id", "origin", "user_id", "", "org"])
def test_other_names_are_not_org_fields(name: str) -> None:
    assert not is_org_field(name)


def test_every_configured_header_and_query_parameter_is_an_org_field() -> None:
    assert all(is_org_field(name) for name in (*ORG_HEADERS, *ORG_QUERY_PARAMS))
