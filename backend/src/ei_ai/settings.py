"""Settings read from environment variables. Errors name the variable, never its value."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from ei_ai.auth.passwords import MAX_LENGTH as MAX_PASSWORD_LENGTH

ENVIRONMENTS = ("local", "test", "production")
DEFAULT_FILE_STORAGE_ROOT = "/var/lib/ei-ai/files"


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
    # Root of the encrypted originals (EA-20 `OrgFileStore`) of uploaded documents (EA-33);
    # one directory per Organization.
    file_storage_root: str = DEFAULT_FILE_STORAGE_ROOT

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
            file_storage_root=env.get("FILE_STORAGE_ROOT") or DEFAULT_FILE_STORAGE_ROOT,
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


@dataclass(frozen=True)
class ModelSettings:
    """Settings of the Model Gateway (EA-24). Every base URL is optional: an unset one means that
    provider is not configured, and a call to it fails without network access."""

    environment: str
    local_base_url: str | None = None
    embedding_base_url: str | None = None
    rerank_base_url: str | None = None
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 60.0
    retry_delay_seconds: float = 0.25
    max_tokens: int = 512
    # The explicit forward proxy of every cloud call (D33); unset means cloud calls are refused.
    egress_proxy_url: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ModelSettings":
        return cls(
            environment=_environment(env),
            local_base_url=_optional_url(env, "MODEL_LOCAL_BASE_URL"),
            embedding_base_url=_optional_url(env, "MODEL_EMBEDDING_BASE_URL"),
            rerank_base_url=_optional_url(env, "MODEL_RERANK_BASE_URL"),
            connect_timeout_seconds=_positive_float(env, "MODEL_CONNECT_TIMEOUT_SECONDS", 5.0),
            read_timeout_seconds=_positive_float(env, "MODEL_READ_TIMEOUT_SECONDS", 60.0),
            retry_delay_seconds=_positive_float(
                env, "MODEL_RETRY_DELAY_SECONDS", 0.25, allow_zero=True
            ),
            max_tokens=_positive_int(env, "MODEL_MAX_TOKENS", 512),
            egress_proxy_url=_optional_url(env, "EGRESS_PROXY_URL"),
        )

    def __repr__(self) -> str:
        urls = {
            "local_base_url": self.local_base_url,
            "embedding_base_url": self.embedding_base_url,
            "rerank_base_url": self.rerank_base_url,
            "egress_proxy_url": self.egress_proxy_url,
        }
        masked = ", ".join(
            f"{name}={None if url is None else mask_url(url)!r}" for name, url in urls.items()
        )
        return f"ModelSettings(environment={self.environment!r}, {masked})"


def require_https_in_production(environment: str, provider: str, url: str) -> str:
    """``url`` of a cloud provider; https in production (a test may use a loopback http URL)."""
    scheme = urlsplit(url).scheme
    allowed = ("https",) if environment == "production" else ("http", "https")
    if scheme not in allowed:
        raise SettingsError(f"cloud provider {provider} must use an https base URL in production")
    return url


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


def seed_password(env: Mapping[str, str]) -> str:
    """The shared test password of the demo seed (``EI_AI_SEED_PASSWORD``, local/test only).

    Required and at most ``passwords.MAX_LENGTH`` characters; errors name the variable, never the
    value. The password policy is not applied: the demo value is below it on purpose.
    """
    value = _required(env, "EI_AI_SEED_PASSWORD")
    if len(value) > MAX_PASSWORD_LENGTH:
        raise SettingsError(f"EI_AI_SEED_PASSWORD must be at most {MAX_PASSWORD_LENGTH} characters")
    return value


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


def _positive_float(
    env: Mapping[str, str], name: str, default: float, *, allow_zero: bool = False
) -> float:
    value = env.get(name, "")
    if not value:
        return default
    message = (
        f"{name} must be a number of seconds >= 0"
        if allow_zero
        else f"{name} must be a positive number of seconds"
    )
    try:
        number = float(value)
    except ValueError:
        raise SettingsError(message) from None
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise SettingsError(message)
    return number


def _optional_url(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "")
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SettingsError(f"{name} must be an http or https URL")
    return value
