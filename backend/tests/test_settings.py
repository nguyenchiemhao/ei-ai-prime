import pytest

from ei_ai.settings import Settings, SettingsError

VALID = {
    "EI_AI_ENV": "local",
    "DATABASE_URL": "postgresql://ei_ai_app:s3cret-pw@db:5432/ei_ai",
    "VALKEY_URL": "redis://valkey:6379/0",
}


def test_reads_all_values_from_the_environment() -> None:
    settings = Settings.from_env(VALID)

    assert settings.environment == "local"
    assert settings.database_url == VALID["DATABASE_URL"]
    assert settings.valkey_url == VALID["VALKEY_URL"]


def test_missing_database_url_fails_with_variable_name_only() -> None:
    env = {k: v for k, v in VALID.items() if k != "DATABASE_URL"}

    with pytest.raises(SettingsError) as error:
        Settings.from_env(env)

    assert "DATABASE_URL" in str(error.value)
    assert "s3cret-pw" not in str(error.value)


def test_rejects_unknown_environment_without_echoing_secrets() -> None:
    with pytest.raises(SettingsError) as error:
        Settings.from_env({**VALID, "EI_AI_ENV": "staging"})

    assert "EI_AI_ENV" in str(error.value)
    assert "s3cret-pw" not in str(error.value)


def test_environment_defaults_to_production_when_unset() -> None:
    env = {k: v for k, v in VALID.items() if k != "EI_AI_ENV"}

    assert Settings.from_env(env).environment == "production"


def test_repr_masks_password() -> None:
    text = repr(Settings.from_env(VALID))

    assert "s3cret-pw" not in text
    assert "***" in text
    assert "db:5432/ei_ai" in text
