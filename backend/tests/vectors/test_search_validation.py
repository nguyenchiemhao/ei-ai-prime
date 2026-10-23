"""EA-20 vector namespace, without a database: input validation of ``nearest`` and the partition
name, which is derived from a ``uuid.UUID`` object only."""

import inspect
import math
import uuid
from typing import Any

import pytest

from ei_ai.model_gateway.refs import ModelRef
from ei_ai.tenancy.context import TenantContext
from ei_ai.vectors.partitions import (
    create_vector_partition,
    drop_vector_partition,
    partition_name,
)
from ei_ai.vectors.search import (
    EMBEDDING_DIMENSIONS,
    MAX_K,
    NEAREST_SQL,
    VectorFilter,
    VectorHit,
    nearest,
)

TENANT = TenantContext(org_id=uuid.uuid4(), user_id=uuid.uuid4())
VALID = [0.0] * EMBEDDING_DIMENSIONS
MODEL = ModelRef("bge-m3", "2026.10")


class _NoDatabase:
    """A session that fails the test if validation lets a call through to the database."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("validation must reject the call before any SQL runs")


def _with(index: int, value: float) -> list[float]:
    query = list(VALID)
    query[index] = value
    return query


@pytest.mark.parametrize(
    ("query", "k"),
    [
        ([0.0] * (EMBEDDING_DIMENSIONS - 1), 5),
        ([0.0] * (EMBEDDING_DIMENSIONS + 1), 5),
        ([], 5),
        (_with(0, math.nan), 5),
        (_with(3, math.inf), 5),
        (_with(EMBEDDING_DIMENSIONS - 1, -math.inf), 5),
        (VALID, 0),
        (VALID, -1),
        (VALID, MAX_K + 1),
    ],
)
async def test_nearest_validates_dimensions_k_and_finiteness(query: list[float], k: int) -> None:
    with pytest.raises(ValueError):
        await nearest(_NoDatabase(), TENANT, query, k, model=MODEL, where=None)  # type: ignore[arg-type]


async def test_nearest_needs_the_verified_context() -> None:
    with pytest.raises(TypeError):
        await nearest(_NoDatabase(), TENANT.org_id, VALID, 5, model=MODEL, where=None)  # type: ignore[arg-type]


def test_the_constants_match_the_spec() -> None:
    assert (EMBEDDING_DIMENSIONS, MAX_K) == (1024, 40)
    # The tenant filter and the model pin are part of the one statement.
    assert (
        " WHERE org_id = :org AND model_id = :model_id AND model_version = :model_version"
        in NEAREST_SQL
    )
    hit = VectorHit(
        id=TENANT.org_id,
        chunk_id=TENANT.org_id,
        document_id=TENANT.org_id,
        collection_id=TENANT.org_id,
        distance=0.5,
    )
    with pytest.raises(AttributeError):
        hit.distance = 0.1  # type: ignore[misc]


def test_vector_filter_is_frozen_and_checks_levels() -> None:
    assert VectorFilter() == VectorFilter(None, (), (), ())
    with pytest.raises(ValueError):
        VectorFilter(access_levels=("public", "admin"))
    with pytest.raises(AttributeError):
        VectorFilter().groups = ("x",)  # type: ignore[misc]


def test_vector_filter_folders_need_a_collection_list() -> None:
    folder = uuid.uuid4()
    with pytest.raises(ValueError, match="collection_ids must not be None when folder_ids"):
        VectorFilter(folder_ids=(folder,))
    assert VectorFilter(collection_ids=(), folder_ids=(folder,)).folder_ids == (folder,)


def test_nearest_sql_scope_and_access_clauses() -> None:
    assert (
        " AND (CAST(:collections AS uuid[]) IS NULL"
        " OR collection_id = ANY(CAST(:collections AS uuid[]))"
        " OR folder_id = ANY(CAST(:folders AS uuid[])))"
    ) in NEAREST_SQL
    assert (
        " AND (NOT :filtered OR access_level = ANY(CAST(:levels AS text[]))"
        " OR groups && CAST(:groups AS text[]))"
    ) in NEAREST_SQL


def test_nearest_requires_where() -> None:
    assert inspect.signature(nearest).parameters["where"].default is inspect.Parameter.empty


def test_partition_name_is_derived_from_the_uuid() -> None:
    org_id = uuid.UUID("0123456789abcdef0123456789abcdef")

    assert partition_name(org_id) == "chunk_embeddings_0123456789abcdef0123456789abcdef"
    assert len(partition_name(uuid.uuid4())) == 49


@pytest.mark.parametrize(
    "value",
    [
        "0123456789abcdef0123456789abcdef",
        "01234567-89ab-cdef-0123-456789abcdef",
        "x'); DROP TABLE organizations; --",
        0,
        None,
    ],
)
def test_partition_functions_reject_strings(value: object) -> None:
    for function in (partition_name,):
        with pytest.raises(TypeError):
            function(value)  # type: ignore[arg-type]
    for command in (create_vector_partition, drop_vector_partition):
        with pytest.raises(TypeError):
            command(_NoConnection(), value)  # type: ignore[arg-type]


class _NoConnection:
    """A connection that fails the test if a command uses it before the type check."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError("the type check must run before the connection is used")
