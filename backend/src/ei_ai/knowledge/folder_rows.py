"""Row reads and writes of folders, run inside the caller's tenant transaction.

Every statement carries the explicit Organization and collection filters (layer 1) on top of
row-level security (layer 2, D46).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class FolderRow:
    id: uuid.UUID
    collection_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    depth: int
    document_count: int = 0


# The documents directly in the folder, counted within the same organization and collection.
_COUNT = (
    "(SELECT count(*) FROM documents d WHERE d.org_id = folders.org_id"
    " AND d.collection_id = folders.collection_id AND d.folder_id = folders.id)"
)
_COLUMNS = f"id, collection_id, parent_id, name, depth, {_COUNT} AS document_count"


def _to_row(row: Any) -> FolderRow:
    return FolderRow(**dict(row._mapping))


async def list_folder_rows(
    conn: AsyncConnection, org_id: uuid.UUID, collection_id: uuid.UUID
) -> list[FolderRow]:
    """The folders of one collection, by depth, then by name ignoring case."""
    result = await conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM folders"
            " WHERE org_id = :org AND collection_id = :collection"
            " ORDER BY depth, lower(name), id"
        ),
        {"org": org_id, "collection": collection_id},
    )
    return [_to_row(row) for row in result]


async def find_folder_row(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> FolderRow | None:
    """One folder of the collection, else None; ``for_update`` locks the row until the
    transaction ends."""
    if for_update:
        result = await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM folders"
                " WHERE org_id = :org AND collection_id = :collection AND id = :id FOR UPDATE"
            ),
            {"org": org_id, "collection": collection_id, "id": folder_id},
        )
    else:
        result = await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM folders"
                " WHERE org_id = :org AND collection_id = :collection AND id = :id"
            ),
            {"org": org_id, "collection": collection_id, "id": folder_id},
        )
    row = result.one_or_none()
    return None if row is None else _to_row(row)


async def insert_folder(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    collection_id: uuid.UUID,
    *,
    parent_id: uuid.UUID | None,
    name: str,
    depth: int,
) -> FolderRow:
    """Insert a folder with already validated values and return it."""
    result = await conn.execute(
        text(
            "INSERT INTO folders (org_id, collection_id, parent_id, name, depth)"
            " VALUES (:org, :collection, :parent, :name, :depth)"
            f" RETURNING {_COLUMNS}"
        ),
        {
            "org": org_id,
            "collection": collection_id,
            "parent": parent_id,
            "name": name,
            "depth": depth,
        },
    )
    return _to_row(result.one())


async def rename_folder_row(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    name: str,
) -> FolderRow:
    """Set the name of a folder and return it."""
    result = await conn.execute(
        text(
            "UPDATE folders SET name = :name"
            " WHERE org_id = :org AND collection_id = :collection AND id = :id"
            f" RETURNING {_COLUMNS}"
        ),
        {"org": org_id, "collection": collection_id, "id": folder_id, "name": name},
    )
    return _to_row(result.one())


async def has_subfolders(
    conn: AsyncConnection, org_id: uuid.UUID, collection_id: uuid.UUID, folder_id: uuid.UUID
) -> bool:
    """Whether the folder has at least one direct subfolder."""
    result = await conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM folders"
            " WHERE org_id = :org AND collection_id = :collection AND parent_id = :id)"
        ),
        {"org": org_id, "collection": collection_id, "id": folder_id},
    )
    return bool(result.scalar_one())


async def has_documents(
    conn: AsyncConnection, org_id: uuid.UUID, collection_id: uuid.UUID, folder_id: uuid.UUID
) -> bool:
    """Whether the folder directly holds at least one document."""
    result = await conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM documents"
            " WHERE org_id = :org AND collection_id = :collection AND folder_id = :id)"
        ),
        {"org": org_id, "collection": collection_id, "id": folder_id},
    )
    return bool(result.scalar_one())


async def delete_folder_row(
    conn: AsyncConnection, org_id: uuid.UUID, collection_id: uuid.UUID, folder_id: uuid.UUID
) -> None:
    """Delete a folder (the caller has checked that it has no subfolders)."""
    await conn.execute(
        text(
            "DELETE FROM folders WHERE org_id = :org AND collection_id = :collection AND id = :id"
        ),
        {"org": org_id, "collection": collection_id, "id": folder_id},
    )
