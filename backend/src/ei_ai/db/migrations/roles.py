"""The database roles, and which of them may run migrations."""

APP_ROLE = "ei_ai_app"
OWNER_ROLE = "ei_ai_migrator"
# Sign-in lookup (EA-22, R42): reads only users(id, org_id, email); see migration 0004.
SIGNIN_ROLE = "ei_ai_signin"


class MigrationRoleError(RuntimeError):
    """Migrations were started with a role that must not run them. The message is safe to print."""


def check_migration_role(name: str, *, is_superuser: bool) -> None:
    """Migrations run only as the owner role, so every object ends up owned by it: never a
    superuser, never the application role (it must own nothing), never any other login."""
    if is_superuser:
        raise MigrationRoleError(
            "migrations must not run as a superuser; use MIGRATION_DATABASE_URL"
        )
    if name != OWNER_ROLE:
        raise MigrationRoleError(f"migrations must run as the owner role {OWNER_ROLE}")
