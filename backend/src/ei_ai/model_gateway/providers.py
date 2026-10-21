"""The provider registry: a catalog row names a provider key, never a URL (SSRF, P35).

Local providers are platform-internal llama.cpp servers whose base URLs come from the settings;
cloud providers have fixed, code-reviewed base URLs and always go through the egress proxy.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from ei_ai.settings import ModelSettings, require_https_in_production

Deployment = Literal["local", "cloud"]
# How the id a server serves is derived from a catalog row (see ``pinning.served_model_id``).
ServedIdRule = Literal["llama.cpp", "model_id"]

CLOUD_BASE_URLS: Mapping[str, str] = {"openai": "https://api.openai.com/v1"}


@dataclass(frozen=True)
class Provider:
    key: str
    deployment: Deployment
    # None: not configured; a call fails without network access.
    base_url: str | None
    served_id_rule: ServedIdRule


class ProviderRegistry:
    def __init__(self, providers: Mapping[str, Provider]) -> None:
        self._providers = dict(providers)

    def get(self, key: str) -> Provider | None:
        return self._providers.get(key)

    @classmethod
    def from_settings(
        cls, settings: ModelSettings, cloud_base_urls: Mapping[str, str] = CLOUD_BASE_URLS
    ) -> "ProviderRegistry":
        """The three local providers from the settings and the cloud providers; a cloud base
        URL must be https in production (raises ``SettingsError``)."""
        local = {
            "local-chat": settings.local_base_url,
            "local-embedding": settings.embedding_base_url,
            "local-rerank": settings.rerank_base_url,
        }
        providers = {key: Provider(key, "local", url, "llama.cpp") for key, url in local.items()}
        for key, url in cloud_base_urls.items():
            checked = require_https_in_production(settings.environment, key, url)
            providers[key] = Provider(key, "cloud", checked, "model_id")
        return cls(providers)
