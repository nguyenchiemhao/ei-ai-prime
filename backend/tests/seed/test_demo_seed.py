import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.crypto.master_key import MasterKey
from ei_ai.seed import demo
from ei_ai.seed.demo import (
    DemoManifest,
    SeedRefused,
    SeedResult,
    load_demo_data,
    run_demo_seed,
)
from ei_ai.seed.manifest import load_manifests
from ei_ai.seed.summary import format_summary
from ei_ai.settings import SettingsError, seed_password
from support.crypto import TEST_MASTER_KEY

MEKONG_ID = "0192a000-0000-7000-8000-00000000ea21"
SONG_HAN_ID = "0192a000-0000-7000-8000-00000000ea94"
PEOPLE_OPS = uuid.UUID("0192a000-0000-7000-8000-0000000000aa")
ENGINEERING = uuid.UUID("0192a000-0000-7000-8000-0000000000bb")
CUSTOMER_CARE = uuid.UUID("0192a000-0000-7000-8000-0000000000cc")
TEST_PASSWORD = "Seed-Test-Value-1"
ENV = {
    "EI_AI_ENV": "test",
    "DATABASE_URL": "postgresql://ei_ai_app:pw@db:5432/ei_ai",
    "EI_AI_MASTER_KEY": TEST_MASTER_KEY.key.hex(),
}


def _mekong_result(created: bool) -> SeedResult:
    return SeedResult(
        organization_created=created,
        workspaces=(("People Ops", PEOPLE_OPS, created), ("Engineering", ENGINEERING, created)),
        members_created=(created,) * 10,
        collections_created=8 if created else 0,
        folders_created=33 if created else 0,
        passwords_applied=10 if created else 0,
        audit_events=78 if created else 0,
    )


def _song_han_result(created: bool) -> SeedResult:
    return SeedResult(
        organization_created=created,
        workspaces=(("Customer Care", CUSTOMER_CARE, created),),
        members_created=(created,) * 2,
        collections_created=1 if created else 0,
        folders_created=3 if created else 0,
        passwords_applied=1 if created else 0,
        audit_events=13 if created else 0,
    )


def _summaries(created: bool) -> list[str]:
    mekong, song_han = load_manifests()
    return [
        format_summary(mekong, _mekong_result(created)),
        format_summary(song_han, _song_han_result(created)),
    ]


@pytest.mark.parametrize("environment", ["production", "staging", ""])
def test_refuses_outside_local_and_test(environment: str) -> None:
    called: list[tuple[DemoManifest, ...]] = []

    def load(manifests: tuple[DemoManifest, ...]) -> str:
        called.append(manifests)
        return ""

    with pytest.raises(SeedRefused) as error:
        run_demo_seed(environment, load)

    assert str(error.value) == "the demo seed runs only in local or test environments"
    assert called == [], "the guard must run before settings, engine or database access"


@pytest.mark.parametrize("environment", ["local", "test"])
def test_runs_the_loader_with_the_manifests_in_local_and_test(environment: str) -> None:
    called: list[tuple[DemoManifest, ...]] = []

    def load(manifests: tuple[DemoManifest, ...]) -> str:
        called.append(manifests)
        return "done"

    summary = run_demo_seed(environment, load)

    assert summary == "done"
    assert called == [load_manifests()]


def test_loader_failure_propagates() -> None:
    def unreachable(manifests: tuple[DemoManifest, ...]) -> str:
        raise ConnectionError("db down")

    with pytest.raises(ConnectionError):
        run_demo_seed("local", unreachable)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "EI_AI_SEED_PASSWORD is required"),
        ("", "EI_AI_SEED_PASSWORD is required"),
        ("Q" * 129, "EI_AI_SEED_PASSWORD must be at most 128 characters"),
    ],
)
def test_seed_password_errors_never_contain_the_value(value: str | None, message: str) -> None:
    env = {} if value is None else {"EI_AI_SEED_PASSWORD": value}

    with pytest.raises(SettingsError) as error:
        seed_password(env)

    assert str(error.value) == message
    if value:
        assert value not in str(error.value)
        assert value not in repr(error.value)


def test_seed_password_reads_the_variable() -> None:
    assert seed_password({"EI_AI_SEED_PASSWORD": TEST_PASSWORD}) == TEST_PASSWORD
    assert seed_password({"EI_AI_SEED_PASSWORD": "Q" * 128}) == "Q" * 128


def test_load_demo_data_reads_the_password_before_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_database(*args: object) -> None:
        raise AssertionError("the password must be read before any database access")

    monkeypatch.setattr(demo, "run_with_app_engine", no_database)

    with pytest.raises(SettingsError, match="EI_AI_SEED_PASSWORD is required"):
        load_demo_data(ENV, load_manifests())


def test_load_demo_data_needs_no_admin_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seeded: list[tuple[str, str]] = []
    results = {MEKONG_ID: _mekong_result(True), SONG_HAN_ID: _song_han_result(True)}

    async def fake_seed(
        engine: AsyncEngine, manifest: DemoManifest, password: str, *, master: MasterKey
    ) -> SeedResult:
        assert master == TEST_MASTER_KEY
        seeded.append((manifest.organization, password))
        return results[str(manifest.organization_id)]

    async def fake_run(url: str, work: Callable[[Any], Awaitable[str]]) -> str:
        assert url == ENV["DATABASE_URL"]
        return await work(object())

    monkeypatch.setattr(demo, "seed_manifest", fake_seed)
    monkeypatch.setattr(demo, "run_with_app_engine", fake_run)
    env = {**ENV, "EI_AI_SEED_PASSWORD": TEST_PASSWORD, "ADMIN_BASE_URL": "not a url"}

    output = load_demo_data(env, load_manifests())

    assert seeded == [("Mekong Devworks", TEST_PASSWORD), ("Sông Hàn Retail", TEST_PASSWORD)]
    assert output == "\n".join(_summaries(True))
    assert TEST_PASSWORD not in output


def test_summary_of_a_first_run() -> None:
    mekong, song_han = _summaries(True)

    assert mekong.splitlines() == [
        "Demo seed: Mekong Devworks",
        f"  Organization: Mekong Devworks ({MEKONG_ID}): created",
        f"  Workspace: People Ops ({PEOPLE_OPS}): created",
        f"  Workspace: Engineering ({ENGINEERING}): created",
        "  Members: 10",
        "    - Linh Tran: org_admin, People Ops=workspace_admin: created",
        "    - Minh Pham: People Ops=builder: created",
        "    - Thao Nguyen: People Ops=knowledge_editor: created",
        "    - Quang Le: People Ops=developer, Engineering=workspace_admin: created",
        "    - Hà Vũ: People Ops=reviewer: created",
        "    - Son Hoang: People Ops=viewer: created",
        "    - Duy Lâm: org_owner: created",
        "    - Vy Huỳnh: Engineering=developer: created",
        "    - Phúc Lương: Engineering=knowledge_editor: created",
        "    - Trung Võ: org_owner, People Ops=workspace_admin, Engineering=workspace_admin:"
        " created",
        "  Collections: 8 (created: 8)",
        "  Folders: 33 (created: 33)",
        "  Shared test password applied to 10 of 10 accounts",
        "  Audit events written: 78",
    ]
    assert song_han.splitlines() == [
        "Demo seed: Sông Hàn Retail",
        f"  Organization: Sông Hàn Retail ({SONG_HAN_ID}): created",
        f"  Workspace: Customer Care ({CUSTOMER_CARE}): created",
        "  Members: 2",
        "    - Ngân Trịnh: org_admin, Customer Care=workspace_admin: created",
        "    - Trung Võ: org_owner, Customer Care=workspace_admin: created",
        "  Collections: 1 (created: 1)",
        "  Folders: 3 (created: 3)",
        "  Shared test password applied to 1 of 1 accounts",
        "  Audit events written: 13",
    ]


def test_summary_when_nothing_was_created() -> None:
    mekong, song_han = _summaries(False)
    lines = [*mekong.splitlines(), *song_han.splitlines()]

    assert sum(line.endswith(": already present") for line in lines) == 17
    assert not any(line.endswith(": created") for line in lines)
    assert "  Collections: 8 (created: 0)" in lines
    assert "  Folders: 33 (created: 0)" in lines
    assert "  Shared test password applied to 0 of 10 accounts" in lines
    assert "  Collections: 1 (created: 0)" in lines
    assert "  Folders: 3 (created: 0)" in lines
    assert "  Shared test password applied to 0 of 1 accounts" in lines
    assert lines.count("  Audit events written: 0") == 2
    assert f"  Workspace: Engineering ({ENGINEERING}): already present" in lines
    assert (
        "    - Quang Le: People Ops=developer, Engineering=workspace_admin: already present"
        in lines
    )


def test_summary_never_contains_links_or_tokens() -> None:
    output = "\n".join([*_summaries(True), *_summaries(False)])

    assert "set-password" not in output.lower()
    assert "#token=" not in output
    assert "$argon2" not in output


def test_load_demo_data_reads_the_master_key_before_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_database(*args: object) -> None:
        raise AssertionError("the master key must be read before any database access")

    monkeypatch.setattr(demo, "run_with_app_engine", no_database)
    env = {**ENV, "EI_AI_SEED_PASSWORD": TEST_PASSWORD, "EI_AI_MASTER_KEY": "abc"}

    with pytest.raises(SettingsError) as error:
        load_demo_data(env, load_manifests())

    assert str(error.value) == "EI_AI_MASTER_KEY must be 64 hexadecimal characters"
