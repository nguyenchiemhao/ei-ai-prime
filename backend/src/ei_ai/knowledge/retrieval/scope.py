"""Resolve a knowledge scope to the collections a principal may read (EA-36, spec section 3).

Unknown, other-Workspace and other-Organization ids all answer ``not_found``: the same, so the
answer is no existence oracle (D46). An unreadable collection, and a folder inside one, answer
``no_access``. An empty or fully unreadable scope searches nothing (fail closed).
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.knowledge.retrieval.access import can_read
from ei_ai.knowledge.retrieval.principal import RetrievalPrincipal
from ei_ai.knowledge.retrieval.scope_rows import collections_by_id, folder_trees


@dataclass(frozen=True)
class KnowledgeScope:
    workspace_id: uuid.UUID
    collection_ids: tuple[uuid.UUID, ...] = ()
    folder_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class Skipped:
    kind: Literal["collection", "folder"]
    id: uuid.UUID
    reason: Literal["no_access", "not_found"]


@dataclass(frozen=True)
class ResolvedScope:
    searched_collection_ids: tuple[uuid.UUID, ...]
    folder_ids: tuple[uuid.UUID, ...]
    readable_collection_ids: tuple[uuid.UUID, ...]
    skipped: tuple[Skipped, ...]


def _unique(ids: Iterable[uuid.UUID]) -> tuple[uuid.UUID, ...]:
    return tuple(dict.fromkeys(ids))


async def resolve_scope(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    scope: KnowledgeScope,
    principal: RetrievalPrincipal,
) -> ResolvedScope:
    """Input: the connection in the tenant transaction, its Organization (from the verified
    identity), the scope and the principal. Output: what is searched, what is readable and why
    each other id was skipped. Ids keep their input order, without duplicates."""
    wanted_collections = _unique(scope.collection_ids)
    wanted_folders = _unique(scope.folder_ids)
    if not wanted_collections and not wanted_folders:
        return ResolvedScope((), (), (), ())
    trees = (
        await folder_trees(conn, org_id, scope.workspace_id, wanted_folders)
        if wanted_folders
        else {}
    )
    lookup = _unique([*wanted_collections, *(collection for collection, _ in trees.values())])
    rows = await collections_by_id(conn, org_id, scope.workspace_id, lookup)
    known = {collection_id for collection_id, _, _ in rows}
    readable = {
        collection_id for collection_id, level, groups in rows if can_read(principal, level, groups)
    }
    skipped: list[Skipped] = []
    searched: list[uuid.UUID] = []
    for collection_id in wanted_collections:
        if collection_id in readable:
            searched.append(collection_id)
        else:
            reason: Literal["no_access", "not_found"] = (
                "no_access" if collection_id in known else "not_found"
            )
            skipped.append(Skipped("collection", collection_id, reason))
    folders: list[uuid.UUID] = []
    folder_collections: list[uuid.UUID] = []
    for folder_id in wanted_folders:
        tree = trees.get(folder_id)
        if tree is None:
            skipped.append(Skipped("folder", folder_id, "not_found"))
        elif tree[0] in readable:
            folders.extend(tree[1])
            folder_collections.append(tree[0])
        else:
            skipped.append(Skipped("folder", folder_id, "no_access"))
    return ResolvedScope(
        searched_collection_ids=tuple(searched),
        folder_ids=_unique(folders),
        readable_collection_ids=_unique([*searched, *folder_collections]),
        skipped=tuple(skipped),
    )
