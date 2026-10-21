"""Reading an Organization's model catalog (EA-24).

``DbCatalog.resolve`` reads exactly the requested ref in the caller's tenant transaction, with the
explicit Organization filter on top of row-level security (D46). It never picks another row: a
missing, other-kind or retired ref is an error, not a reason to look further (D18). No
transaction stays open during a model call.
"""

import datetime
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import MODEL_CLOUD_CALL_BLOCKED, record_event
from ei_ai.db.tenant import tenant_transaction
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.manifest import Kind
from ei_ai.model_gateway.refs import ModelRef


@dataclass(frozen=True)
class CatalogEntry:
    """The pinned fields of one ``model_catalog`` row that a call needs."""

    id: uuid.UUID
    kind: str
    model_id: str
    version: str
    digest: str | None
    deployment: str
    provider: str
    status: str = "available"
    retirement_date: datetime.date | None = None

    @property
    def ref(self) -> ModelRef:
        return ModelRef(self.model_id, self.version)


@dataclass(frozen=True)
class Resolved:
    """A callable catalog row and the Organization's "Allow cloud models" switch (D17)."""

    entry: CatalogEntry
    cloud_allowed: bool


class CatalogReader(Protocol):
    async def resolve(self, ctx: ModelCallContext, ref: ModelRef, kind: Kind = "chat") -> Resolved:
        """The row of ``ref`` in the caller's Organization; raises ``ModelError``."""
        ...

    async def record_cloud_block(self, ctx: ModelCallContext, entry: CatalogEntry) -> None:
        """Audit a blocked cloud call; committed before the caller gets ``CLOUD_DISABLED``."""
        ...


def utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.UTC).date()


def ensure_callable(entry: CatalogEntry, today: datetime.date) -> CatalogEntry:
    """``entry`` unless it is retired: status ``retired`` or a retirement date today or earlier
    (``retiring`` stays callable until its date, D18)."""
    retired = entry.status == "retired" or (
        entry.retirement_date is not None and entry.retirement_date <= today
    )
    if retired:
        raise ModelError(ModelErrorCode.MODEL_RETIRED, str(entry.ref), entry.kind)
    return entry


_RESOLVE = text(
    "SELECT m.id, m.kind, m.model_id, m.version, m.digest, m.deployment, m.provider, m.status,"
    " m.retirement_date, o.allow_cloud_models"
    " FROM model_catalog m JOIN organizations o ON o.id = m.org_id"
    " WHERE m.org_id = :org AND o.id = :org"
    " AND m.model_id = :model_id AND m.version = :version AND m.kind = :kind"
)


class DbCatalog:
    """The catalog in PostgreSQL, read as ``ei_ai_app``."""

    def __init__(self, engine: AsyncEngine, today: Callable[[], datetime.date] = utc_today) -> None:
        self._engine = engine
        self._today = today

    async def resolve(self, ctx: ModelCallContext, ref: ModelRef, kind: Kind = "chat") -> Resolved:
        params = {
            "org": ctx.org_id,
            "model_id": ref.model_id,
            "version": ref.version,
            "kind": kind,
        }
        async with self._engine.connect() as conn, tenant_transaction(conn, ctx.org_id):
            row = (await conn.execute(_RESOLVE, params)).first()
        if row is None:
            raise ModelError(ModelErrorCode.MODEL_NOT_FOUND, str(ref), kind)
        entry = CatalogEntry(*row[:9])
        return Resolved(ensure_callable(entry, self._today()), cloud_allowed=bool(row[9]))

    async def record_cloud_block(self, ctx: ModelCallContext, entry: CatalogEntry) -> None:
        async with self._engine.connect() as conn, tenant_transaction(conn, ctx.org_id):
            await record_event(
                conn, ctx.org_id, ctx.actor, MODEL_CLOUD_CALL_BLOCKED, "model", entry.id
            )
