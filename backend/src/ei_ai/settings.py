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
    # The sign-in lookup role (EA-22, R42): only ei_ai.auth.directory connects with it.
    signin_database_url: str
    # Base URL of the admin app; its origin is the only Origin the CSRF check accepts (EA-22).
    admin_base_url: str
    # Read the client address from X-Forwarded-For (only behind the admin nginx proxy).
    trust_proxy_headers: bool = False
    auth_rate_limit_per_minute: int = 30
    session_idle_timeout_seconds: int = 43200

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        environment = _environment(env)
        return cls(
            environment=environment,
            database_url=_required(env, "DATABASE_URL"),
            valkey_url=_required(env, "VALKEY_URL"),
            signin_database_url=_required(env, "SIGNIN_DATABASE_URL"),
            admin_base_url=admin_base_url(env, environment),
            trust_proxy_headers=_boolean(env, "TRUST_PROXY_HEADERS", default=False),
            auth_rate_limit_per_minute=_positive_int(env, "AUTH_RATE_LIMIT_PER_MINUTE", 30),
            session_idle_timeout_seconds=_positive_int(env, "SESSION_IDLE_TIMEOUT_SECONDS", 43200),
        )

    def __repr__(self) -> str:
        return (
            f"Settings(environment={self.environment!r}, "
            f"database_url={mask_url(self.database_url)!r}, "
            f"valkey_url={mask_url(self.valkey_url)!r}, "
            f"signin_database_url={mask_url(self.signin_database_url)!r})"
        )


@dataclass(frozen=True)
class CliSettings:
    """Settings of the Platform Operator commands: they talk to the database only (no Valkey)."""

    environment: str
    database_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "CliSettings":
        """Read EI_AI_ENV and DATABASE_URL; raises SettingsError naming a missing variable."""
        return cls(environment=_environment(env), database_url=_required(env, "DATABASE_URL"))

    def __repr__(self) -> str:
        return (
            f"CliSettings(environment={self.environment!r}, "
            f"database_url={mask_url(self.database_url)!r})"
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


LOCAL_ADMIN_BASE_URL = "http://localhost:3000"


def admin_base_url(env: Mapping[str, str], environment: str) -> str:
    """Base URL of the admin app for set-password links, without a trailing slash.

    ``ADMIN_BASE_URL`` when set; unset or empty means the local admin in local/test and an error in
    production (a link must never point at a developer machine).
    """
    value = env.get("ADMIN_BASE_URL", "")
    if not value:
        if environment == "production":
            raise SettingsError("ADMIN_BASE_URL is required")
        return LOCAL_ADMIN_BASE_URL
    if not value.startswith(("http://", "https://")):
        raise SettingsError("ADMIN_BASE_URL must be an http or https URL")
    return value.rstrip("/")


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


def _boolean(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name, "")
    if not value:
        return default
    if value.lower() in ("true", "1"):
        return True
    if value.lower() in ("false", "0"):
        return False
    raise SettingsError(f"{name} must be true or false")


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name, "")
    if not value:
        return default
    try:
        number = int(value)
    except ValueError:
        raise SettingsError(f"{name} must be a positive integer") from None
    if number < 1:
        raise SettingsError(f"{name} must be a positive integer")
    return number
