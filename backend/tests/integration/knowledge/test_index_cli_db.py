"""``ei-ai index reindex``, ``status`` and ``search`` on the real database (EA-35 R15, AC4, AC6).

The CLI runs its own event loop, so it is called in a thread; the embedder is the deterministic
``FakeEmbedder`` injected through ``commands.build_embedder`` (no model, no network). The
``two_orgs`` fixture gives each Organization its vector partition and one ready document with one
chunk and one ``bge-m3@2026.10`` vector.
"""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai import cli
from ei_ai.db.tenant import tenant_transaction
from ei_ai.knowledge.indexing import commands
from ei_ai.knowledge.indexing.embedder import ChunkEmbedder
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.refs import ModelRef
from support.fake_embedder import FakeEmbedder
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

NEW_REF = ModelRef("bge-m3", "2099.01")
SENTINEL = "zebracorn7q4sentinel"
POISON = "poisonedchunk"


class SelectiveEmbedder:
    """A ``FakeEmbedder`` that fails with MODEL_UNAVAILABLE for texts that contain ``POISON``."""

    def __init__(self) -> None:
        self._inner = FakeEmbedder()
        self.ref = self._inner.ref

    async def embed(self, ctx: ModelCallContext, texts: Sequence[str]) -> list[list[float]]:
        if any(POISON in value for value in texts):
            raise ModelError(ModelErrorCode.MODEL_UNAVAILABLE, str(self.ref), "embedding")
        return await self._inner.embed(ctx, texts)


def use_embedder(monkeypatch: pytest.MonkeyPatch, embedder: ChunkEmbedder) -> None:
    @asynccontextmanager
    async def build(engine: AsyncEngine) -> AsyncIterator[ChunkEmbedder]:
        yield embedder

    monkeypatch.setattr(commands, "build_embedder", build)


@dataclass(frozen=True)
class Run:
    code: int
    out: list[str]
    err: str


async def run_cli(capsys: pytest.CaptureFixture[str], *argv: str) -> Run:
    capsys.readouterr()
    code = await asyncio.to_thread(cli.main, ["index", *argv])
    captured = capsys.readouterr()
    return Run(code, captured.out.splitlines(), captured.err)


async def add_ready_document(
    engine: AsyncEngine, org: OrgRows, chunk_text: str, ordinal: int = 0
) -> uuid.UUID:
    """A ready document of the org's fixture collection with one chunk of ``chunk_text``."""
    document_id = uuid.uuid4()
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        await conn.execute(
            text(
                "INSERT INTO documents (id, org_id, collection_id, folder_id, name, format,"
                " size_bytes, status, page_count, chunk_count, extracted_text, uploaded_by,"
                " file_id)"
                " VALUES (:id, :org, :collection, :folder, 'qa.txt', 'txt', 10, 'ready', 1, 1,"
                " 'qa', :user, gen_random_uuid())"
            ),
            {
                "id": document_id,
                "org": org.org_id,
                "collection": org.collection_id,
                "folder": org.folder_id,
                "user": org.user_id,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO document_chunks (org_id, document_id, ordinal, text, char_start,"
                " char_end, token_estimate) VALUES (:org, :document, :ordinal, :text, 0, 2, 1)"
            ),
            {"org": org.org_id, "document": document_id, "text": chunk_text, "ordinal": ordinal},
        )
    return document_id


async def vector_models(engine: AsyncEngine, org: OrgRows) -> set[tuple[str, str]]:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        result = await conn.execute(
            text(
                "SELECT DISTINCT model_id, model_version FROM chunk_embeddings WHERE org_id = :org"
            ),
            {"org": org.org_id},
        )
        return {(row.model_id, row.model_version) for row in result}


async def vector_rows(engine: AsyncEngine, org: OrgRows, document_id: uuid.UUID) -> list[Any]:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        result = await conn.execute(
            text(
                "SELECT id, created_at FROM chunk_embeddings"
                " WHERE org_id = :org AND document_id = :document ORDER BY id"
            ),
            {"org": org.org_id, "document": document_id},
        )
        return list(result)


async def test_reindex_document_prints_indexed_and_done(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a
    use_embedder(monkeypatch, FakeEmbedder())

    run = await run_cli(capsys, "reindex", "--org", str(a.org_id), "--document", str(a.document_id))

    assert run.code == 0
    assert run.out == [
        f"indexed: {a.document_id} vectors=1",
        "done: documents=1 vectors=1 failed=0 model=bge-m3@2026.10",
    ]


async def test_org_reindex_moves_every_vector_to_the_new_model(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = two_orgs.a, two_orgs.b
    await add_ready_document(app_engine, a, "second document")
    use_embedder(monkeypatch, FakeEmbedder(ref=NEW_REF))

    run = await run_cli(capsys, "reindex", "--org", str(a.org_id))

    assert run.code == 0
    assert run.out[-1] == "done: documents=2 vectors=2 failed=0 model=bge-m3@2099.01"
    assert await vector_models(app_engine, a) == {("bge-m3", "2099.01")}
    assert await vector_models(app_engine, b) == {("bge-m3", "2026.10")}


async def test_status_reports_stale_documents(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a
    use_embedder(monkeypatch, FakeEmbedder(ref=NEW_REF))
    org, document = str(a.org_id), str(a.document_id)

    before = await run_cli(capsys, "status", "--org", org, "--document", document)
    await run_cli(capsys, "reindex", "--org", org, "--document", document)
    after = await run_cli(capsys, "status", "--org", org, "--document", document)

    assert before.out == [
        "ready_documents=1 indexed=0 not_indexed=1 stale=1 vectors=0 model=bge-m3@2099.01"
    ]
    assert after.out == [
        "ready_documents=1 indexed=1 not_indexed=0 stale=0 vectors=1 model=bge-m3@2099.01"
    ]


async def test_status_counts_a_ready_document_without_vectors_as_not_indexed(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a
    await add_ready_document(app_engine, a, "no vector yet")
    use_embedder(monkeypatch, FakeEmbedder())

    run = await run_cli(capsys, "status", "--org", str(a.org_id))

    assert run.out == [
        "ready_documents=2 indexed=1 not_indexed=1 stale=0 vectors=1 model=bge-m3@2026.10"
    ]


async def test_reindex_command_treats_another_orgs_document_as_not_found(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = two_orgs.a, two_orgs.b
    use_embedder(monkeypatch, FakeEmbedder(ref=NEW_REF))
    before = await vector_rows(app_engine, a, a.document_id)

    reindex = await run_cli(
        capsys, "reindex", "--org", str(b.org_id), "--document", str(a.document_id)
    )
    status = await run_cli(
        capsys, "status", "--org", str(b.org_id), "--document", str(a.document_id)
    )
    unknown = await run_cli(capsys, "reindex", "--org", str(uuid.uuid4()))

    assert (reindex.code, reindex.err.strip()) == (1, "error: document not found")
    assert (status.code, status.err.strip()) == (1, "error: document not found")
    assert (unknown.code, unknown.err.strip()) == (1, "error: Organization not found")
    assert await vector_rows(app_engine, a, a.document_id) == before


async def test_reindex_continues_after_a_failed_document(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a
    bad = await add_ready_document(app_engine, a, POISON)
    good = await add_ready_document(app_engine, a, "fine text")
    use_embedder(monkeypatch, SelectiveEmbedder())

    run = await run_cli(capsys, "reindex", "--org", str(a.org_id))

    assert run.code == 1
    assert f"failed: {bad} (MODEL_UNAVAILABLE)" in run.out
    assert f"indexed: {good} vectors=1" in run.out
    assert f"indexed: {a.document_id} vectors=1" in run.out
    assert run.out[-1] == "done: documents=2 vectors=2 failed=1 model=bge-m3@2026.10"
    assert await vector_rows(app_engine, a, bad) == []


HIT = re.compile(
    r"^(\d+) distance=(\d\.\d{4}) document=([0-9a-f-]{36}) chunk=([0-9a-f-]{36}) ordinal=(\d+)"
    r" collection=([0-9a-f-]{36})$"
)


async def test_index_search_returns_own_org_hits_in_distance_order(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = two_orgs.a, two_orgs.b
    near = await add_ready_document(app_engine, a, "alpha beta")
    middle = await add_ready_document(app_engine, a, "alpha beta gamma")
    foreign = await add_ready_document(app_engine, b, "alpha beta")
    use_embedder(monkeypatch, FakeEmbedder())
    await run_cli(capsys, "reindex", "--org", str(a.org_id))
    await run_cli(capsys, "reindex", "--org", str(b.org_id))

    query = ("--query", "alpha beta")
    run = await run_cli(capsys, "search", "--org", str(a.org_id), *query, "--k", "3")
    other = await run_cli(capsys, "search", "--org", str(b.org_id), *query, "--k", "40")

    assert run.code == 0
    hits = [HIT.fullmatch(line) for line in run.out]
    assert all(hits)
    parsed = [match.groups() for match in hits if match]
    assert [row[0] for row in parsed] == ["1", "2", "3"]
    assert [row[2] for row in parsed][:2] == [str(near), str(middle)]
    assert parsed[0][1] == "0.0000"
    assert [row[1] for row in parsed] == sorted(row[1] for row in parsed)
    assert {row[4] for row in parsed} == {"0"}
    assert {row[5] for row in parsed} == {str(a.collection_id)}
    assert str(foreign) not in "\n".join(run.out)
    assert str(near) not in "\n".join(other.out) and str(middle) not in "\n".join(other.out)
    assert f"document={foreign}" in "\n".join(other.out)


async def test_index_search_filters_by_collection(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a
    use_embedder(monkeypatch, FakeEmbedder())
    await run_cli(capsys, "reindex", "--org", str(a.org_id))

    search = ("search", "--org", str(a.org_id), "--query", "qa", "--collection")
    here = await run_cli(capsys, *search, str(a.collection_id))
    elsewhere = await run_cli(capsys, *search, str(uuid.uuid4()))

    assert (here.code, len(here.out)) == (0, 1)
    assert (elsewhere.code, elsewhere.out) == (0, [])


async def test_index_search_prints_no_chunk_text(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a
    await add_ready_document(app_engine, a, f"contains {SENTINEL} inside")
    use_embedder(monkeypatch, FakeEmbedder())
    reindex = await run_cli(capsys, "reindex", "--org", str(a.org_id))

    run = await run_cli(capsys, "search", "--org", str(a.org_id), "--query", SENTINEL)

    assert run.out
    for output in (reindex.out, run.out, [reindex.err, run.err]):
        assert SENTINEL not in "\n".join(output)


async def test_index_search_prints_the_ordinal_of_the_chunk(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a
    document = await add_ready_document(app_engine, a, "ordinal probe", ordinal=7)
    use_embedder(monkeypatch, FakeEmbedder())
    await run_cli(capsys, "reindex", "--org", str(a.org_id))

    run = await run_cli(capsys, "search", "--org", str(a.org_id), "--query", "ordinal probe")

    first = HIT.fullmatch(run.out[0])
    assert first is not None
    assert (first.group(3), first.group(5)) == (str(document), "7")
