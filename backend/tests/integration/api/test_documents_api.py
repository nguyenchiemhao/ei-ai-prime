"""The documents API on the real database and a real runner: upload, processing, list, preview,
chunks, removal, permissions, limits and what never reaches a log or an audit event."""

import logging
import unicodedata
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.jobs.envelope import JobContext
from ei_ai.knowledge import documents as document_service
from ei_ai.knowledge.ingestion.formats import MAX_FILE_BYTES
from support.documents import make_blank_pdf, make_docx, make_text_pdf
from support.isolation.client import RecordingRunner
from support.rbac.orgs import PersonSpec, RoleOrg, role_app
from support.sign_in import in_tenant

from ..knowledge.conftest import MakeOrg, document_file_id, file_store

pytestmark = pytest.mark.integration

PEOPLE: Mapping[str, PersonSpec] = {
    "ke": (None, {"x": "knowledge_editor"}),
    "ws_admin": (None, {"x": "workspace_admin", "y": "workspace_admin"}),
    "builder": (None, {"x": "builder"}),
    "org_admin": ("org_admin", {}),
    "viewer": (None, {"x": "viewer"}),
}
OCTET = "application/octet-stream"
ITEM_KEYS = {
    "id",
    "folder_id",
    "name",
    "format",
    "size_bytes",
    "status",
    "progress",
    "reason",
    "page_count",
    "uploaded_by",
    "created_at",
    "updated_at",
}
CHUNK_KEYS = {
    "ordinal",
    "text",
    "page",
    "heading_path",
    "char_start",
    "char_end",
    "token_estimate",
}
_PARAGRAPH = "Employees need written approval from a manager before overtime starts. "


@dataclass
class Env:
    client: httpx.AsyncClient
    app: FastAPI
    org: RoleOrg
    root: Path
    collection_id: str
    folder_id: str

    @property
    def base(self) -> str:
        return f"/workspaces/{self.org.workspace('x')}/collections/{self.collection_id}"

    def upload_url(self, folder_id: str | None = None) -> str:
        return f"{self.base}/folders/{folder_id or self.folder_id}/documents"

    async def upload(
        self,
        name: str,
        data: bytes,
        *,
        actor: str = "ke",
        folder_id: str | None = None,
        encoded: bool = True,
        extra: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        headers = {
            **self.org.headers(actor),
            "X-File-Name": quote(name, safe="") if encoded else name,
            "Content-Type": OCTET,
            **(extra or {}),
        }
        return await self.client.post(self.upload_url(folder_id), headers=headers, content=data)

    async def original(self, document_id: str) -> Path:
        """Where the encrypted original of a document is: ``<root>/<org_id>/<file_id>.bin``."""
        engine = self.app.state.engine
        file_id = await document_file_id(engine, self.org.org_id, uuid.UUID(document_id))
        assert file_id is not None
        return self.root / str(self.org.org_id) / f"{file_id}.bin"

    async def drain(self) -> None:
        await self.app.state.ingestion_runner.drain()

    async def get(self, path: str, actor: str = "ke") -> httpx.Response:
        return await self.client.get(self.base + path, headers=self.org.headers(actor))

    async def documents(self, query: str = "") -> list[dict[str, object]]:
        response = await self.get("/documents" + query)
        assert response.status_code == 200, response.text
        found: list[dict[str, object]] = response.json()["documents"]
        return found

    async def document(self, document_id: str) -> dict[str, object]:
        found = [d for d in await self.documents() if d["id"] == document_id]
        assert len(found) == 1
        return found[0]

    def recording(self) -> RecordingRunner:
        """Replace the runner with one that only records, for tests that need no processing."""
        runner = RecordingRunner()
        self.app.state.ingestion_runner = runner
        return runner

    async def new_folder(self, name: str) -> str:
        response = await self.client.post(
            f"{self.base}/folders", headers=self.org.headers("ke"), json={"name": name}
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])


@pytest.fixture
async def env(app_engine: AsyncEngine, make_org: MakeOrg, tmp_path: Path) -> AsyncIterator[Env]:
    org = await make_org(PEOPLE)
    app = role_app(app_engine, [org], file_store=file_store(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            f"/workspaces/{org.workspace('x')}/collections",
            headers=org.headers("ke"),
            json={"name": "Handbook", "access_level": "authenticated"},
        )
        collection_id = created.json()["id"]
        folder = await client.post(
            f"/workspaces/{org.workspace('x')}/collections/{collection_id}/folders",
            headers=org.headers("ke"),
            json={"name": "Policies"},
        )
        try:
            yield Env(client, app, org, tmp_path, collection_id, folder.json()["id"])
        finally:
            await app.state.ingestion_runner.close()


def _md(heading: str, section: str) -> bytes:
    body = f"# {heading}\n\n{_PARAGRAPH * 8}\n\n## {section}\n\n{_PARAGRAPH * 8}\n"
    return body.encode()


async def test_five_supported_files_become_ready(env: Env) -> None:
    files = {
        "one.pdf": make_text_pdf([_PARAGRAPH * 6, _PARAGRAPH * 6]),
        "two.docx": make_docx([("Heading 1", "Policy"), ("Normal", _PARAGRAPH * 4)]),
        "three.md": _md("Overtime", "Weekend work"),
        "four.txt": (_PARAGRAPH * 10).encode(),
        "five.pdf": make_text_pdf([_PARAGRAPH * 6]),
    }

    for name, data in files.items():
        response = await env.upload(name, data)
        assert response.status_code == 201, response.text
        assert set(response.json()) == ITEM_KEYS
        assert response.json()["status"] == "queued"
    await env.drain()

    listed = await env.documents()
    assert sorted(str(d["name"]) for d in listed) == sorted(files)
    assert {d["status"] for d in listed} == {"ready"}
    by_name = {d["name"]: d for d in listed}
    assert by_name["one.pdf"]["page_count"] == 2
    assert by_name["five.pdf"]["page_count"] == 1
    assert all(isinstance(d["page_count"], int) and d["page_count"] >= 1 for d in listed)
    assert all(d["progress"] is None and d["reason"] is None for d in listed)


@pytest.mark.parametrize("name", ["setup.exe", "old.doc", "table.xlsx", "noextension"])
async def test_exe_and_doc_rejected_415_without_row(env: Env, name: str) -> None:
    response = await env.upload(name, b"MZ binary")

    assert (response.status_code, response.json()) == (415, {"detail": "unsupported_format"})
    assert await env.documents() == []


async def test_exact_limit_accepted_one_byte_more_rejected(env: Env) -> None:
    env.recording()

    accepted = await env.upload("limit.txt", b"a" * MAX_FILE_BYTES)
    rejected = await env.upload("over.txt", b"a" * (MAX_FILE_BYTES + 1))

    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["size_bytes"] == MAX_FILE_BYTES
    assert (rejected.status_code, rejected.json()) == (413, {"detail": "file_too_large"})
    assert [d["name"] for d in await env.documents()] == ["limit.txt"]
    stored = await env.original(accepted.json()["id"])
    assert stored.stat().st_size == MAX_FILE_BYTES + 32


async def test_content_length_over_limit_rejected_early(env: Env) -> None:
    env.recording()
    read: list[bytes] = []

    async def body() -> AsyncIterator[bytes]:
        read.append(b"x")
        yield b"short"

    response = await env.client.post(
        env.upload_url(),
        headers={
            **env.org.headers("ke"),
            "X-File-Name": "big.txt",
            "Content-Type": OCTET,
            "Content-Length": "60000000",
        },
        content=body(),
    )

    assert (response.status_code, response.json()) == (413, {"detail": "file_too_large"})
    assert read == []
    assert await env.documents() == []


async def test_viewer_is_refused_before_the_body_is_read(env: Env) -> None:
    read: list[bytes] = []

    async def body() -> AsyncIterator[bytes]:
        read.append(b"x")
        yield b"short"

    response = await env.client.post(
        env.upload_url(),
        headers={
            **env.org.headers("viewer"),
            "X-File-Name": "big.txt",
            "Content-Type": OCTET,
            "Content-Length": "60000000",
        },
        content=body(),
    )

    assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})
    assert read == []


async def test_empty_file_422(env: Env) -> None:
    response = await env.upload("empty.txt", b"")

    assert (response.status_code, response.json()) == (422, {"detail": "empty_file"})
    assert await env.documents() == []


async def test_invalid_file_name_422(env: Env) -> None:
    invalid = {
        "missing header": None,
        "bad escape": "%ZZ.txt",
        "invalid utf-8": "%FF%FE.txt",
        "control character": "a%00b.txt",
        "blank": "%20%20",
        "256 characters": "a" * 252 + ".txt",
    }
    for case, header in invalid.items():
        headers = {**env.org.headers("ke"), "Content-Type": OCTET}
        if header is not None:
            headers["X-File-Name"] = header
        response = await env.client.post(env.upload_url(), headers=headers, content=b"text")
        assert (response.status_code, response.json()) == (
            422,
            {"detail": "invalid_file_name"},
        ), case
    assert await env.documents() == []


async def test_the_longest_file_name_is_accepted(env: Env) -> None:
    env.recording()

    response = await env.upload("a" * 251 + ".txt", b"text")

    assert response.status_code == 201
    assert len(response.json()["name"]) == 255


async def test_quota_exceeded_413(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    env.recording()
    monkeypatch.setattr(document_service, "ORG_QUOTA_BYTES", 20)

    first = await env.upload("a.txt", b"0123456789")
    second = await env.upload("b.txt", b"0123456789")
    third = await env.upload("c.txt", b"0")

    assert (first.status_code, second.status_code) == (201, 201)
    assert (third.status_code, third.json()) == (413, {"detail": "storage_quota_exceeded"})
    assert len(await env.documents()) == 2


async def test_scanned_pdf_not_supported_without_chunks_and_removable(env: Env) -> None:
    created = (await env.upload("scan.pdf", make_blank_pdf(2))).json()
    await env.drain()

    shown = await env.document(created["id"])
    chunks = await env.get(f"/documents/{created['id']}/chunks")
    text = await env.get(f"/documents/{created['id']}/text")
    removed = await env.client.delete(
        f"{env.base}/documents/{created['id']}", headers=env.org.headers("ke")
    )

    assert (shown["status"], shown["reason"], shown["page_count"]) == (
        "not_supported",
        "scanned_pdf",
        None,
    )
    assert (chunks.status_code, chunks.json()) == (409, {"detail": "document_not_ready"})
    assert (text.status_code, text.json()) == (409, {"detail": "document_not_ready"})
    assert removed.status_code == 204
    assert await env.documents() == []


async def test_corrupt_file_fails_with_reason_others_ready(env: Env) -> None:
    await env.upload("good-one.txt", (_PARAGRAPH * 5).encode())
    await env.upload("broken.pdf", b"\x00\x01 random bytes, not a pdf" * 20)
    await env.upload("good-two.md", _md("Title", "Part"))
    await env.drain()

    by_name = {d["name"]: d for d in await env.documents()}

    assert (by_name["broken.pdf"]["status"], by_name["broken.pdf"]["reason"]) == (
        "failed",
        "corrupt_file",
    )
    assert by_name["good-one.txt"]["status"] == "ready"
    assert by_name["good-two.md"]["status"] == "ready"


async def _chunks(env: Env, document_id: str) -> list[dict[str, object]]:
    response = await env.get(f"/documents/{document_id}/chunks")
    assert response.status_code == 200, response.text
    found: list[dict[str, object]] = response.json()["chunks"]
    return found


async def test_nfc_and_nfd_uploads_have_identical_chunks(env: Env) -> None:
    text = (
        "# Quy trình làm thêm giờ\n\n"
        + "Nhân viên cần được quản lý phê duyệt trước khi làm thêm giờ. " * 12
        + "\n\n## Làm việc cuối tuần\n\n"
        + "Cần có sự đồng ý bằng văn bản của trưởng phòng. " * 12
    )
    nfc = unicodedata.normalize("NFC", text).encode()
    nfd = unicodedata.normalize("NFD", text).encode()
    assert nfc != nfd

    first = (await env.upload("vn-nfc.md", nfc)).json()["id"]
    second = (await env.upload("vn-nfd.md", nfd)).json()["id"]
    await env.drain()

    assert await _chunks(env, first) == await _chunks(env, second)
    assert len(await _chunks(env, first)) >= 2


async def test_chunks_route_returns_location(env: Env) -> None:
    pdf = (
        await env.upload("p.pdf", make_text_pdf([_PARAGRAPH * 6, _PARAGRAPH * 6, _PARAGRAPH * 6]))
    ).json()["id"]
    docx = (
        await env.upload(
            "d.docx",
            make_docx(
                [
                    ("Heading 1", "Overtime"),
                    ("Normal", _PARAGRAPH * 4),
                    ("Heading 2", "Weekend work"),
                    ("Normal", _PARAGRAPH * 4),
                ]
            ),
        )
    ).json()["id"]
    markdown = (await env.upload("m.md", _md("Overtime", "Weekend work"))).json()["id"]
    await env.drain()

    pdf_chunks = await _chunks(env, pdf)
    docx_chunks = await _chunks(env, docx)
    md_chunks = await _chunks(env, markdown)

    assert all(set(chunk) == CHUNK_KEYS for chunk in pdf_chunks)
    assert [c["ordinal"] for c in pdf_chunks] == list(range(len(pdf_chunks)))
    assert {c["page"] for c in pdf_chunks} == {1, 2, 3}
    assert all(c["heading_path"] == [] for c in pdf_chunks)
    assert all(c["page"] is None for c in docx_chunks + md_chunks)
    assert docx_chunks[-1]["heading_path"] == ["Overtime", "Weekend work"]
    assert md_chunks[-1]["heading_path"] == ["Overtime", "Weekend work"]
    for document_id, chunks in ((pdf, pdf_chunks), (docx, docx_chunks), (markdown, md_chunks)):
        text = (await env.get(f"/documents/{document_id}/text")).json()["text"]
        for chunk in chunks:
            start, end = int(str(chunk["char_start"])), int(str(chunk["char_end"]))
            assert text[start:end] == chunk["text"]


async def test_text_route_truncates_at_100000(env: Env) -> None:
    line = "x" * 99 + "\n"
    created = (await env.upload("long.txt", (line * 1300).encode())).json()
    short = (await env.upload("short.txt", b"Short text.")).json()
    await env.drain()

    preview = (await env.get(f"/documents/{created['id']}/text")).json()
    whole = (await env.get(f"/documents/{short['id']}/text")).json()

    assert preview["truncated"] is True
    assert len(preview["text"]) == 100_000
    assert preview["total_characters"] > 100_000
    assert whole == {"text": "Short text.", "truncated": False, "total_characters": 11}


async def test_text_of_queued_document_409(env: Env) -> None:
    env.recording()
    created = (await env.upload("waiting.txt", b"text")).json()

    text = await env.get(f"/documents/{created['id']}/text")
    chunks = await env.get(f"/documents/{created['id']}/chunks")

    assert (text.status_code, text.json()) == (409, {"detail": "document_not_ready"})
    assert (chunks.status_code, chunks.json()) == (409, {"detail": "document_not_ready"})


@pytest.mark.parametrize(
    ("actor", "status"),
    [("ke", 201), ("ws_admin", 201), ("builder", 201), ("org_admin", 201), ("viewer", 403)],
)
async def test_viewer_403_editor_admin_builder_201(env: Env, actor: str, status: int) -> None:
    env.recording()

    response = await env.upload("a.txt", b"text", actor=actor)

    assert response.status_code == status, response.text
    if status == 403:
        assert response.json() == {"detail": "forbidden"}
        assert await env.documents() == []


async def test_viewer_cannot_use_the_other_routes(env: Env) -> None:
    env.recording()
    created = (await env.upload("a.txt", b"text")).json()
    paths = [
        ("GET", "/documents"),
        ("GET", f"/documents/{created['id']}/text"),
        ("GET", f"/documents/{created['id']}/chunks"),
        ("DELETE", f"/documents/{created['id']}"),
    ]

    for method, path in paths:
        response = await env.client.request(
            method, env.base + path, headers=env.org.headers("viewer")
        )
        assert response.status_code == 403, (method, path)

    assert len(await env.documents()) == 1


async def test_uploaded_by_is_the_caller(env: Env) -> None:
    env.recording()
    forged = {"X-Org-Id": str(uuid.uuid4()), "X-Tenant-Id": str(uuid.uuid4())}

    response = await env.client.post(
        env.upload_url() + f"?org_id={uuid.uuid4()}&uploaded_by={uuid.uuid4()}",
        headers={
            **env.org.headers("builder"),
            **forged,
            "X-File-Name": "mine.txt",
            "Content-Type": OCTET,
        },
        content=b"text",
    )

    assert response.status_code == 201, response.text
    assert response.json()["uploaded_by"] == {
        "id": str(env.org.user("builder")),
        "display_name": env.org.people["builder"].display_name,
    }
    rows = await in_tenant(
        env.app.state.engine,
        env.org.org_id,
        "SELECT org_id, uploaded_by FROM documents WHERE org_id = :org AND id = :id",
        {"id": uuid.UUID(response.json()["id"])},
    )
    assert [tuple(row) for row in rows] == [(env.org.org_id, env.org.user("builder"))]


async def test_file_name_with_path_is_reduced_to_base_name(env: Env) -> None:
    env.recording()

    traversal = await env.upload("../../etc/passwd.txt", b"text")
    windows = await env.upload("C:\\temp\\a\\report.md", b"# text")

    assert traversal.status_code == 201
    assert traversal.json()["name"] == "passwd.txt"
    assert windows.json()["name"] == "report.md"
    originals = {await env.original(r.json()["id"]) for r in (traversal, windows)}
    files = {path for path in env.root.rglob("*") if path.is_file()}
    assert files == originals
    assert all(path.parent == env.root / str(env.org.org_id) for path in files)


async def test_encoded_slashes_in_the_header_are_reduced_too(env: Env) -> None:
    env.recording()

    response = await env.client.post(
        env.upload_url(),
        headers={
            **env.org.headers("ke"),
            "X-File-Name": "..%2F..%2Fetc%2Fpasswd.txt",
            "Content-Type": OCTET,
        },
        content=b"text",
    )

    assert (response.status_code, response.json()["name"]) == (201, "passwd.txt")


async def test_upload_logs_no_file_name(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    secret_name = "qa-EA33-secret-name.txt"
    secret_text = "qa-EA33-secret-text"

    created = (await env.upload(secret_name, secret_text.encode())).json()
    await env.drain()
    broken = (await env.upload("qa-EA33-broken-name.pdf", b"qa-EA33-broken-text")).json()
    await env.drain()
    await env.client.delete(f"{env.base}/documents/{created['id']}", headers=env.org.headers("ke"))

    assert secret_name not in caplog.text
    assert secret_text not in caplog.text
    assert "qa-EA33-broken" not in caplog.text
    assert created["id"] in caplog.text
    assert broken["id"] in caplog.text


async def test_upload_and_remove_audit_codes_only(env: Env) -> None:
    secret_name = "qa-EA33-secret-name.txt"
    created = (await env.upload(secret_name, b"qa-EA33-secret-text")).json()
    await env.drain()

    removed = await env.client.delete(
        f"{env.base}/documents/{created['id']}", headers=env.org.headers("ke")
    )

    assert removed.status_code == 204
    rows = await in_tenant(
        env.app.state.engine,
        env.org.org_id,
        "SELECT action, target_type, old_value, new_value, actor, workspace_id FROM audit_events"
        " WHERE org_id = :org AND target_id = :id ORDER BY created_at, id",
        {"id": uuid.UUID(created["id"])},
    )
    actor = f"user:{env.org.user('ke')}"
    assert [tuple(row) for row in rows] == [
        ("document.uploaded", "document", None, "txt", actor, env.org.workspace("x")),
        ("document.removed", "document", "txt", None, actor, env.org.workspace("x")),
    ]
    dump = await in_tenant(
        env.app.state.engine,
        env.org.org_id,
        "SELECT string_agg(audit_events::text, ' ') FROM audit_events WHERE org_id = :org",
    )
    assert "qa-EA33" not in str(dump)


async def test_remove_deletes_row_chunks_and_original(env: Env) -> None:
    created = (await env.upload("a.txt", (_PARAGRAPH * 6).encode())).json()
    await env.drain()
    original = await env.original(created["id"])
    assert original.exists()

    removed = await env.client.delete(
        f"{env.base}/documents/{created['id']}", headers=env.org.headers("ke")
    )
    again = await env.client.delete(
        f"{env.base}/documents/{created['id']}", headers=env.org.headers("ke")
    )

    assert removed.status_code == 204
    assert (again.status_code, again.json()) == (404, {"detail": "not_found"})
    assert not original.exists()
    chunks = await in_tenant(
        env.app.state.engine,
        env.org.org_id,
        "SELECT count(*) FROM document_chunks WHERE org_id = :org",
    )
    assert chunks[0][0] == 0


async def test_document_of_other_workspace_is_404(env: Env, app_engine: AsyncEngine) -> None:
    env.recording()
    created = (await env.upload("a.txt", b"text")).json()
    other = await env.client.post(
        f"/workspaces/{env.org.workspace('y')}/collections",
        headers=env.org.headers("ws_admin"),
        json={"name": "Elsewhere", "access_level": "authenticated"},
    )
    other_collection = other.json()["id"]
    unknown = str(uuid.uuid4())
    foreign_base = f"/workspaces/{env.org.workspace('x')}/collections/{other_collection}"
    unknown_base = f"/workspaces/{env.org.workspace('x')}/collections/{unknown}"
    # the same Workspace in the path, a document of another collection of the same Workspace
    sibling = await env.client.post(
        f"/workspaces/{env.org.workspace('x')}/collections",
        headers=env.org.headers("ke"),
        json={"name": "Sibling", "access_level": "authenticated"},
    )
    sibling_base = f"/workspaces/{env.org.workspace('x')}/collections/{sibling.json()['id']}"
    document = created["id"]

    for base in (foreign_base, unknown_base, sibling_base):
        listing = [] if base == sibling_base else [("GET", "/documents")]
        for method, path in (
            *listing,
            ("GET", f"/documents/{document}/text"),
            ("GET", f"/documents/{document}/chunks"),
            ("DELETE", f"/documents/{document}"),
            ("POST", f"/folders/{env.folder_id}/documents"),
        ):
            response = await env.client.request(
                method,
                base + path,
                headers={**env.org.headers("ke"), "X-File-Name": "a.txt", "Content-Type": OCTET},
                content=b"text" if method == "POST" else None,
            )
            assert (response.status_code, response.json()) == (
                404,
                {"detail": "not_found"},
            ), (base, method, path)
    assert len(await env.documents()) == 1


async def test_folder_of_another_collection_is_404(env: Env) -> None:
    sibling = await env.client.post(
        f"/workspaces/{env.org.workspace('x')}/collections",
        headers=env.org.headers("ke"),
        json={"name": "Sibling", "access_level": "authenticated"},
    )
    other_folder = await env.client.post(
        f"/workspaces/{env.org.workspace('x')}/collections/{sibling.json()['id']}/folders",
        headers=env.org.headers("ke"),
        json={"name": "Other"},
    )

    upload = await env.upload("a.txt", b"text", folder_id=other_folder.json()["id"])
    listed = await env.get(f"/documents?folder_id={other_folder.json()['id']}")

    assert (upload.status_code, upload.json()) == (404, {"detail": "not_found"})
    assert (listed.status_code, listed.json()) == (404, {"detail": "not_found"})


async def test_processing_shows_progress(env: Env) -> None:
    runner = env.recording()
    created = (await env.upload("a.txt", b"text")).json()
    document_id = uuid.UUID(created["id"])
    board = env.app.state.progress_board
    ctx = JobContext(org_id=env.org.org_id, session=None)  # type: ignore[arg-type]

    board.track(runner.submitted[0], document_id)
    waiting = await env.document(created["id"])
    board.start(ctx, document_id)
    board.report(ctx, document_id, 60)
    running = await env.document(created["id"])

    assert (waiting["status"], waiting["progress"]) == ("queued", None)
    assert (running["status"], running["progress"], running["page_count"]) == (
        "processing",
        60,
        None,
    )


async def test_queued_document_without_a_job_is_interrupted_after_two_minutes(env: Env) -> None:
    env.recording()
    created = (await env.upload("a.txt", b"text")).json()
    now = env.app.state.clock()

    env.app.state.clock = lambda: now + timedelta(minutes=3)
    shown = await env.document(created["id"])

    assert (shown["status"], shown["reason"]) == ("failed", "interrupted")


async def test_list_filters_by_folder_newest_first(env: Env) -> None:
    env.recording()
    second_folder = await env.new_folder("Templates")
    first = (await env.upload("first.txt", b"text")).json()
    second = (await env.upload("second.txt", b"text", folder_id=second_folder)).json()
    third = (await env.upload("third.txt", b"text")).json()

    everything = [d["id"] for d in await env.documents()]
    in_policies = [d["id"] for d in await env.documents(f"?folder_id={env.folder_id}")]
    in_templates = [d["id"] for d in await env.documents(f"?folder_id={second_folder}")]
    unknown = await env.get(f"/documents?folder_id={uuid.uuid4()}")

    assert everything == [third["id"], second["id"], first["id"]]
    assert in_policies == [third["id"], first["id"]]
    assert in_templates == [second["id"]]
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "not_found"})


async def test_folder_counts_and_delete_follow_documents(env: Env) -> None:
    env.recording()
    created = (await env.upload("a.txt", b"text")).json()
    folder_url = f"{env.base}/folders/{env.folder_id}"

    detail = await env.client.get(env.base, headers=env.org.headers("ke"))
    blocked = await env.client.delete(folder_url, headers=env.org.headers("ke"))
    await env.client.delete(f"{env.base}/documents/{created['id']}", headers=env.org.headers("ke"))
    allowed = await env.client.delete(folder_url, headers=env.org.headers("ke"))

    assert [f["document_count"] for f in detail.json()["folders"]] == [1]
    assert detail.json()["documents"]["total"] == 1
    assert (blocked.status_code, blocked.json()) == (409, {"detail": "folder_not_empty"})
    assert allowed.status_code == 204


async def test_collection_documents_summary_in_every_response(env: Env) -> None:
    env.recording()
    await env.upload("a.txt", b"text")
    listed = await env.client.get(
        f"/workspaces/{env.org.workspace('x')}/collections", headers=env.org.headers("ke")
    )
    patched = await env.client.patch(
        env.base, headers=env.org.headers("ke"), json={"name": "Renamed"}
    )

    expected = {"total": 1, "ready": 0, "processing": 1, "needs_attention": 0}
    assert listed.json()["collections"][0]["documents"] == expected
    assert patched.json()["documents"] == expected


async def test_collection_delete_removes_documents_chunks_and_originals(env: Env) -> None:
    created = (await env.upload("a.txt", (_PARAGRAPH * 6).encode())).json()
    await env.drain()
    original = await env.original(created["id"])
    assert original.exists()

    response = await env.client.delete(env.base, headers=env.org.headers("ke"))

    assert response.status_code == 204
    assert not original.exists()
    counts = await in_tenant(
        env.app.state.engine,
        env.org.org_id,
        "SELECT (SELECT count(*) FROM documents WHERE org_id = :org),"
        " (SELECT count(*) FROM document_chunks WHERE org_id = :org)",
    )
    assert tuple(counts[0]) == (0, 0)


async def test_interrupted_document_counts_as_needs_attention(env: Env) -> None:
    env.recording()
    await env.upload("a.txt", b"text")
    url = f"/workspaces/{env.org.workspace('x')}/collections"
    now = env.app.state.clock()

    fresh = await env.client.get(url, headers=env.org.headers("ke"))
    env.app.state.clock = lambda: now + timedelta(minutes=3)
    stale = await env.client.get(url, headers=env.org.headers("ke"))
    detail = await env.client.get(env.base, headers=env.org.headers("ke"))

    assert fresh.json()["collections"][0]["documents"] == {
        "total": 1,
        "ready": 0,
        "processing": 1,
        "needs_attention": 0,
    }
    expected = {"total": 1, "ready": 0, "processing": 0, "needs_attention": 1}
    assert stale.json()["collections"][0]["documents"] == expected
    assert detail.json()["documents"] == expected


async def test_a_queued_document_a_job_still_holds_stays_processing(env: Env) -> None:
    runner = env.recording()
    created = (await env.upload("a.txt", b"text")).json()
    env.app.state.progress_board.track(runner.submitted[0], uuid.UUID(created["id"]))
    now = env.app.state.clock()

    env.app.state.clock = lambda: now + timedelta(minutes=10)
    listed = await env.client.get(
        f"/workspaces/{env.org.workspace('x')}/collections", headers=env.org.headers("ke")
    )

    assert listed.json()["collections"][0]["documents"]["processing"] == 1
