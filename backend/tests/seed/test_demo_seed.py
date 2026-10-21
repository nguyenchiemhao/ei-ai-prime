import json
import uuid
from importlib import resources
from typing import Any

import pytest
from pydantic import ValidationError

from ei_ai.seed import demo
from ei_ai.seed.demo import (
    DemoManifest,
    SeedRefused,
    SeedResult,
    format_summary,
    load_demo_data,
    load_manifest,
    run_demo_seed,
)

WS = uuid.UUID("0192a000-0000-7000-8000-0000000000aa")
BASE = "http://localhost:3000"


def _raw_manifest() -> dict[str, Any]:
    text = resources.files("ei_ai.seed").joinpath("data/mekong-devworks.json").read_text("utf-8")
    raw: dict[str, Any] = json.loads(text)
    return raw


def test_manifest_v2_holds_mekong_devworks_people_ops_and_six_members() -> None:
    manifest = load_manifest()

    assert manifest.version == 2
    assert manifest.organization_id == uuid.UUID("0192a000-0000-7000-8000-00000000ea21")
    assert manifest.organization == "Mekong Devworks"
    assert manifest.workspace == "People Ops"
    assert [(m.name, m.email, m.roles) for m in manifest.members] == [
        ("Linh Tran", "linh.tran@mekongdevworks.example", ["org_admin", "workspace_admin"]),
        ("Minh Pham", "minh.pham@mekongdevworks.example", ["builder"]),
        ("Thao Nguyen", "thao.nguyen@mekongdevworks.example", ["knowledge_editor"]),
        ("Quang Le", "quang.le@mekongdevworks.example", ["developer"]),
        ("Hà Vũ", "ha.vu@mekongdevworks.example", ["reviewer"]),
        ("Son Hoang", "son.hoang@mekongdevworks.example", ["viewer"]),
    ]


def test_manifest_holds_the_six_demo_collections() -> None:
    manifest = load_manifest()

    assert [
        (c.name, c.subtitle, c.access_level, c.groups, c.local_only) for c in manifest.collections
    ] == [
        ("Company & Careers", None, "public", [], False),
        ("Employee Handbook", None, "authenticated", [], False),
        ("Engineering Standards", None, "authenticated", [], False),
        ("IT & Security", None, "authenticated", [], False),
        ("Manager Handbook", None, "restricted", ["managers"], True),
        ("Project Falcon", "Client: Japan · under NDA", "restricted", ["project-falcon"], True),
    ]


def test_manifest_restricted_collections_need_groups() -> None:
    raw = _raw_manifest()
    raw["collections"][4]["groups"] = []

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_manifest_unrestricted_collections_have_no_groups() -> None:
    raw = _raw_manifest()
    raw["collections"][0]["groups"] = ["managers"]

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_manifest_collection_names_are_unique_ignoring_case() -> None:
    raw = _raw_manifest()
    raw["collections"][1]["name"] = raw["collections"][0]["name"].upper()

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_summary_counts_created_collections_as_audit_events() -> None:
    result = SeedResult(WS, False, False, (None,) * 6, collections_created=6)

    assert "  Audit events written: 6" in format_summary(load_manifest(), result, BASE)


@pytest.mark.parametrize(
    "roles", [["boss"], ["Builder"], ["builder", "viewer"], ["org_owner", "org_admin"], []]
)
def test_manifest_roles_are_validated(roles: list[str]) -> None:
    raw = _raw_manifest()
    raw["members"][1]["roles"] = roles

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


@pytest.mark.parametrize("email", ["not-an-email", "Minh.Pham@mekongdevworks.example", " a@b.c"])
def test_manifest_emails_must_be_valid_and_normalised(email: str) -> None:
    raw = _raw_manifest()
    raw["members"][1]["email"] = email

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_manifest_emails_are_unique() -> None:
    raw = _raw_manifest()
    raw["members"][1]["email"] = raw["members"][0]["email"]

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_manifest_version_1_is_rejected() -> None:
    raw = _raw_manifest()
    raw["version"] = 1

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


@pytest.mark.parametrize("environment", ["production", "staging", ""])
def test_refuses_outside_local_and_test(environment: str) -> None:
    called: list[DemoManifest] = []

    def load(manifest: DemoManifest) -> str:
        called.append(manifest)
        return ""

    with pytest.raises(SeedRefused) as error:
        run_demo_seed(environment, load)

    assert str(error.value) == "the demo seed runs only in local or test environments"
    assert called == [], "the guard must run before settings, engine or database access"


@pytest.mark.parametrize("environment", ["local", "test"])
def test_runs_the_loader_with_the_manifest_in_local_and_test(environment: str) -> None:
    called: list[DemoManifest] = []

    def load(manifest: DemoManifest) -> str:
        called.append(manifest)
        return "done"

    summary = run_demo_seed(environment, load)

    assert summary == "done"
    assert called == [load_manifest()]


def test_loader_failure_propagates() -> None:
    def unreachable(manifest: DemoManifest) -> str:
        raise ConnectionError("db down")

    with pytest.raises(ConnectionError):
        run_demo_seed("local", unreachable)


def test_summary_of_a_first_run_says_created_and_lists_the_links() -> None:
    manifest = load_manifest()
    secrets = tuple(f"{i}" * 43 for i in range(6))
    result = SeedResult(
        workspace_id=WS, organization_created=True, workspace_created=True, member_secrets=secrets
    )

    lines = format_summary(manifest, result, BASE).splitlines()

    org = "0192a000-0000-7000-8000-00000000ea21"
    assert lines == [
        "Demo seed: Mekong Devworks",
        f"  Organization: Mekong Devworks ({org}): created",
        f"  Workspace: People Ops ({WS}): created",
        "  Members: 6",
        "    - Linh Tran: org_admin, workspace_admin: created",
        "    - Minh Pham: builder: created",
        "    - Thao Nguyen: knowledge_editor: created",
        "    - Quang Le: developer: created",
        "    - Hà Vũ: reviewer: created",
        "    - Son Hoang: viewer: created",
        "  Audit events written: 8",
        "  Set-password links (valid 24 h, shown once):",
        *(
            f"    - {member.email}: {BASE}/set-password#token={org}.{secret}"
            for member, secret in zip(manifest.members, secrets, strict=True)
        ),
    ]


def test_summary_when_nothing_was_created() -> None:
    manifest = load_manifest()
    result = SeedResult(
        workspace_id=WS,
        organization_created=False,
        workspace_created=False,
        member_secrets=(None,) * 6,
    )

    lines = format_summary(manifest, result, BASE).splitlines()

    assert lines[1].endswith("): already present")
    assert lines[2] == f"  Workspace: People Ops ({WS}): already present"
    assert all(line.endswith(": already present") for line in lines[4:10])
    assert lines[10:] == [
        "  Audit events written: 0",
        '  Set-password links: none (no member was created; use "ei-ai user link" for a new link)',
    ]
    assert format_summary(manifest, result, BASE) == format_summary(manifest, result, BASE)


def test_summary_lists_only_the_members_created_in_this_run() -> None:
    manifest = load_manifest()
    secret = "Z" * 43
    result = SeedResult(
        workspace_id=WS,
        organization_created=False,
        workspace_created=False,
        member_secrets=(None, None, secret, None, None, None),
    )

    lines = format_summary(manifest, result, BASE).splitlines()

    assert lines[6] == "    - Thao Nguyen: knowledge_editor: created"
    assert lines[10:] == [
        "  Audit events written: 1",
        "  Set-password links (valid 24 h, shown once):",
        "    - thao.nguyen@mekongdevworks.example: "
        f"{BASE}/set-password#token=0192a000-0000-7000-8000-00000000ea21.{secret}",
    ]


def test_load_demo_data_needs_no_valkey_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    result = SeedResult(WS, False, False, (None,) * 6)

    async def fake_run(database_url: str, work: Any) -> SeedResult:
        seen.append(database_url)
        return result

    monkeypatch.setattr(demo, "run_with_app_engine", fake_run)
    env = {"EI_AI_ENV": "local", "DATABASE_URL": "postgresql://u:pw@db:5432/ei_ai"}

    summary = load_demo_data(env, load_manifest())

    assert seen == ["postgresql://u:pw@db:5432/ei_ai"]
    assert summary == format_summary(load_manifest(), result, "http://localhost:3000")
