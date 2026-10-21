"""``ei-ai model add`` and ``ei-ai model try`` against the real database (EA-24 AC1, AC7).

The CLI runs its own event loop with ``asyncio.run``, so it is called in a worker thread.
"""

import asyncio
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai import cli
from ei_ai.db.tenant import tenant_transaction
from support.fake_model_server import (
    FakeModelServer,
    running_fake_model_server,
    unused_loopback_url,
)
from support.tenants import TwoOrgs

pytestmark = pytest.mark.integration

QWEN = "qwen3-4b-instruct-2507@2026.10"
KNOWN = "bge-m3@2026.10, bge-reranker-v2-m3@2026.10, qwen3-4b-instruct-2507@2026.10"


async def _run(*argv: str) -> int:
    return await asyncio.to_thread(cli.main, list(argv))


async def _rows(engine: AsyncEngine, org: uuid.UUID, sql: str) -> list[tuple[Any, ...]]:
    async with engine.connect() as conn, tenant_transaction(conn, org):
        return [tuple(row) for row in await conn.execute(text(sql), {"org": org})]


async def _model_rows(engine: AsyncEngine, org: uuid.UUID) -> list[tuple[Any, ...]]:
    return await _rows(
        engine,
        org,
        "SELECT id, kind, display_name, model_id, version, digest, source_revision, deployment,"
        " provider, vietnamese_quality, vietnamese_quality_measured, tool_use, context_window,"
        " speed, status, retirement_date FROM model_catalog"
        " WHERE org_id = :org AND model_id <> 'fixture-chat' ORDER BY model_id",
    )


async def _model_events(engine: AsyncEngine, org: uuid.UUID) -> list[tuple[Any, ...]]:
    return await _rows(
        engine,
        org,
        "SELECT actor, action, target_type, target_id FROM audit_events"
        " WHERE org_id = :org AND target_type = 'model'",
    )


async def test_model_add_inserts_the_manifest_row_and_one_audit_event(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, capsys: pytest.CaptureFixture[str]
) -> None:
    org = two_orgs.a.org_id

    code = await _run("model", "add", "--org", str(org), "--model", QWEN)

    assert code == 0
    assert capsys.readouterr().out == f"added: {QWEN} (chat, local)\n"
    rows = await _model_rows(app_engine, org)
    assert [row[1:] for row in rows] == [
        (
            "chat",
            "Qwen3 4B Instruct 2507",
            "qwen3-4b-instruct-2507",
            "2026.10",
            "sha256:3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597",
            "unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b655725eafa393f4a9745d460374c9"
            "/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
            "local",
            "local-chat",
            None,
            False,
            True,
            8192,
            None,
            "available",
            None,
        )
    ]
    assert await _model_events(app_engine, org) == [
        ("platform-operator", "model.catalog_entry_added", "model", rows[0][0])
    ]


async def test_model_add_twice_is_already_present_and_audited_once(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, capsys: pytest.CaptureFixture[str]
) -> None:
    org = two_orgs.a.org_id
    await _run("model", "add", "--org", str(org), "--model", "bge-m3@2026.10")
    capsys.readouterr()

    code = await _run("model", "add", "--org", str(org), "--model", "bge-m3@2026.10")

    assert code == 0
    assert capsys.readouterr().out == "already present: bge-m3@2026.10\n"
    assert len(await _model_rows(app_engine, org)) == 1
    assert len(await _model_events(app_engine, org)) == 1


async def test_model_add_writes_only_to_the_given_org(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    await _run("model", "add", "--org", str(two_orgs.a.org_id), "--model", QWEN)

    assert await _model_rows(app_engine, two_orgs.b.org_id) == []
    assert await _model_events(app_engine, two_orgs.b.org_id) == []


async def test_model_add_for_an_unknown_organization_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = await _run("model", "add", "--org", str(uuid.uuid4()), "--model", QWEN)

    assert code == 1
    assert capsys.readouterr().err == "error: Organization not found\n"


async def test_model_add_of_a_model_outside_the_manifest_exits_1(
    two_orgs: TwoOrgs, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await _run(
        "model", "add", "--org", str(two_orgs.a.org_id), "--model", "gpt-4.1-2025-04-14@2025.04"
    )

    assert code == 1
    assert capsys.readouterr().err == (
        f"error: unknown model gpt-4.1-2025-04-14@2025.04; known: {KNOWN}\n"
    )


DONE = re.compile(
    r"^done: model=qwen3-4b-instruct-2507@2026\.10 digest=sha256:3605803b982c prompt_tokens=7"
    r" completion_tokens=2 attempts=1 first_token_ms=(\d+) total_ms=(\d+)$"
)


@pytest.fixture
def local_server() -> Iterator[FakeModelServer]:
    yield from running_fake_model_server()


async def _ei_ai(*argv: str, **env: str) -> subprocess.CompletedProcess[str]:
    """The real ``ei-ai`` in a child process: stderr has no pytest logging handlers."""
    executable = shutil.which("ei-ai")
    assert executable is not None
    return await asyncio.to_thread(
        subprocess.run,
        [executable, *argv],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=60,
        check=False,
    )


async def test_model_try_streams_from_fake_server_and_prints_done_line(
    two_orgs: TwoOrgs, local_server: FakeModelServer
) -> None:
    org = str(two_orgs.a.org_id)
    local_server.listed_ids = ["qwen3-4b-instruct-2507@sha256-3605803b982c"]
    await _run("model", "add", "--org", org, "--model", QWEN)

    result = await _ei_ai(
        "model", "try", "--org", org, "--model", QWEN, MODEL_LOCAL_BASE_URL=local_server.base_url
    )

    assert (result.returncode, result.stderr) == (0, "")
    text, _, last = result.stdout.rstrip("\n").rpartition("\n")
    assert text == "Xin chào"
    match = DONE.match(last)
    assert match is not None, last
    assert int(match.group(1)) <= int(match.group(2))
    body = local_server.requests[-1].body
    assert body["messages"] == [
        {"role": "user", "content": "Xin chào, hãy giới thiệu ngắn gọn về bạn."}
    ]
    assert body["max_tokens"] == 64


async def test_model_try_unreachable_server_is_model_unavailable_with_one_stderr_line(
    two_orgs: TwoOrgs,
) -> None:
    org = str(two_orgs.a.org_id)
    await _run("model", "add", "--org", org, "--model", QWEN)

    result = await _ei_ai(
        "model", "try", "--org", org, "--model", QWEN, MODEL_LOCAL_BASE_URL=unused_loopback_url()
    )

    assert result.returncode == 1
    assert result.stderr == f"error: MODEL_UNAVAILABLE: model {QWEN} is unavailable\n"
    assert result.stdout == ""


async def test_model_try_of_a_cloud_row_with_the_switch_off_is_blocked_and_audited(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        cloud_id = (
            await conn.execute(
                text(
                    "INSERT INTO model_catalog (org_id, kind, display_name, model_id, version,"
                    " deployment, provider) VALUES (:org, 'chat', 'QA cloud',"
                    " 'gpt-4.1-2025-04-14', '2025.04', 'cloud', 'openai') RETURNING id"
                ),
                {"org": a.org_id},
            )
        ).scalar_one()

    result = await _ei_ai(
        "model", "try", "--org", str(a.org_id), "--model", "gpt-4.1-2025-04-14@2025.04"
    )

    assert result.returncode == 1
    assert result.stderr == "error: CLOUD_DISABLED: cloud models are off for this Organization\n"
    assert await _model_events(app_engine, a.org_id) == [
        ("platform-operator", "model.cloud_call_blocked", "model", cloud_id)
    ]
    assert await _model_events(app_engine, two_orgs.b.org_id) == []


async def test_model_try_for_an_unknown_organization_exits_1() -> None:
    result = await _ei_ai("model", "try", "--org", str(uuid.uuid4()), "--model", QWEN)

    assert (result.returncode, result.stderr) == (1, "error: Organization not found\n")


async def test_model_try_of_a_ref_missing_from_the_catalog_is_model_not_found(
    two_orgs: TwoOrgs,
) -> None:
    result = await _ei_ai("model", "try", "--org", str(two_orgs.a.org_id), "--model", QWEN)

    assert result.returncode == 1
    assert result.stderr == (
        f"error: MODEL_NOT_FOUND: no chat model {QWEN} in this Organization's catalog\n"
    )
