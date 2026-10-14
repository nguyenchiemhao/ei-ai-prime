"""Settings read from environment variables. Errors name the variable, never its value."""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

ENVIRONMENTS = ("local", "test", "production")


class SettingsError(ValueError):
    """A required setting is missing or invalid."""


def mask_url(url: str) -> str:
    """The URL with the password replaced by ``***`` (safe to print)."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    user = f"{parts.username}:***@" if parts.username else ":***@"
    return urlunsplit(
        (parts.scheme, f"{user}{host}{port}", parts.path, parts.query, parts.fragment)
    )


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    valkey_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        return cls(
            environment=_environment(env),
            database_url=_required(env, "DATABASE_URL"),
            valkey_url=_required(env, "VALKEY_URL"),
        )

    def __repr__(self) -> str:
        return (
            f"Settings(environment={self.environment!r}, "
            f"database_url={mask_url(self.database_url)!r}, "
            f"valkey_url={mask_url(self.valkey_url)!r})"
        )


@dataclass(frozen=True)
class MigrationSettings:
    """Settings of the migration step, apart from Settings: the API never reads the owner URL."""

    environment: str
    migration_database_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "MigrationSettings":
        return cls(
            environment=_environment(env),
            migration_database_url=_required(env, "MIGRATION_DATABASE_URL"),
        )

    def __repr__(self) -> str:
        return (
            f"MigrationSettings(environment={self.environment!r}, "
            f"migration_database_url={mask_url(self.migration_database_url)!r})"
        )


def _environment(env: Mapping[str, str]) -> str:
    # Unset means production: the strictest environment is the safe default.
    environment = env.get("EI_AI_ENV", "production")
    if environment not in ENVIRONMENTS:
        raise SettingsError(f"EI_AI_ENV must be one of {', '.join(ENVIRONMENTS)}")
    return environment


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value:
        raise SettingsError(f"{name} is required")
    return value
