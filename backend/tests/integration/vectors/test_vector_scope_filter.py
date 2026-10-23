"""EA-36: the collection/folder scope of ``nearest`` fails closed. ``()`` matches nothing,
``None`` (any collection) is only the explicit unscoped value, and a folder grants its rows."""

import uuid
from dataclasses import dataclass

import pytest
from psycopg.errors import CheckViolation
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.tenancy.context import TenantContext
from ei_ai.vectors.search import EMBEDDING_DIMENSIONS, VectorFilter, nearest
from support.tenants import OrgRows, TwoOrgs
from support.vectors import DEFAULT_MODEL, insert_vector

pytestmark = [pytest.mark.integration, pytest.mark.isolation]

LEVELS = ("public", "authenticated")


def _unit(index: int) -> list[float]:
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[index] = 1.0
    return values


@dataclass(frozen=True)
class Seeded:
    """Org A: folder f1 = 2 rows (the fixture row + 1), f2 = 1 row, a second collection c2 = 2
    rows; org B: 2 rows in B's own collection and folder."""

    a: OrgRows
    b: OrgRows
    f1: set[uuid.UUID]
    f2: set[uuid.UUID]
    c2: uuid.UUID
    c2_rows: set[uuid.UUID]
    b_rows: set[uuid.UUID]


async def _add(
    engine: AsyncEngine,
    org: OrgRows,
    count: int,
    *,
    collection: uuid.UUID | None = None,
    folder: uuid.UUID | None = None,
) -> set[uuid.UUID]:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        return {
            await insert_vector(conn, org, _unit(0), collection_id=collection, folder_id=folder)
            for _ in range(count)
        }


async def _search(engine: AsyncEngine, org: OrgRows, where: VectorFilter) -> set[uuid.UUID]:
    tenant = TenantContext(org_id=org.org_id, user_id=org.user_id)
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        hits = await nearest(conn, tenant, _unit(0), 40, model=DEFAULT_MODEL, where=where)
    return {hit.id for hit in hits}


@pytest.fixture
async def seeded(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> Seeded:
    a, b = two_orgs.a, two_orgs.b
    c2 = uuid.uuid4()
    f1 = {a.chunk_embedding_id} | await _add(app_engine, a, 1)
    f2 = await _add(app_engine, a, 1, folder=a.empty_folder_id)
    c2_rows = await _add(app_engine, a, 2, collection=c2, folder=uuid.uuid4())
    b_rows = {b.chunk_embedding_id} | await _add(app_engine, b, 1)
    return Seeded(a, b, f1, f2, c2, c2_rows, b_rows)


async def test_empty_scope_arrays_match_no_row(app_engine: AsyncEngine, seeded: Seeded) -> None:
    assert await _search(app_engine, seeded.a, VectorFilter((), LEVELS, (), ())) == set()


async def test_folder_only_filter_returns_only_folder_rows(
    app_engine: AsyncEngine, seeded: Seeded
) -> None:
    where = VectorFilter((), LEVELS, (), (seeded.a.folder_id,))

    assert await _search(app_engine, seeded.a, where) == seeded.f1
    assert len(seeded.f1) == 2


async def test_collections_or_folders(app_engine: AsyncEngine, seeded: Seeded) -> None:
    where = VectorFilter((seeded.c2,), LEVELS, (), (seeded.a.empty_folder_id,))

    found = await _search(app_engine, seeded.a, where)

    assert found == seeded.c2_rows | seeded.f2
    assert len(found) == 3
    assert not found & (seeded.f1 | seeded.b_rows)


async def test_scope_never_crosses_the_organization(
    app_engine: AsyncEngine, seeded: Seeded
) -> None:
    where = VectorFilter((seeded.b.collection_id,), LEVELS, (), (seeded.b.folder_id,))

    assert await _search(app_engine, seeded.a, where) == set()


async def test_public_row_with_groups_is_rejected_by_check(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    with pytest.raises(DBAPIError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
            await insert_vector(conn, a, _unit(0), access_level="public", groups=("hr",))

    assert isinstance(error.value.orig, CheckViolation)
