"""SQL on ``organization_keys``, run inside the caller's tenant transaction.

Every statement carries the explicit Organization filter (layer 1) on top of row-level
security (layer 2, D46). Nothing here logs or returns an unwrapped key.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from ei_ai.db.tenant import TenantExecutor


@dataclass(frozen=True)
class KeyRow:
    wrapped_key: bytes | None
    kek_id: str
    destroyed_at: datetime | None

    def __repr__(self) -> str:
        return f"KeyRow(kek_id={self.kek_id!r}, destroyed={self.destroyed_at is not None})"


async def insert_key_row(
    conn: TenantExecutor, org_id: uuid.UUID, wrapped_key: bytes, kek_id: str
) -> uuid.UUID:
    result = await conn.execute(
        text(
            "INSERT INTO organization_keys (org_id, wrapped_key, kek_id)"
            " VALUES (:org, :wrapped, :kek) RETURNING id"
        ),
        {"org": org_id, "wrapped": wrapped_key, "kek": kek_id},
    )
    key_id: uuid.UUID = result.scalar_one()
    return key_id


async def read_key_row(conn: TenantExecutor, org_id: uuid.UUID) -> KeyRow | None:
    result = await conn.execute(
        text("SELECT wrapped_key, kek_id, destroyed_at FROM organization_keys WHERE org_id = :org"),
        {"org": org_id},
    )
    row = result.first()
    if row is None:
        return None
    wrapped = None if row.wrapped_key is None else bytes(row.wrapped_key)
    return KeyRow(wrapped, row.kek_id, row.destroyed_at)


async def mark_key_destroyed(conn: TenantExecutor, org_id: uuid.UUID) -> bool:
    """Erase the wrapped key; False when there is no live key row."""
    result = await conn.execute(
        text(
            "UPDATE organization_keys SET wrapped_key = NULL, destroyed_at = now()"
            " WHERE org_id = :org AND destroyed_at IS NULL"
        ),
        {"org": org_id},
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]
