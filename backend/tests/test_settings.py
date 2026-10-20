import pytest

from ei_ai.settings import (
    CliSettings,
    MigrationSettings,
    Settings,
    SettingsError,
    admin_base_url,
)

VALID = {
    "EI_AI_ENV": "local",
    "DATABASE_URL": "postgresql://ei_ai_app:s3cret-pw@db:5432/ei_ai",
    "VALKEY_URL": "redis://valkey:6379/0",
    "SIGNIN_DATABASE_URL": "postgresql://ei_ai_signin:s1gnin-pw@db:5432/ei_ai",
}


def test_reads_all_values_from_the_environment() -> None:
    settings = Settings.from_env(VALID)

    assert settings.environment == "local"
    assert settings.database_url == VALID["DATABASE_URL"]
    assert settings.valkey_url == VALID["VALKEY_URL"]
    assert settings.signin_database_url == VALID["SIGNIN_DATABASE_URL"]


def test_missing_database_url_fails_with_variable_name_only() -> None:
    env = {k: v for k, v in VALID.items() if k != "DATABASE_URL"}

    with pytest.raises(SettingsError) as error:
        Settings.from_env(env)

    assert "DATABASE_URL" in str(error.value)
    assert "s3cret-pw" not in str(error.value)


@pytest.mark.parametrize("value", [None, ""])
def test_signin_database_url_is_required(value: str | None) -> None:
    env = {k: v for k, v in VALID.items() if k != "SIGNIN_DATABASE_URL"}
    if value is not None:
        env["SIGNIN_DATABASE_URL"] = value

    with pytest.raises(SettingsError) as error:
        Settings.from_env(env)

    assert str(error.value) == "SIGNIN_DATABASE_URL is required"


def test_rejects_unknown_environment_without_echoing_secrets() -> None:
    with pytest.raises(SettingsError) as error:
        Settings.from_env({**VALID, "EI_AI_ENV": "staging"})

    assert "EI_AI_ENV" in str(error.value)
    assert "s3cret-pw" not in str(error.value)


def test_environment_defaults_to_production_when_unset() -> None:
    env = {k: v for k, v in VALID.items() if k != "EI_AI_ENV"}
    env["ADMIN_BASE_URL"] = "https://admin.example"

    assert Settings.from_env(env).environment == "production"


def test_repr_masks_password() -> None:
    text = repr(Settings.from_env(VALID))

    assert "s3cret-pw" not in text
    assert "s1gnin-pw" not in text
    assert "ei_ai_signin:***@db:5432/ei_ai" in text
    assert "db:5432/ei_ai" in text


def test_migration_settings_read_the_owner_url_and_mask_it_in_repr() -> None:
    env = {
        "EI_AI_ENV": "local",
        "MIGRATION_DATABASE_URL": "postgresql://ei_ai_migrator:s3cret-pw@db:5432/ei_ai",
    }

    settings = MigrationSettings.from_env(env)

    assert settings.environment == "local"
    assert settings.migration_database_url == env["MIGRATION_DATABASE_URL"]
    assert "s3cret-pw" not in repr(settings)
    assert "***" in repr(settings)


def test_migration_settings_need_only_the_migration_url() -> None:
    with pytest.raises(SettingsError) as error:
        MigrationSettings.from_env({"EI_AI_ENV": "local", "DATABASE_URL": "postgresql://x"})

    assert "MIGRATION_DATABASE_URL" in str(error.value)


def test_migration_settings_reject_unknown_environment() -> None:
    env = {"EI_AI_ENV": "staging", "MIGRATION_DATABASE_URL": "postgresql://x"}

    with pytest.raises(SettingsError) as error:
        MigrationSettings.from_env(env)

    assert "EI_AI_ENV" in str(error.value)


@pytest.mark.parametrize("environment", ["local", "test"])
def test_admin_base_url_defaults_to_localhost_in_local_and_test(environment: str) -> None:
    assert admin_base_url({}, environment) == "http://localhost:3000"
    assert admin_base_url({"ADMIN_BASE_URL": ""}, environment) == "http://localhost:3000"


@pytest.mark.parametrize("value", [None, ""])
def test_admin_base_url_is_required_in_production(value: str | None) -> None:
    env = {} if value is None else {"ADMIN_BASE_URL": value}

    with pytest.raises(SettingsError) as error:
        admin_base_url(env, "production")

    assert str(error.value) == "ADMIN_BASE_URL is required"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://admin.example.com/", "https://admin.example.com"),
        ("http://localhost:3000", "http://localhost:3000"),
        ("https://admin.example.com/ei//", "https://admin.example.com/ei"),
    ],
)
def test_admin_base_url_strips_the_trailing_slash(value: str, expected: str) -> None:
    assert admin_base_url({"ADMIN_BASE_URL": value}, "production") == expected


@pytest.mark.parametrize("value", ["ftp://admin.example.com", "admin.example.com", "javascript:x"])
def test_admin_base_url_must_be_http_or_https(value: str) -> None:
    with pytest.raises(SettingsError) as error:
        admin_base_url({"ADMIN_BASE_URL": value}, "local")

    assert str(error.value) == "ADMIN_BASE_URL must be an http or https URL"


def test_cli_settings_need_only_the_environment_and_the_database_url() -> None:
    env = {"EI_AI_ENV": "local", "DATABASE_URL": VALID["DATABASE_URL"]}

    settings = CliSettings.from_env(env)

    assert (settings.environment, settings.database_url) == ("local", VALID["DATABASE_URL"])
    assert "s3cret-pw" not in repr(settings)


def test_cli_settings_require_the_database_url() -> None:
    with pytest.raises(SettingsError) as error:
        CliSettings.from_env({"EI_AI_ENV": "local", "VALKEY_URL": "redis://valkey:6379/0"})

    assert str(error.value) == "DATABASE_URL is required"


def test_new_api_settings_defaults() -> None:
    settings = Settings.from_env(VALID)

    assert settings.admin_base_url == "http://localhost:3000"
    assert settings.trust_proxy_headers is False
    assert settings.auth_rate_limit_per_minute == 30
    assert settings.session_idle_timeout_seconds == 43200


def test_new_api_settings_overrides() -> None:
    settings = Settings.from_env(
        {
            **VALID,
            "ADMIN_BASE_URL": "https://admin.example.com/",
            "TRUST_PROXY_HEADERS": "true",
            "AUTH_RATE_LIMIT_PER_MINUTE": "5",
            "SESSION_IDLE_TIMEOUT_SECONDS": "600",
        }
    )

    assert settings.admin_base_url == "https://admin.example.com"
    assert settings.trust_proxy_headers is True
    assert settings.auth_rate_limit_per_minute == 5
    assert settings.session_idle_timeout_seconds == 600


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TRUST_PROXY_HEADERS", "maybe"),
        ("AUTH_RATE_LIMIT_PER_MINUTE", "x"),
        ("SESSION_IDLE_TIMEOUT_SECONDS", "0"),
    ],
)
def test_invalid_new_api_settings_name_the_variable(name: str, value: str) -> None:
    with pytest.raises(SettingsError) as error:
        Settings.from_env({**VALID, name: value})

    assert name in str(error.value)


def test_production_requires_admin_base_url() -> None:
    with pytest.raises(SettingsError) as error:
        Settings.from_env({**VALID, "EI_AI_ENV": "production"})

    assert str(error.value) == "ADMIN_BASE_URL is required"
