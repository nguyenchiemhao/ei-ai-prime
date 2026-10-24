"""EA-37: ``POST /workspaces/{id}/collections/{id}/ask`` on the real database with scripted models
(AC1-AC4, AC6, AC7 through the API): frames, headers, streaming, checks, errors, no writes."""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncGenerator, Mapping, Sequence
from types import SimpleNamespace
from typing import Any, cast

import httpx
import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.results import ChatMessage, StreamEvent
from ei_ai.vectors.partitions import create_vector_partition
from support.answer_questions import AnswerCorpus, build_answer_corpus
from support.fake_answer_model import FakeAnswerModel
from support.fake_embedder import FakeEmbedder
from support.rbac.orgs import RoleOrg, role_app, role_client
from support.sign_in import in_tenant
from support.tenants import OrgRows

from ..knowledge.conftest import PEOPLE, MakeOrg

pytestmark = pytest.mark.integration

QUESTION = "How many days of paid leave do employees get when they marry?"
AUTHENTICATED = {"kind": "authenticated", "groups": []}
ASK_PEOPLE = {**PEOPLE, "reviewer": (None, {"x": "reviewer"})}

Frame = tuple[str, dict[str, Any]]


async def _org_with_corpus(
    app_engine: AsyncEngine, make_org: MakeOrg, embedder: FakeEmbedder
) -> tuple[RoleOrg, AnswerCorpus]:
    """A role Organization with its vector partition and the three indexed fixture collections."""
    org: RoleOrg = await make_org(ASK_PEOPLE)
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"], autocommit=True) as migrator:
        create_vector_partition(migrator, org.org_id)
    rows = cast(
        OrgRows,
        SimpleNamespace(org_id=org.org_id, workspace_id=org.workspace("x"), user_id=org.user("ke")),
    )
    async with app_engine.connect() as conn, tenant_transaction(conn, org.org_id):
        corpus = await build_answer_corpus(conn, rows, embedder)
    return org, corpus


def _url(org: RoleOrg, collection_id: uuid.UUID | str) -> str:
    return f"/workspaces/{org.workspace('x')}/collections/{collection_id}/ask"


def _body(question: str = QUESTION, **principal: object) -> dict[str, object]:
    return {"question": question, "principal": {**AUTHENTICATED, **principal}}


def _frames(text: str) -> list[Frame]:
    frames: list[Frame] = []
    for block in text.split("\n\n"):
        if not block:
            continue
        name, data = block.split("\n")
        assert name.startswith("event: ") and data.startswith("data: "), block
        frames.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return frames


async def _ask(
    client: httpx.AsyncClient,
    org: RoleOrg,
    collection_id: uuid.UUID | str,
    body: object,
    actor: str,
) -> httpx.Response:
    return await client.post(_url(org, collection_id), headers=org.headers(actor), json=body)


async def test_ask_streams_passages_deltas_done(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    embedder, model = FakeEmbedder(), FakeAnswerModel()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)

    async with role_client(app_engine, org, embedder=embedder, answer_model=model) as client:
        response = await _ask(client, org, corpus.collections["authenticated"], _body(), "ke")

    assert response.status_code == 200
    frames = _frames(response.text)
    names = [name for name, _ in frames]
    assert names[0] == "passages" and names[-1] == "done"
    assert names[1:-1] and set(names[1:-1]) == {"delta"}
    passages = frames[0][1]["passages"]
    assert frames[0][1]["language"] == "en"
    assert 1 <= len(passages) <= 3
    for passage in passages:
        assert set(passage) == {"number", "title", "section", "page", "score"}
        assert passage["title"] == "Leave Policy 2026"
        assert isinstance(passage["score"], float)
    assert [p["number"] for p in passages] == list(range(1, len(passages) + 1))
    done = frames[-1][1]
    assert done["outcome"] == "answered"
    assert done["citations"] == [1]
    assert set(done["citations"]) <= {p["number"] for p in passages}
    assert "".join(data["text"] for name, data in frames if name == "delta") == done["answer"]
    assert len(model.calls) == 1


async def test_ask_stream_headers(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    embedder = FakeEmbedder()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)

    async with role_client(
        app_engine, org, embedder=embedder, answer_model=FakeAnswerModel()
    ) as client:
        response = await _ask(client, org, corpus.collections["authenticated"], _body(), "ke")

    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"


async def _raw_post(
    app: Any, path: str, headers: Mapping[str, str], body: object, on_chunk: Any
) -> None:
    """Drive the ASGI app directly: ``httpx`` collects a whole response before it returns, which
    cannot show what the client sees while the model is still running."""
    payload = json.dumps(body).encode()
    sent = False
    never = asyncio.Event()

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await never.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body":
            on_chunk(message.get("body", b"").decode())

    raw_headers = [(b"host", b"test"), (b"content-type", b"application/json")]
    raw_headers += [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": raw_headers,
        "server": ("test", 80),
        "client": ("127.0.0.1", 1),
    }
    await app(scope, receive, send)


async def test_first_delta_reaches_client_before_model_finishes(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    embedder = FakeEmbedder()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)
    gate = asyncio.Event()
    model = FakeAnswerModel(deltas=("Nghỉ 3 ngày ", "[1]", "."), gate=gate, gate_after=1)
    app = role_app(app_engine, [org], embedder=embedder, answer_model=model)
    received: list[str] = []
    first_delta = asyncio.Event()

    def on_chunk(chunk: str) -> None:
        received.append(chunk)
        if "event: delta" in chunk:
            first_delta.set()

    # The model pauses after its first delta; the client must hold ``passages`` and that delta
    # while the model is still running.
    task = asyncio.create_task(
        _raw_post(
            app,
            _url(org, corpus.collections["authenticated"]),
            org.headers("ke"),
            _body(),
            on_chunk,
        )
    )
    async with asyncio.timeout(20):
        await first_delta.wait()
    assert not task.done()
    assert any("event: passages" in chunk for chunk in received)
    assert not any("event: done" in chunk for chunk in received)
    gate.set()
    async with asyncio.timeout(20):
        await task
    assert first_delta.is_set()
    names = [name for name, _ in _frames("".join(received))]
    assert names[0] == "passages" and names[-1] == "done"


async def test_ask_as_anonymous_on_authenticated_collection_finds_no_passages(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    embedder, model = FakeEmbedder(), FakeAnswerModel()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)

    async with role_client(app_engine, org, embedder=embedder, answer_model=model) as client:
        response = await _ask(
            client,
            org,
            corpus.collections["authenticated"],
            {"question": QUESTION, "principal": {"kind": "anonymous"}},
            "ke",
        )

    assert response.status_code == 200
    frames = _frames(response.text)
    assert frames[0] == ("passages", {"language": "en", "passages": []})
    assert frames[-1] == ("done", {"outcome": "not_found", "answer": "", "citations": []})
    assert model.calls == []


async def test_ask_other_org_collection_is_not_found_like_unknown(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    embedder, model = FakeEmbedder(), FakeAnswerModel()
    org, _ = await _org_with_corpus(app_engine, make_org, embedder)
    other, other_corpus = await _org_with_corpus(app_engine, make_org, embedder)
    embedder.calls.clear()

    async with role_client(app_engine, org, other, embedder=embedder, answer_model=model) as client:
        foreign = await _ask(client, org, other_corpus.collections["public"], _body(), "ke")
        unknown = await _ask(client, org, uuid.uuid4(), _body(), "ke")

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == {"detail": "not_found"}
    assert foreign.content == unknown.content
    assert model.calls == [] and embedder.calls == []


async def test_ask_collection_of_another_workspace_is_not_found(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    embedder, model = FakeEmbedder(), FakeAnswerModel()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)
    people = {"ws_admin": org.headers("ws_admin")}  # a member of both Workspaces x and y
    foreign = f"/workspaces/{org.workspace('y')}/collections/{corpus.collections['public']}/ask"
    unknown = f"/workspaces/{org.workspace('y')}/collections/{uuid.uuid4()}/ask"

    async with role_client(app_engine, org, embedder=embedder, answer_model=model) as client:
        other = await client.post(foreign, headers=people["ws_admin"], json=_body())
        missing = await client.post(unknown, headers=people["ws_admin"], json=_body())

    assert other.status_code == missing.status_code == 404
    assert other.json() == {"detail": "not_found"}
    assert other.content == missing.content
    assert model.calls == []


@pytest.mark.parametrize(
    "extra",
    [
        {"org_id": str(uuid.uuid4())},
        {"user_id": str(uuid.uuid4())},
        {"workspace_id": str(uuid.uuid4())},
    ],
)
async def test_ask_rejects_identity_fields(
    extra: dict[str, str], app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    embedder, model = FakeEmbedder(), FakeAnswerModel()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)
    collection = corpus.collections["public"]

    async with role_client(app_engine, org, embedder=embedder, answer_model=model) as client:
        top = await _ask(client, org, collection, {**_body(), **extra}, "ke")
        inner = await _ask(client, org, collection, _body(**extra), "ke")
        anonymous = await _ask(
            client,
            org,
            collection,
            {"question": QUESTION, "principal": {"kind": "anonymous", "groups": ["managers"]}},
            "ke",
        )

    for response in (top, inner, anonymous):
        assert response.status_code == 422
        assert response.json() == {"detail": "invalid_request"}
    assert model.calls == []


async def test_ask_forbidden_for_viewer_and_reviewer(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    embedder, model = FakeEmbedder(), FakeAnswerModel()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)

    async with role_client(app_engine, org, embedder=embedder, answer_model=model) as client:
        collection = corpus.collections["public"]
        responses = [await _ask(client, org, collection, _body(), "viewer")]
        reviewer = org.headers("reviewer")
        # A Reviewer sees the Workspace but has no Knowledge permission: same answer as a Viewer.
        responses.append(await client.post(_url(org, collection), headers=reviewer, json=_body()))
        anonymous = await client.post(_url(org, collection), json=_body())

    for response in responses:
        assert response.status_code == 403
        assert response.json() == {"detail": "forbidden"}
    assert anonymous.status_code == 401
    assert anonymous.json() == {"detail": "unauthenticated"}
    assert model.calls == []


async def test_ask_check_order(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    embedder, model = FakeEmbedder(), FakeAnswerModel()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)
    bad = {"question": "", "principal": AUTHENTICATED}

    async with role_client(app_engine, org, embedder=embedder, answer_model=model) as client:
        viewer = await _ask(client, org, corpus.collections["public"], bad, "viewer")
        unknown = await _ask(client, org, uuid.uuid4(), bad, "ke")
        bad_group = await _ask(client, org, uuid.uuid4(), _body(groups=["a" * 65]), "ke")
        unknown_ok = await _ask(client, org, uuid.uuid4(), _body(), "ke")

    assert (viewer.status_code, viewer.json()) == (403, {"detail": "forbidden"})
    assert (unknown.status_code, unknown.json()) == (422, {"detail": "invalid_request"})
    assert (bad_group.status_code, bad_group.json()) == (422, {"detail": "invalid_group"})
    assert (unknown_ok.status_code, unknown_ok.json()) == (404, {"detail": "not_found"})


async def test_ask_check_order_models_after_collection(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org, corpus = await _org_with_corpus(app_engine, make_org, FakeEmbedder())

    async with role_client(app_engine, org) as client:
        unknown = await _ask(client, org, uuid.uuid4(), _body(), "ke")
        known = await _ask(client, org, corpus.collections["public"], _body(), "ke")

    assert (unknown.status_code, unknown.json()) == (404, {"detail": "not_found"})
    assert (known.status_code, known.json()) == (503, {"detail": "model_unavailable"})


@pytest.mark.parametrize(
    "body",
    [
        {"question": QUESTION},
        {"question": QUESTION, "principal": None},
        {"principal": AUTHENTICATED},
        {"question": "   ", "principal": AUTHENTICATED},
        {"question": "x" * 2001, "principal": AUTHENTICATED},
        {"question": QUESTION, "principal": {"groups": []}},
        {"question": QUESTION, "principal": {"kind": "admin"}},
    ],
)
async def test_ask_requires_principal(
    body: dict[str, object], app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    embedder, model = FakeEmbedder(), FakeAnswerModel()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)

    async with role_client(app_engine, org, embedder=embedder, answer_model=model) as client:
        response = await _ask(client, org, corpus.collections["public"], body, "ke")

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request"}
    assert model.calls == []


async def test_ask_group_limits(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    embedder, model = FakeEmbedder(), FakeAnswerModel()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)
    collection = corpus.collections["public"]

    async with role_client(app_engine, org, embedder=embedder, answer_model=model) as client:
        hundred = await _ask(
            client, org, collection, _body(groups=[f"g{n}" for n in range(100)]), "ke"
        )
        too_many = await _ask(
            client, org, collection, _body(groups=[f"g{n}" for n in range(101)]), "ke"
        )
        padded = await _ask(client, org, collection, _body(groups=["g1"] * 101), "ke")
        long_name = await _ask(client, org, collection, _body(groups=["g" * 65]), "ke")
        comma = await _ask(client, org, collection, _body(groups=["a,b"]), "ke")

    assert hundred.status_code == 200
    # More than 100 items is refused before normalising, even when they repeat one name.
    for response in (too_many, padded, long_name, comma):
        assert response.status_code == 422
        assert response.json() == {"detail": "invalid_group"}


async def test_ask_embedding_failure_is_503(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org, corpus = await _org_with_corpus(app_engine, make_org, FakeEmbedder())
    down = FakeEmbedder(fail=ModelError(ModelErrorCode.MODEL_UNAVAILABLE, "bge-m3@2026.10"))
    model = FakeAnswerModel()

    async with role_client(app_engine, org, embedder=down, answer_model=model) as client:
        failed = await _ask(client, org, corpus.collections["public"], _body(), "ke")
    async with role_client(app_engine, org, embedder=FakeEmbedder()) as client:
        no_model = await _ask(client, org, corpus.collections["public"], _body(), "ke")

    for response in (failed, no_model):
        assert response.status_code == 503
        assert response.json() == {"detail": "model_unavailable"}
    assert model.calls == []


async def test_ask_error_frame_has_code_only(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    embedder = FakeEmbedder()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)
    secret_ref = "secret-chat-model@9.9"
    model = FakeAnswerModel(
        deltas=(), fail=ModelError(ModelErrorCode.MODEL_UNAVAILABLE, secret_ref)
    )

    async with role_client(app_engine, org, embedder=embedder, answer_model=model) as client:
        response = await _ask(client, org, corpus.collections["authenticated"], _body(), "ke")

    assert response.status_code == 200
    frames = _frames(response.text)
    assert [name for name, _ in frames] == ["passages", "error"]
    assert frames[-1][1] == {"code": "model_unavailable"}
    for forbidden in (secret_ref, "Traceback", "ModelError", "MODEL_UNAVAILABLE"):
        assert forbidden not in response.text


async def test_ask_writes_no_rows(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    embedder = FakeEmbedder()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)
    tables = [
        row[0]
        for row in await in_tenant(
            app_engine,
            org.org_id,
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relrowsecurity AND c.relkind IN ('r', 'p') AND n.nspname = 'public'"
            " AND NOT c.relispartition ORDER BY c.relname",
        )
    ]
    assert "audit_events" in tables and "document_chunks" in tables

    async def counts() -> dict[str, int]:
        found: dict[str, int] = {}
        for table in tables:
            rows = await in_tenant(app_engine, org.org_id, f'SELECT count(*) FROM "{table}"')
            found[table] = rows[0][0]
        return found

    before = await counts()
    async with role_client(
        app_engine, org, embedder=embedder, answer_model=FakeAnswerModel()
    ) as client:
        response = await _ask(client, org, corpus.collections["authenticated"], _body(), "ke")
    assert response.status_code == 200

    assert await counts() == before


async def test_ask_uses_the_tenant_of_the_session_for_the_model_call(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    """The model context and the prepared answer name the same Organization (D46)."""
    seen: list[uuid.UUID] = []

    class Spy(FakeAnswerModel):
        def stream(
            self,
            ctx: ModelCallContext,
            messages: Sequence[ChatMessage],
            *,
            temperature: float | None = None,
            max_tokens: int | None = None,
        ) -> AsyncGenerator[StreamEvent]:
            seen.append(ctx.org_id)
            return super().stream(ctx, messages, temperature=temperature, max_tokens=max_tokens)

    embedder = FakeEmbedder()
    org, corpus = await _org_with_corpus(app_engine, make_org, embedder)

    async with role_client(app_engine, org, embedder=embedder, answer_model=Spy()) as client:
        response = await _ask(client, org, corpus.collections["authenticated"], _body(), "ke")

    assert response.status_code == 200
    assert seen == [org.org_id]
