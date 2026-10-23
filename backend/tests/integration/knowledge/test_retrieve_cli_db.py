"""``ei-ai index retrieve`` on the real database (EA-36): the output contract, the simulated
principal, the scope options, tenant isolation and no text in the output.

The CLI runs its own event loop, so it is called in a thread; the embedder is the deterministic
``FakeEmbedder`` injected through ``commands.build_embedder`` (no model, no network).
"""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai import cli
from ei_ai.db.tenant import tenant_transaction
from ei_ai.knowledge.indexing import commands
from ei_ai.knowledge.indexing.embedder import ChunkEmbedder
from ei_ai.knowledge.retrieval import command
from support.fake_embedder import FakeEmbedder
from support.retrieval_corpus import (
    add_collection,
    add_folder,
    add_indexed_document,
    add_workspace,
)
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

SENTINEL = "zebracorn7q4sentinel"
QUESTION = "salary review bands"
PASSAGE = re.compile(
    r"^passage: (\d+) chunk=([0-9a-f-]{36}) document=([0-9a-f-]{36}) collection=([0-9a-f-]{36})"
    r" ordinal=(\d+) score=(-?\d\.\d{4}) rerank=-$"
)
DONE = re.compile(
    r"^done: searched=(\d+) skipped=(\d+) candidates=(\d+) passages=(\d+) retrieval=vector"
    r" rerank=(off|applied|unavailable)$"
)


@dataclass(frozen=True)
class Corpus:
    public: uuid.UUID
    authenticated: uuid.UUID
    managers: uuid.UUID
    hr: uuid.UUID
    folder_one: uuid.UUID
    other_workspace_collection: uuid.UUID


@dataclass(frozen=True)
class Run:
    code: int
    out: list[str]
    err: str


@asynccontextmanager
async def _fake_embedder(engine: AsyncEngine) -> AsyncIterator[ChunkEmbedder]:
    yield FakeEmbedder()


@asynccontextmanager
async def _no_reranker(engine: AsyncEngine) -> AsyncIterator[None]:
    yield None


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commands, "build_embedder", _fake_embedder)
    monkeypatch.setattr(command, "build_reranker", _no_reranker)


async def run_cli(capsys: pytest.CaptureFixture[str], *argv: str) -> Run:
    capsys.readouterr()
    code = await asyncio.to_thread(cli.main, ["index", *argv])
    captured = capsys.readouterr()
    return Run(code, captured.out.splitlines(), captured.err)


def retrieve_args(org: OrgRows, *extra: str, query: str = QUESTION) -> tuple[str, ...]:
    return (
        "retrieve",
        *("--org", str(org.org_id), "--workspace", str(org.workspace_id)),
        *("--query", query),
        *extra,
    )


async def build_corpus(app_engine: AsyncEngine, org: OrgRows, other: OrgRows) -> Corpus:
    embedder = FakeEmbedder()
    async with app_engine.connect() as conn, tenant_transaction(conn, org.org_id):
        public, public_folder = await add_collection(conn, org, name="P", access_level="public")
        auth, auth_folder = await add_collection(conn, org, name="A", access_level="authenticated")
        managers, managers_folder = await add_collection(
            conn, org, name="M", access_level="restricted", groups=["managers"]
        )
        hr, hr_folder = await add_collection(
            conn, org, name="H", access_level="restricted", groups=["hr"]
        )
        folder_one = await add_folder(conn, org, auth, name="f1")
        folder_two = await add_folder(conn, org, auth, name="f2")
        second = await add_workspace(conn, org, "Second")
        elsewhere, elsewhere_folder = await add_collection(
            conn, org, name="E", access_level="public", workspace_id=second
        )
        for collection, folder, chunks in (
            (public, public_folder, ["office opening hours", "salary review"]),
            (auth, auth_folder, ["annual leave days", "review bands"]),
            (auth, folder_one, ["expense claims one"]),
            (auth, folder_two, ["expense claims two"]),
            (managers, managers_folder, [f"salary review bands {SENTINEL}", "salary review bands"]),
            (hr, hr_folder, ["disciplinary process salary"]),
            (elsewhere, elsewhere_folder, ["salary review bands elsewhere"]),
        ):
            await add_indexed_document(conn, org, collection, folder, chunks, embedder=embedder)
    return Corpus(public, auth, managers, hr, folder_one, elsewhere)


@pytest.fixture
async def corpus(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> Corpus:
    return await build_corpus(app_engine, two_orgs.a, two_orgs.b)


def passages(run: Run) -> list[re.Match[str]]:
    return [m for line in run.out if (m := PASSAGE.match(line))]


def collections_of(run: Run) -> set[str]:
    return {m.group(4) for m in passages(run)}


def searched(run: Run) -> set[str]:
    return {line.removeprefix("searched: ") for line in run.out if line.startswith("searched: ")}


def skipped(run: Run) -> list[str]:
    return [line for line in run.out if line.startswith("skipped: ")]


async def test_retrieve_cli_output_lines(
    corpus: Corpus, two_orgs: TwoOrgs, capsys: pytest.CaptureFixture[str]
) -> None:
    run = await run_cli(capsys, *retrieve_args(two_orgs.a, "--as", "anonymous", "--k", "10"))

    assert run.code == 0
    assert run.err == ""
    assert run.out[0] == "principal: anonymous groups=0 simulated=yes"
    assert collections_of(run) == {str(corpus.public)}
    assert searched(run) == {str(corpus.public)}
    assert {
        f"skipped: {c} kind=collection reason=no_access"
        for c in (corpus.authenticated, corpus.managers, corpus.hr)
    } <= set(skipped(run))
    rows = passages(run)
    assert [int(m.group(1)) for m in rows] == list(range(1, len(rows) + 1))
    scores = [float(m.group(6)) for m in rows]
    assert scores == sorted(scores, reverse=True)
    done = DONE.match(run.out[-1])
    assert done is not None
    assert done.groups() == ("1", str(len(skipped(run))), str(len(rows)), str(len(rows)), "off")


async def test_retrieve_cli_managers_sees_manager_handbook(
    corpus: Corpus, two_orgs: TwoOrgs, capsys: pytest.CaptureFixture[str]
) -> None:
    member = await run_cli(capsys, *retrieve_args(two_orgs.a, "--as", "authenticated", "--k", "10"))
    managers = await run_cli(
        capsys,
        *retrieve_args(two_orgs.a, "--as", "authenticated", "--group", "Managers", "--k", "10"),
    )

    assert str(corpus.managers) not in collections_of(member)
    assert f"skipped: {corpus.managers} kind=collection reason=no_access" in member.out
    assert str(corpus.hr) not in collections_of(member)
    assert managers.out[0] == "principal: authenticated groups=1 simulated=yes"
    assert str(corpus.managers) in collections_of(managers)
    assert str(corpus.hr) not in collections_of(managers)


async def test_retrieve_cli_default_scope_is_whole_workspace(
    corpus: Corpus, two_orgs: TwoOrgs, capsys: pytest.CaptureFixture[str]
) -> None:
    run = await run_cli(capsys, *retrieve_args(two_orgs.a, "--as", "authenticated"))

    listed = searched(run) | {line.split()[1] for line in skipped(run)}
    assert run.code == 0
    assert {
        str(corpus.public),
        str(corpus.authenticated),
        str(corpus.managers),
        str(corpus.hr),
    } <= listed


async def test_retrieve_cli_folder_scope(
    corpus: Corpus, two_orgs: TwoOrgs, capsys: pytest.CaptureFixture[str]
) -> None:
    run = await run_cli(
        capsys,
        *retrieve_args(
            two_orgs.a,
            *("--as", "authenticated", "--folder", str(corpus.folder_one), "--k", "10"),
            query="expense claims",
        ),
    )

    assert run.code == 0
    assert searched(run) == {str(corpus.authenticated)}
    assert len(passages(run)) == 1


async def test_retrieve_cli_unknown_and_foreign_ids_look_the_same(
    corpus: Corpus, two_orgs: TwoOrgs, capsys: pytest.CaptureFixture[str]
) -> None:
    unknown = uuid.uuid4()
    run = await run_cli(
        capsys,
        *retrieve_args(
            two_orgs.a,
            *("--as", "authenticated"),
            *("--collection", str(unknown)),
            *("--collection", str(corpus.other_workspace_collection)),
            *("--collection", str(two_orgs.b.collection_id)),
            *("--folder", str(two_orgs.b.folder_id)),
        ),
    )

    assert run.code == 0
    assert skipped(run) == [
        f"skipped: {i} kind=collection reason=not_found"
        for i in (unknown, corpus.other_workspace_collection, two_orgs.b.collection_id)
    ] + [f"skipped: {two_orgs.b.folder_id} kind=folder reason=not_found"]
    assert run.out[-1] == (
        "done: searched=0 skipped=4 candidates=0 passages=0 retrieval=vector rerank=off"
    )


@pytest.mark.isolation
async def test_retrieve_cli_other_orgs_workspace_is_not_found(
    corpus: Corpus, two_orgs: TwoOrgs, capsys: pytest.CaptureFixture[str]
) -> None:
    run = await run_cli(
        capsys,
        "retrieve",
        *("--org", str(two_orgs.b.org_id), "--workspace", str(two_orgs.a.workspace_id)),
        *("--query", QUESTION, "--as", "authenticated"),
    )

    assert run.code == 1
    assert run.err.strip() == "error: workspace not found"
    assert run.out == []


async def test_retrieve_cli_unknown_org(capsys: pytest.CaptureFixture[str]) -> None:
    run = await run_cli(
        capsys,
        "retrieve",
        *("--org", str(uuid.uuid4()), "--workspace", str(uuid.uuid4())),
        *("--query", QUESTION, "--as", "anonymous"),
    )

    assert run.code == 1
    assert run.err.strip() == "error: Organization not found"


async def test_retrieve_cli_prints_no_chunk_text(
    corpus: Corpus, two_orgs: TwoOrgs, capsys: pytest.CaptureFixture[str]
) -> None:
    for extra in (("--group", "managers"), ()):
        run = await run_cli(
            capsys,
            *retrieve_args(
                two_orgs.a,
                *("--as", "authenticated", *extra, "--k", "10"),
                query=f"{QUESTION} {SENTINEL}",
            ),
        )

        assert run.code == 0
        everything = "\n".join(run.out) + run.err
        assert SENTINEL not in everything
        assert "salary" not in everything.lower()


async def test_retrieve_cli_bad_rerank_setting(
    corpus: Corpus,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.undo()  # drop the fakes, then keep only the embedder
    monkeypatch.setattr(commands, "build_embedder", _fake_embedder)
    monkeypatch.setenv("RERANK_MODEL_REF", "bge-m3@2026.10")

    run = await run_cli(capsys, *retrieve_args(two_orgs.a, "--as", "anonymous"))

    assert run.code == 1
    assert run.err.strip() == (
        "configuration error: RERANK_MODEL_REF must name a local rerank model of the platform"
        " manifest"
    )
    assert run.out == []
