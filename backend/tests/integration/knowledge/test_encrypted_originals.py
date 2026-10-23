"""Stored originals are encrypted per Organization and never cross to another one (EA-33 Task 7).

Through the production routes and the real ingestion runner, with ``OrgFileStore`` at
``tmp_path``. The file id of a document comes only from its own row and the path only from the
verified Organization, so a row of A can name only a file under ``<root>/<A>/``.
"""

import shutil
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.crypto.lifecycle import destroy_org_key
from ei_ai.db.tenant import tenant_transaction
from ei_ai.jobs.envelope import JobEnvelope
from ei_ai.knowledge.ingestion.runner import IngestionRunner
from support.isolation.client import RecordingRunner
from support.rbac.orgs import PersonSpec, RoleOrg, role_app
from support.sign_in import in_tenant

from .conftest import MakeOrg, document_file_id, file_store

pytestmark = [pytest.mark.integration, pytest.mark.isolation]

PEOPLE: Mapping[str, PersonSpec] = {"ke": (None, {"x": "knowledge_editor"})}
WINDOW = 32
MARKER = b"qa-EA33-T7-disk-marker-" + uuid.uuid4().hex.encode() + b"-" + b"m" * 8
assert len(MARKER) == 64


@dataclass(frozen=True)
class Side:
    org: RoleOrg
    collection_id: str
    folder_id: str

    @property
    def base(self) -> str:
        return f"/workspaces/{self.org.workspace('x')}/collections/{self.collection_id}"


@dataclass
class Pair:
    client: httpx.AsyncClient
    app: FastAPI
    engine: AsyncEngine
    root: Path
    runner: IngestionRunner
    a: Side
    b: Side

    async def upload(self, side: Side, name: str, data: bytes) -> str:
        """Upload through the route; the job runs only when ``run`` is called (returns the id)."""
        response = await self.client.post(
            f"{side.base}/folders/{side.folder_id}/documents",
            headers={
                **side.org.headers("ke"),
                "X-File-Name": quote(name, safe=""),
                "Content-Type": "application/octet-stream",
            },
            content=data,
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    async def run_jobs(self) -> None:
        """Run the recorded jobs on the real runner and wait for them."""
        recorder = self.app.state.ingestion_runner
        assert isinstance(recorder, RecordingRunner)
        envelopes: list[JobEnvelope] = list(recorder.submitted)
        recorder.submitted.clear()
        for envelope in envelopes:
            self.runner.submit(envelope)
        await self.runner.drain()

    async def document(self, side: Side, document_id: str) -> dict[str, object]:
        response = await self.client.get(f"{side.base}/documents", headers=side.org.headers("ke"))
        assert response.status_code == 200, response.text
        found = [d for d in response.json()["documents"] if d["id"] == document_id]
        assert len(found) == 1
        return dict(found[0])

    async def original(self, side: Side, document_id: str) -> Path:
        file_id = await document_file_id(self.engine, side.org.org_id, uuid.UUID(document_id))
        assert file_id is not None
        return self.root / str(side.org.org_id) / f"{file_id}.bin"

    def files(self) -> list[Path]:
        return sorted(path for path in self.root.rglob("*") if path.is_file())


async def _side(client: httpx.AsyncClient, org: RoleOrg) -> Side:
    base = f"/workspaces/{org.workspace('x')}/collections"
    created = await client.post(
        base,
        headers=org.headers("ke"),
        json={"name": "Handbook", "access_level": "authenticated"},
    )
    assert created.status_code == 201, created.text
    collection_id = created.json()["id"]
    folder = await client.post(
        f"{base}/{collection_id}/folders", headers=org.headers("ke"), json={"name": "Policies"}
    )
    assert folder.status_code == 201, folder.text
    return Side(org, collection_id, folder.json()["id"])


@pytest.fixture
async def pair(app_engine: AsyncEngine, make_org: MakeOrg, tmp_path: Path) -> AsyncIterator[Pair]:
    """Organizations A and B on one app. Uploads only record their job; ``run_jobs`` runs them
    on the real runner, so a test can change state before a job runs."""
    a_org = await make_org(PEOPLE, ("x",))
    b_org = await make_org(PEOPLE, ("x",))
    app = role_app(app_engine, [a_org, b_org], file_store=file_store(tmp_path))
    real_runner = app.state.ingestion_runner
    app.state.ingestion_runner = RecordingRunner()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        try:
            a = await _side(client, a_org)
            b = await _side(client, b_org)
            yield Pair(client, app, app_engine, tmp_path, real_runner, a, b)
        finally:
            await real_runner.close()


def _contains_plaintext_window(raw: bytes, plaintext: bytes) -> bool:
    """True when ``raw`` holds any 32-byte window of the plaintext (a boolean, so a failing
    assertion never prints plaintext)."""
    return any(
        plaintext[i : i + WINDOW] in raw for i in range(0, max(len(plaintext) - WINDOW, 0) + 1)
    )


async def _ready_b_document(pair: Pair) -> tuple[str, Path, bytes]:
    """A ready document of B: its id, its stored file and that file's bytes."""
    document_id = await pair.upload(pair.b, "b.txt", b"Text of Organization B. " * 10)
    await pair.run_jobs()
    assert (await pair.document(pair.b, document_id))["status"] == "ready"
    path = await pair.original(pair.b, document_id)
    return document_id, path, path.read_bytes()


async def test_upload_stores_ciphertext_under_own_org(pair: Pair) -> None:
    env = pair
    plaintext = MARKER + b"\n" + MARKER * 3 + b"\nEnd of the uploaded text.\n"

    document_id = await env.upload(env.a, "disk.txt", plaintext)
    await env.run_jobs()

    stored = await env.original(env.a, document_id)
    raw = stored.read_bytes()
    assert env.files() == [stored]
    assert stored.parent == env.root / str(env.a.org.org_id)
    assert raw.startswith(b"EIA\x01")
    assert len(raw) == len(plaintext) + 32
    leaked = [p for p in env.files() if _contains_plaintext_window(p.read_bytes(), plaintext)]
    assert leaked == [], "plaintext found on disk"
    assert not (env.root / str(env.b.org.org_id)).exists()
    assert (await env.document(env.a, document_id))["status"] == "ready"


@pytest.mark.parametrize("forgery", ["row_names_b_file", "b_blob_copied_into_a"])
async def test_job_with_foreign_file_id_fails_without_touching_other_org(
    pair: Pair, forgery: str
) -> None:
    env = pair
    b_id, b_path, b_bytes = await _ready_b_document(env)
    b_before = await env.document(env.b, b_id)
    a_id = await env.upload(env.a, "a.txt", b"Text of Organization A. " * 10)
    if forgery == "row_names_b_file":
        await in_tenant(
            env.engine,
            env.a.org.org_id,
            "UPDATE documents SET file_id = :file WHERE org_id = :org AND id = :id",
            {"file": uuid.UUID(b_path.stem), "id": uuid.UUID(a_id)},
        )
    else:
        shutil.copyfile(b_path, await env.original(env.a, a_id))

    await env.run_jobs()

    a_after = await env.document(env.a, a_id)
    assert (a_after["status"], a_after["reason"]) == ("failed", "processing_error")
    assert b_path.read_bytes() == b_bytes
    assert await env.document(env.b, b_id) == b_before


async def test_remove_with_foreign_file_id_keeps_other_org_file(
    pair: Pair,
) -> None:
    env = pair
    _, b_path, b_bytes = await _ready_b_document(env)
    a_id = await env.upload(env.a, "a.txt", b"Text of Organization A.")
    await in_tenant(
        env.engine,
        env.a.org.org_id,
        "UPDATE documents SET file_id = :file WHERE org_id = :org AND id = :id",
        {"file": uuid.UUID(b_path.stem), "id": uuid.UUID(a_id)},
    )

    removed = await env.client.delete(
        f"{env.a.base}/documents/{a_id}", headers=env.a.org.headers("ke")
    )

    assert removed.status_code == 204
    assert b_path.read_bytes() == b_bytes


async def test_destroyed_key_fails_job_and_remove_still_works(
    pair: Pair,
) -> None:
    env = pair
    a_id = await env.upload(env.a, "a.txt", b"Text of Organization A. " * 10)
    a_path = await env.original(env.a, a_id)
    async with env.engine.connect() as conn, tenant_transaction(conn, env.a.org.org_id):
        assert await destroy_org_key(conn, env.a.org.org_id)

    await env.run_jobs()

    a_after = await env.document(env.a, a_id)
    assert (a_after["status"], a_after["reason"]) == ("failed", "processing_error")
    removed = await env.client.delete(
        f"{env.a.base}/documents/{a_id}", headers=env.a.org.headers("ke")
    )
    assert removed.status_code == 204
    assert not a_path.exists()
    b_id = await env.upload(env.b, "b.txt", b"Text of Organization B. " * 10)
    await env.run_jobs()
    assert (await env.document(env.b, b_id))["status"] == "ready"
