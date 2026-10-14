import pytest

from ei_ai.db.migrations.roles import MigrationRoleError, check_migration_role


def test_accepts_the_owner_role() -> None:
    check_migration_role("ei_ai_migrator", is_superuser=False)


@pytest.mark.parametrize(
    ("role", "is_superuser"),
    [
        ("postgres", True),
        ("ei_ai_migrator", True),
        ("ei_ai_app", False),
        ("someone_else", False),
    ],
)
def test_refuses_to_migrate_as_superuser_app_role_or_anyone_but_the_owner_role(
    role: str, is_superuser: bool
) -> None:
    with pytest.raises(MigrationRoleError):
        check_migration_role(role, is_superuser=is_superuser)


def test_the_refusal_message_is_safe_to_print_and_names_the_expected_role() -> None:
    with pytest.raises(MigrationRoleError) as error:
        check_migration_role("someone_else", is_superuser=False)

    assert "ei_ai_migrator" in str(error.value)
    assert "someone_else" not in str(error.value)
