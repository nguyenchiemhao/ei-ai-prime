"""EA-35 AC3/AC4/AC6 (vector half): permission and model metadata, and the filtered query."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.tenancy.context import TenantContext
from ei_ai.vectors.search import EMBEDDING_DIMENSIONS, VectorFilter, nearest
from support.tenants import OrgRows, TwoOrgs
from support.vectors import DEFAULT_MODEL, insert_vector

pytestmark = [pytest.mark.integration, pytest.mark.isolation]

ALL_LEVELS = ("public", "authenticated", "restricted")
FUTURE_MODEL = ModelRef("bge-m3", "2099.01")


def _unit(index: int) -> list[float]:
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[index] = 1.0
    return values


def _near(offset: float) -> list[float]:
    """A vector at a growing distance from ``_unit(0)``."""
    values = _unit(0)
    values[1] = offset
    return values


def _tenant(org: OrgRows) -> TenantContext:
    return TenantContext(org_id=org.org_id, user_id=org.user_id)


async def _add(
    engine: AsyncEngine,
    org: OrgRows,
    embedding: list[float],
    *,
    model: ModelRef = DEFAULT_MODEL,
    chunk_id: uuid.UUID | None = None,
) -> uuid.UUID:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        return await insert_vector(conn, org, embedding, model=model, chunk_id=chunk_id)


async def _search(
    engine: AsyncEngine,
    org: OrgRows,
    k: int,
    *,
    where: VectorFilter | None = None,
    model: ModelRef = DEFAULT_MODEL,
    force_index: bool = False,
) -> list[uuid.UUID]:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        if force_index:
            # On a tiny table the planner prefers a btree scan plus sort and never reaches HNSW;
            # without those two paths the ordered HNSW scan is the only plan left.
            await conn.execute(text("SET LOCAL enable_seqscan = off"))
            await conn.execute(text("SET LOCAL enable_sort = off"))
        hits = await nearest(conn, _tenant(org), _unit(0), k, model=model, where=where)
    return [hit.id for hit in hits]


_REQUIRED = (
    "chunk_id",
    "document_id",
    "workspace_id",
    "collection_id",
    "folder_id",
    "access_level",
    "model_id",
    "model_version",
)


async def _raw_insert(
    engine: AsyncEngine,
    org: OrgRows,
    over: dict[str, object] | None = None,
    *,
    omit: str | None = None,
) -> None:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        chunk = (
            await conn.execute(
                text(
                    "INSERT INTO document_chunks (org_id, document_id, ordinal, text, char_start,"
                    " char_end, token_estimate) VALUES (:org, :document,"
                    " (SELECT max(ordinal) + 1 FROM document_chunks WHERE org_id = :org), 'qa',"
                    " 0, 2, 1) RETURNING id"
                ),
                {"org": org.org_id, "document": org.document_id},
            )
        ).scalar_one()
        values: dict[str, object] = {
            "chunk_id": chunk,
            "document_id": org.document_id,
            "workspace_id": org.workspace_id,
            "collection_id": org.collection_id,
            "folder_id": org.folder_id,
            "access_level": "authenticated",
            "model_id": "bge-m3",
            "model_version": "2026.10",
            **(over or {}),
        }
        if omit:
            del values[omit]
        columns = ", ".join(values)
        binds = ", ".join(f":{name}" for name in values)
        await conn.execute(
            text(
                f"INSERT INTO chunk_embeddings (org_id, embedding, {columns})"
                f" VALUES (:org, array_fill(0.1::real, ARRAY[1024])::vector, {binds})"
            ),
            {"org": org.org_id, **values},
        )


@pytest.mark.parametrize("column", _REQUIRED)
async def test_vector_rows_require_every_metadata_column(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, column: str
) -> None:
    with pytest.raises(DBAPIError) as error:
        await _raw_insert(app_engine, two_orgs.a, omit=column)
    assert getattr(error.value.orig, "sqlstate", None) == "23502"  # not_null_violation


@pytest.mark.parametrize(
    "over",
    [
        {"access_level": "restricted"},  # restricted needs a group
        {"access_level": "secret"},
        {"model_id": "BGE M3"},
        {"model_version": "-1"},
    ],
)
async def test_vector_rows_reject_inconsistent_metadata(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, over: dict[str, object]
) -> None:
    with pytest.raises(DBAPIError) as error:
        await _raw_insert(app_engine, two_orgs.a, over)
    assert getattr(error.value.orig, "sqlstate", None) == "23514"  # check_violation


async def test_a_chunk_has_at_most_one_vector(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    with pytest.raises(DBAPIError) as error:
        await _add(app_engine, two_orgs.a, _unit(0), chunk_id=two_orgs.a.chunk_id)
    assert getattr(error.value.orig, "sqlstate", None) == "23505"  # unique_violation


async def test_deleting_a_document_removes_its_vectors(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await _add(app_engine, a, _unit(0))
    count = text("SELECT count(*) FROM chunk_embeddings WHERE org_id = :org AND document_id = :d")
    params = {"org": a.org_id, "d": a.document_id}
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        before = (await conn.execute(count, params)).scalar_one()
        await conn.execute(text("DELETE FROM documents WHERE org_id = :org AND id = :d"), params)
        after = (await conn.execute(count, params)).scalar_one()
    assert before >= 2
    assert after == 0


async def test_nearest_in_org_b_never_returns_org_a_vectors(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    a_ids = {a.chunk_embedding_id, await _add(app_engine, a, _unit(0))}  # distance 0
    b_id = await _add(app_engine, b, _unit(1))  # distance 1

    plain = await _search(app_engine, b, 40)
    filtered = await _search(app_engine, b, 40, where=VectorFilter(access_levels=ALL_LEVELS))

    for ids in (plain, filtered):
        assert b_id in ids
        assert not a_ids & set(ids)
        assert set(ids) <= {b.chunk_embedding_id, b_id}


async def test_filtered_nearest_returns_allowed_entries_when_restricted_ones_are_nearer(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(
            text("DELETE FROM chunk_embeddings WHERE org_id = :org"), {"org": a.org_id}
        )
        restricted = [
            await insert_vector(
                conn, a, _near(0.001 * (i + 1)), access_level="restricted", groups=("hr",)
            )
            for i in range(60)
        ]
        public = [
            await insert_vector(conn, a, _near(1.0 + i), access_level="public") for i in range(3)
        ]

    only_public = await _search(
        app_engine, a, 3, where=VectorFilter(access_levels=("public",)), force_index=True
    )
    with_group = await _search(
        app_engine,
        a,
        3,
        where=VectorFilter(access_levels=("public",), groups=("hr",)),
        force_index=True,
    )
    nothing = await _search(app_engine, a, 3, where=VectorFilter())

    assert sorted(only_public) == sorted(public)
    assert with_group == restricted[:3]
    assert nothing == []


async def test_nearest_ignores_vectors_of_another_model(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    other = await _add(app_engine, a, _unit(0), model=FUTURE_MODEL)

    current = await _search(app_engine, a, 40)
    future = await _search(app_engine, a, 40, model=FUTURE_MODEL)

    assert other not in current
    assert future == [other]


async def test_nearest_filters_by_collection(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    a = two_orgs.a
    own = VectorFilter(collection_ids=(a.collection_id,), access_levels=ALL_LEVELS)
    foreign = VectorFilter(collection_ids=(uuid.uuid4(),), access_levels=ALL_LEVELS)

    assert a.chunk_embedding_id in await _search(app_engine, a, 40, where=own)
    assert await _search(app_engine, a, 40, where=foreign) == []


def test_vector_filter_rejects_an_unknown_access_level() -> None:
    with pytest.raises(ValueError):
        VectorFilter(access_levels=("everyone",))


async def test_pgvector_supports_iterative_scan(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        version = (
            await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        ).scalar_one()
    assert tuple(int(part) for part in version.split(".")[:3]) >= (0, 8, 0)
