"""Wiring of the production gateway: database catalog, providers from the settings, transport."""

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.model_gateway.catalog import DbCatalog
from ei_ai.model_gateway.gateway import ModelGateway
from ei_ai.model_gateway.observer import LoggingObserver, ModelCallObserver
from ei_ai.model_gateway.providers import ProviderRegistry
from ei_ai.model_gateway.transport import CloudCredentials, NoCloudCredentials, Transport
from ei_ai.settings import ModelSettings


def build_gateway(
    settings: ModelSettings,
    engine: AsyncEngine,
    credentials: CloudCredentials | None = None,
    observers: Iterable[ModelCallObserver] | None = None,
) -> ModelGateway:
    """The gateway for ``ei_ai_app``'s engine. Without a BYOK store every cloud call fails closed;
    the default observer is the metadata-only log line."""
    return ModelGateway(
        catalog=DbCatalog(engine),
        providers=ProviderRegistry.from_settings(settings),
        transport=Transport(settings, credentials or NoCloudCredentials()),
        observers=(LoggingObserver(),) if observers is None else tuple(observers),
        retry_delay_seconds=settings.retry_delay_seconds,
        default_max_tokens=settings.max_tokens,
    )
