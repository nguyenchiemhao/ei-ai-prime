"""Writing manifest entries into an Organization's catalog, inside the caller's tenant
transaction (``ei-ai model add`` and the demo seed). Never updates or deletes a row."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.model_gateway.manifest import ManifestEntry, load_platform_models

_COLUMNS = (
    "kind",
    "display_name",
    "model_id",
    "version",
    "digest",
    "source_revision",
    "deployment",
    "provider",
    "vietnamese_quality",
    "vietnamese_quality_measured",
    "tool_use",
    "context_window",
    "speed",
    "status",
)
_INSERT = text(
    f"INSERT INTO model_catalog (org_id, {', '.join(_COLUMNS)})"
    f" VALUES (:org, {', '.join(f':{name}' for name in _COLUMNS)})"
    " ON CONFLICT (org_id, model_id, version) DO NOTHING RETURNING id"
)


async def insert_manifest_entry(
    conn: AsyncConnection, org_id: uuid.UUID, entry: ManifestEntry
) -> uuid.UUID | None:
    """Insert ``entry`` for the Organization; its new row id, or None when the ref is present."""
    values = {name: getattr(entry, name) for name in _COLUMNS}
    result = await conn.execute(_INSERT, {"org": org_id, **values})
    new_id: uuid.UUID | None = result.scalar_one_or_none()
    return new_id


async def ensure_platform_models(conn: AsyncConnection, org_id: uuid.UUID) -> None:
    """Insert every manifest entry the Organization does not have yet (no audit: demo seed)."""
    for entry in load_platform_models().entries:
        await insert_manifest_entry(conn, org_id, entry)
