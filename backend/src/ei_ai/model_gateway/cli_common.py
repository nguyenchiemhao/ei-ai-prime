"""Argument checks and errors shared by the ``ei-ai model`` commands (messages safe to print)."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.model_gateway.refs import InvalidModelRef, ModelRef

_ORG_ID = "--org must be an Organization id (UUID)"
_MODEL_REF = "--model must be <model_id>@<version>"
_MAX_TOKENS = "--max-tokens must be a positive integer"


class CommandRefused(Exception):
    """A bad argument (exit 2)."""


class CommandFailed(Exception):
    """A user-safe failure of a command (exit 1)."""


def parse_org_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        raise CommandRefused(_ORG_ID) from None


def parse_ref(raw: str) -> ModelRef:
    try:
        return ModelRef.parse(raw)
    except InvalidModelRef:
        raise CommandRefused(_MODEL_REF) from None


def parse_max_tokens(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise CommandRefused(_MAX_TOKENS) from None
    if value < 1:
        raise CommandRefused(_MAX_TOKENS)
    return value


async def organization_exists(conn: AsyncConnection, org_id: uuid.UUID) -> bool:
    """True when the Organization row is visible in this tenant transaction."""
    result = await conn.execute(
        text("SELECT 1 FROM organizations WHERE id = :org"), {"org": org_id}
    )
    return result.first() is not None


async def ensure_organization(engine: AsyncEngine, org_id: uuid.UUID) -> None:
    """Raise ``CommandFailed("Organization not found")`` unless the Organization exists."""
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        found = await organization_exists(conn, org_id)
    if not found:
        raise CommandFailed("Organization not found")
