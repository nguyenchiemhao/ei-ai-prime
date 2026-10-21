"""Settings of the Model Gateway (EA-24): base URLs, timeouts, retry delay, egress proxy."""

import pytest

from ei_ai.model_gateway.providers import ProviderRegistry
from ei_ai.settings import ModelSettings, SettingsError, require_https_in_production


def test_defaults_when_nothing_is_set() -> None:
    settings = ModelSettings.from_env({"EI_AI_ENV": "test"})

    assert settings.environment == "test"
    assert settings.local_base_url is None
    assert settings.embedding_base_url is None
    assert settings.rerank_base_url is None
    assert settings.connect_timeout_seconds == 5.0
    assert settings.read_timeout_seconds == 60.0
    assert settings.retry_delay_seconds == 0.25
    assert settings.max_tokens == 512
    assert settings.egress_proxy_url is None


def test_reads_every_variable() -> None:
    settings = ModelSettings.from_env(
        {
            "EI_AI_ENV": "local",
            "MODEL_LOCAL_BASE_URL": "http://model:8080/v1",
            "MODEL_EMBEDDING_BASE_URL": "http://embed:8080/v1",
            "MODEL_RERANK_BASE_URL": "https://rerank.internal/v1",
            "MODEL_CONNECT_TIMEOUT_SECONDS": "2.5",
            "MODEL_READ_TIMEOUT_SECONDS": "0.2",
            "MODEL_RETRY_DELAY_SECONDS": "0",
            "MODEL_MAX_TOKENS": "64",
            "EGRESS_PROXY_URL": "http://proxy:3128",
        }
    )

    assert settings.local_base_url == "http://model:8080/v1"
    assert settings.embedding_base_url == "http://embed:8080/v1"
    assert settings.rerank_base_url == "https://rerank.internal/v1"
    assert settings.connect_timeout_seconds == 2.5
    assert settings.read_timeout_seconds == 0.2
    assert settings.retry_delay_seconds == 0.0
    assert settings.max_tokens == 64
    assert settings.egress_proxy_url == "http://proxy:3128"


@pytest.mark.parametrize(
    "name",
    [
        "MODEL_LOCAL_BASE_URL",
        "MODEL_EMBEDDING_BASE_URL",
        "MODEL_RERANK_BASE_URL",
        "EGRESS_PROXY_URL",
    ],
)
@pytest.mark.parametrize("value", ["ftp://secret-host/x", "model:8080", "http://"])
def test_urls_must_be_http_or_https_and_errors_name_only_the_variable(
    name: str, value: str
) -> None:
    with pytest.raises(SettingsError) as error:
        ModelSettings.from_env({"EI_AI_ENV": "test", name: value})

    assert str(error.value) == f"{name} must be an http or https URL"
    assert "secret-host" not in str(error.value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MODEL_CONNECT_TIMEOUT_SECONDS", "0"),
        ("MODEL_CONNECT_TIMEOUT_SECONDS", "-1"),
        ("MODEL_READ_TIMEOUT_SECONDS", "soon"),
        ("MODEL_READ_TIMEOUT_SECONDS", "nan"),
        ("MODEL_READ_TIMEOUT_SECONDS", "inf"),
        ("MODEL_MAX_TOKENS", "0"),
        ("MODEL_MAX_TOKENS", "1.5"),
    ],
)
def test_invalid_numbers_name_the_variable(name: str, value: str) -> None:
    with pytest.raises(SettingsError) as error:
        ModelSettings.from_env({"EI_AI_ENV": "test", name: value})

    assert name in str(error.value)
    assert value not in str(error.value).replace(name, "")


@pytest.mark.parametrize("value", ["-0.1", "never", "inf"])
def test_retry_delay_must_be_zero_or_more(value: str) -> None:
    with pytest.raises(SettingsError) as error:
        ModelSettings.from_env({"EI_AI_ENV": "test", "MODEL_RETRY_DELAY_SECONDS": value})

    assert str(error.value) == "MODEL_RETRY_DELAY_SECONDS must be a number of seconds >= 0"


def test_repr_masks_url_credentials() -> None:
    settings = ModelSettings.from_env(
        {
            "EI_AI_ENV": "test",
            "MODEL_LOCAL_BASE_URL": "http://user:local-pw@model:8080/v1",
            "EGRESS_PROXY_URL": "http://proxy-user:proxy-pw@proxy:3128",
        }
    )

    text = repr(settings)

    assert "local-pw" not in text
    assert "proxy-pw" not in text
    assert "***" in text


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(SettingsError):
        ModelSettings.from_env({"EI_AI_ENV": "staging"})


@pytest.mark.parametrize("environment", ["local", "test"])
def test_http_cloud_base_url_is_allowed_outside_production(environment: str) -> None:
    url = "http://127.0.0.1:9999/v1"

    assert require_https_in_production(environment, "openai", url) == url


@pytest.mark.parametrize("url", ["http://api.openai.com/v1", "ftp://api.openai.com/v1"])
def test_production_rejects_non_https_cloud_base_urls(url: str) -> None:
    with pytest.raises(SettingsError) as error:
        require_https_in_production("production", "openai", url)

    assert str(error.value) == "cloud provider openai must use an https base URL in production"


def test_production_accepts_https_cloud_base_urls() -> None:
    url = "https://api.openai.com/v1"

    assert require_https_in_production("production", "openai", url) == url


def test_provider_registry_refuses_an_http_cloud_url_in_production() -> None:
    settings = ModelSettings(environment="production")

    with pytest.raises(SettingsError):
        ProviderRegistry.from_settings(settings, cloud_base_urls={"openai": "http://evil/v1"})


def test_provider_registry_uses_https_openai_by_default_in_production() -> None:
    registry = ProviderRegistry.from_settings(ModelSettings(environment="production"))

    openai = registry.get("openai")
    assert openai is not None
    assert (openai.base_url, openai.deployment) == ("https://api.openai.com/v1", "cloud")
