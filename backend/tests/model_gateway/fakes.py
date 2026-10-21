"""In-memory catalog and a gateway builder for the Model Gateway unit tests."""

import datetime
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from ei_ai.model_gateway.catalog import CatalogEntry, Resolved, ensure_callable
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.gateway import ModelGateway
from ei_ai.model_gateway.manifest import Kind
from ei_ai.model_gateway.observer import ModelCallObserver, ModelCallRecord
from ei_ai.model_gateway.providers import ProviderRegistry
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.model_gateway.transport import Transport
from ei_ai.settings import ModelSettings
from support.fake_model_server import FakeModelServer
from support.forward_proxy import ForwardProxy

ORG_A = uuid.UUID("0192a000-0000-7000-8000-00000000000a")
ORG_B = uuid.UUID("0192a000-0000-7000-8000-00000000000b")
CTX = ModelCallContext(org_id=ORG_A, actor="platform-operator")
TODAY = datetime.date(2026, 10, 20)

QWEN_DIGEST = "sha256:3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
QWEN_SERVED = "qwen3-4b-instruct-2507@sha256-3605803b982c"
LOCAL = CatalogEntry(
    id=uuid.UUID("0192a000-0000-7000-8000-0000000000c1"),
    kind="chat",
    model_id="qwen3-4b-instruct-2507",
    version="2026.10",
    digest=QWEN_DIGEST,
    deployment="local",
    provider="local-chat",
)
NEWER = CatalogEntry(
    id=uuid.UUID("0192a000-0000-7000-8000-0000000000c2"),
    kind="chat",
    model_id="qwen3-4b-instruct-2507",
    version="qa-newer",
    digest=f"sha256:{'a' * 64}",
    deployment="local",
    provider="local-chat",
)
CLOUD = CatalogEntry(
    id=uuid.UUID("0192a000-0000-7000-8000-0000000000c3"),
    kind="chat",
    model_id="gpt-4.1-2025-04-14",
    version="2025.04",
    digest=None,
    deployment="cloud",
    provider="openai",
)
EMBED = CatalogEntry(
    id=uuid.UUID("0192a000-0000-7000-8000-0000000000c4"),
    kind="embedding",
    model_id="bge-m3",
    version="2026.10",
    digest=f"sha256:{'b' * 64}",
    deployment="local",
    provider="local-embedding",
)
RERANK = CatalogEntry(
    id=uuid.UUID("0192a000-0000-7000-8000-0000000000c5"),
    kind="rerank",
    model_id="bge-reranker-v2-m3",
    version="2026.10",
    digest=f"sha256:{'c' * 64}",
    deployment="local",
    provider="local-rerank",
)
EMBED_SERVED = f"bge-m3@sha256-{'b' * 12}"
RERANK_SERVED = f"bge-reranker-v2-m3@sha256-{'c' * 12}"


class Keys:
    """Fake BYOK store: one key per (Organization, provider)."""

    def __init__(self, keys: dict[tuple[uuid.UUID, str], str] | None = None) -> None:
        self.keys = keys if keys is not None else {(ORG_A, "openai"): "sk-org-a"}

    def api_key(self, org_id: uuid.UUID, provider: str) -> str | None:
        return self.keys.get((org_id, provider))


class FakeCatalog:
    """Catalog rows in memory; records every resolve and every audited cloud block."""

    def __init__(self, entries: Iterable[CatalogEntry], cloud_allowed: bool = False) -> None:
        self.entries = {(str(entry.ref), entry.kind): entry for entry in entries}
        self.cloud_allowed = cloud_allowed
        self.resolves: list[tuple[uuid.UUID, str, str]] = []
        self.blocks: list[tuple[ModelCallContext, CatalogEntry]] = []

    async def resolve(self, ctx: ModelCallContext, ref: ModelRef, kind: Kind = "chat") -> Resolved:
        self.resolves.append((ctx.org_id, str(ref), kind))
        entry = self.entries.get((str(ref), kind))
        if entry is None:
            raise ModelError(ModelErrorCode.MODEL_NOT_FOUND, str(ref), kind)
        return Resolved(ensure_callable(entry, TODAY), self.cloud_allowed)

    async def record_cloud_block(self, ctx: ModelCallContext, entry: CatalogEntry) -> None:
        self.blocks.append((ctx, entry))


@dataclass
class Collector:
    """An observer that keeps every record."""

    records: list[ModelCallRecord] = field(default_factory=list)

    def record(self, record: ModelCallRecord) -> None:
        self.records.append(record)


def build_gateway(
    catalog: FakeCatalog,
    *,
    local: FakeModelServer | None = None,
    cloud: FakeModelServer | None = None,
    proxy: ForwardProxy | None = None,
    keys: Keys | None = None,
    observers: Iterable[ModelCallObserver] = (),
    read_timeout: float = 2.0,
) -> ModelGateway:
    """A gateway on the fake servers: local providers at ``local``, ``openai`` at ``cloud``."""
    settings = ModelSettings(
        environment="test",
        local_base_url=None if local is None else local.base_url,
        embedding_base_url=None if local is None else local.base_url,
        rerank_base_url=None if local is None else local.base_url,
        read_timeout_seconds=read_timeout,
        retry_delay_seconds=0,
        egress_proxy_url=None if proxy is None else proxy.url,
    )
    cloud_urls = {"openai": cloud.base_url if cloud is not None else "http://127.0.0.1:9/v1"}
    return ModelGateway(
        catalog=catalog,
        providers=ProviderRegistry.from_settings(settings, cloud_base_urls=cloud_urls),
        transport=Transport(settings, keys or Keys()),
        observers=tuple(observers),
        retry_delay_seconds=0,
        default_max_tokens=settings.max_tokens,
    )
