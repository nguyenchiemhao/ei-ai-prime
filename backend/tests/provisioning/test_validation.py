import uuid

import pytest

from ei_ai.provisioning.validation import (
    ORG_ROLES,
    WORKSPACE_ROLES,
    ProvisioningError,
    normalise_display_name,
    normalise_email,
    normalise_org_name,
    normalise_workspace_name,
    parse_uuid,
    split_roles,
)

E11_TAIL = (
    "valid roles: org_owner, org_admin, workspace_admin, developer, builder, knowledge_editor,"
    " reviewer, viewer, member"
)


def _message(error: pytest.ExceptionInfo[ProvisioningError]) -> str:
    return str(error.value)


def test_org_name_is_trimmed() -> None:
    assert normalise_org_name("  Mekong Devworks  ") == "Mekong Devworks"


@pytest.mark.parametrize("raw", ["", "   ", "x" * 201])
def test_org_name_out_of_range_is_e1(raw: str) -> None:
    with pytest.raises(ProvisioningError) as error:
        normalise_org_name(raw)

    assert _message(error) == "Organization name must be 1-200 characters"


def test_org_name_of_200_characters_is_accepted() -> None:
    assert normalise_org_name("x" * 200) == "x" * 200


def test_workspace_name_is_trimmed() -> None:
    assert normalise_workspace_name(" People Ops ") == "People Ops"


@pytest.mark.parametrize("raw", ["", " ", "w" * 201])
def test_workspace_name_out_of_range_is_e5(raw: str) -> None:
    with pytest.raises(ProvisioningError) as error:
        normalise_workspace_name(raw)

    assert _message(error) == "Workspace name must be 1-200 characters"


def test_display_name_is_trimmed() -> None:
    assert normalise_display_name("  Hà Vũ ") == "Hà Vũ"


@pytest.mark.parametrize("raw", ["", "  ", "d" * 201])
def test_display_name_out_of_range_is_e4(raw: str) -> None:
    with pytest.raises(ProvisioningError) as error:
        normalise_display_name(raw)

    assert _message(error) == "display name must be 1-200 characters"


def test_email_is_trimmed_and_lowercased() -> None:
    assert normalise_email("  Owner+QA@Example.com ") == "owner+qa@example.com"


@pytest.mark.parametrize(
    "raw",
    [
        "not-an-email",
        "a@b",
        "a@@b.example",
        "a b@c.example",
        "linh@",
        "@example.com",
        "",
        "linh@example..com",
        "x" * 65 + "@example.com",
        "a@" + "b" * 320 + ".example",
    ],
)
def test_malformed_email_is_e3(raw: str) -> None:
    with pytest.raises(ProvisioningError) as error:
        normalise_email(raw)

    assert _message(error) == "invalid email address"


def test_email_with_64_character_local_part_is_accepted() -> None:
    assert normalise_email("x" * 64 + "@example.com") == "x" * 64 + "@example.com"


def test_parse_uuid_returns_the_uuid() -> None:
    value = uuid.uuid4()

    assert parse_uuid(f" {value} ", "bad id") == value


@pytest.mark.parametrize("raw", ["", "nope", "1234", "0192a000-0000-7000-8000-00000000ea2"])
def test_parse_uuid_rejects_with_the_given_message(raw: str) -> None:
    with pytest.raises(ProvisioningError) as error:
        parse_uuid(raw, "--org must be an Organization id (UUID)")

    assert _message(error) == "--org must be an Organization id (UUID)"


def test_role_tuples_match_the_migration_check_constraints() -> None:
    assert ORG_ROLES == ("org_owner", "org_admin")
    assert WORKSPACE_ROLES == (
        "workspace_admin",
        "developer",
        "builder",
        "knowledge_editor",
        "reviewer",
        "viewer",
        "member",
    )


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["builder"], (None, "builder")),
        (["org_admin"], ("org_admin", None)),
        (["workspace_admin", "org_admin"], ("org_admin", "workspace_admin")),
        ([], (None, None)),
    ],
)
def test_split_roles(roles: list[str], expected: tuple[str | None, str | None]) -> None:
    assert split_roles(roles) == expected


def test_unknown_role_is_e11_naming_the_first_unknown_code() -> None:
    with pytest.raises(ProvisioningError) as error:
        split_roles(["builder", "Builder", "boss"])

    assert _message(error) == f'unknown role "Builder"; {E11_TAIL}'


@pytest.mark.parametrize("roles", [["org_owner", "org_admin"], ["builder", "viewer"]])
def test_two_roles_of_one_kind_are_e12(roles: list[str]) -> None:
    with pytest.raises(ProvisioningError) as error:
        split_roles(roles)

    assert _message(error) == "give at most one Organization role and one Workspace role"
