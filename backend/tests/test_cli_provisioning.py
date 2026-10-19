"""The provisioning commands of the CLI with the service replaced (FND-04 AC1, AC2, NFR)."""

import logging
import re
import uuid
from typing import Any

import pytest

from ei_ai import cli
from ei_ai.db import engine as engine_module
from ei_ai.provisioning import commands
from ei_ai.provisioning.service import (
    CreatedOrganization,
    CreatedWorkspace,
    InvitedUser,
    IssuedLink,
)
from ei_ai.provisioning.validation import ProvisioningError

ORG = uuid.UUID("0192a000-0000-7000-8000-000000000001")
WS = uuid.UUID("0192a000-0000-7000-8000-000000000002")
USER = uuid.UUID("0192a000-0000-7000-8000-000000000003")
SECRET = "S3cr3t-" + "x" * 36
LINK = f"Set-password link (valid 24 h, shown once): http://localhost:3000/set-password#token={ORG}.{SECRET}"
LINK_RE = re.compile(
    r"^Set-password link \(valid 24 h, shown once\): http://localhost:3000/set-password#token="
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.([A-Za-z0-9_-]{43})$"
)
DB_PASSWORD = "s3cret-pw"
E11 = (
    'error: unknown role "boss"; valid roles: org_owner, org_admin, workspace_admin, developer,'
    " builder, knowledge_editor, reviewer, viewer, member"
)


@pytest.fixture(autouse=True)
def local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EI_AI_ENV", "local")
    monkeypatch.setenv("DATABASE_URL", f"postgresql://ei_ai_app:{DB_PASSWORD}@db:5432/ei_ai")
    monkeypatch.setenv("VALKEY_URL", "redis://valkey:6379/0")
    monkeypatch.delenv("ADMIN_BASE_URL", raising=False)


@pytest.fixture
def no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any database access fails the test loudly (with a class name the CLI would print)."""

    class NoDatabaseAccess(Exception):
        pass

    class NoEngine:
        def connect(self) -> None:
            raise NoDatabaseAccess

        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(engine_module, "create_cli_engine", lambda url: NoEngine())


def _fake(monkeypatch: pytest.MonkeyPatch, name: str, result: object) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake(engine: Any, *args: Any, **kwargs: Any) -> object:
        calls.append({"args": args, **kwargs})
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(commands, name, fake)
    return calls


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


CREATED = CreatedOrganization(
    ORG, "Mekong Devworks", WS, "Default", USER, "linh.tran@mekongdevworks.example", SECRET
)
AC1_ARGV = [
    "org",
    "create",
    "--name",
    "Mekong Devworks",
    "--owner",
    "linh.tran@mekongdevworks.example",
]


def test_org_create_passes_name_and_owner_through(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _fake(monkeypatch, "create_organization", CREATED)

    code, _, _ = _run(AC1_ARGV, capsys)

    assert code == 0
    assert calls == [
        {
            "args": (),
            "name": "Mekong Devworks",
            "owner_email": "linh.tran@mekongdevworks.example",
            "owner_name": None,
            "workspace_name": "Default",
        }
    ]


def test_org_create_passes_the_optional_names(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _fake(monkeypatch, "create_organization", CREATED)

    _run([*AC1_ARGV, "--owner-name", "Linh Tran", "--workspace-name", "People Ops"], capsys)

    assert calls[0]["owner_name"] == "Linh Tran"
    assert calls[0]["workspace_name"] == "People Ops"


def test_org_create_prints_ids_and_link(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "A" * 43
    _fake(
        monkeypatch,
        "create_organization",
        CreatedOrganization(ORG, "QA X", WS, "Default", USER, "owner@example.com", secret),
    )

    code, out, err = _run(["org", "create", "--name", "  QA X  ", "--owner", "Owner@x.io"], capsys)

    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[:3] == [
        f"Organization created: {ORG} (QA X)",
        f"Workspace created: {WS} (Default)",
        f"Org Owner created: {USER} (owner@example.com)",
    ]
    match = LINK_RE.match(lines[3])
    assert match is not None
    assert match.groups() == (str(ORG), secret)
    assert len(lines) == 4


def test_workspace_create_prints_one_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _fake(monkeypatch, "create_workspace", CreatedWorkspace(WS, "Second"))

    code, out, err = _run(["workspace", "create", "--org", str(ORG), "--name", " Second "], capsys)

    assert (code, out, err) == (0, f"Workspace created: {WS} (Second)\n", "")
    assert calls == [{"args": (ORG, " Second ")}]


def test_user_invite_prints_user_roles_and_link(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _fake(
        monkeypatch,
        "invite_user",
        InvitedUser(USER, "lead@example.com", ("org_admin", "workspace_admin"), SECRET),
    )
    argv = ["user", "invite", "--org", str(ORG), "--email", "Lead@example.com"]
    argv += ["--role", "workspace_admin", "--role", "org_admin", "--workspace", str(WS)]
    argv += ["--name", "Lead"]

    code, out, err = _run(argv, capsys)

    assert (code, err) == (0, "")
    assert out.splitlines() == [
        f"User invited: {USER} (lead@example.com) roles: org_admin, workspace_admin",
        LINK,
    ]
    assert calls == [
        {
            "args": (ORG, "Lead@example.com", ["workspace_admin", "org_admin"]),
            "workspace_id": WS,
            "display_name": "Lead",
        }
    ]


def test_user_link_prints_the_link_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _fake(monkeypatch, "issue_link", IssuedLink(USER, SECRET))

    code, out, err = _run(["user", "link", "--org", str(ORG), "--email", "a@b.example"], capsys)

    assert (code, out, err) == (0, f"{LINK}\n", "")
    assert calls == [{"args": (ORG, "a@b.example")}]


ORG_ARG = str(ORG)
VALIDATION_CASES = [
    (
        ["org", "create", "--name", "  ", "--owner", "o@example.com"],
        "error: Organization name must be 1-200 characters",
    ),
    (["org", "create", "--name", "X", "--owner", "not-an-email"], "error: invalid email address"),
    (["org", "create", "--name", "X", "--owner", "a b@c.example"], "error: invalid email address"),
    (
        ["org", "create", "--name", "X", "--owner", "o@example.com", "--owner-name", " "],
        "error: display name must be 1-200 characters",
    ),
    (
        ["org", "create", "--name", "X", "--owner", "o@example.com", "--workspace-name", ""],
        "error: Workspace name must be 1-200 characters",
    ),
    (
        ["workspace", "create", "--org", ORG_ARG, "--name", " "],
        "error: Workspace name must be 1-200 characters",
    ),
    (
        ["workspace", "create", "--org", "nope", "--name", "W"],
        "error: --org must be an Organization id (UUID)",
    ),
    (
        ["user", "link", "--org", "nope", "--email", "a@b.example"],
        "error: --org must be an Organization id (UUID)",
    ),
    (
        [
            "user",
            "invite",
            "--org",
            ORG_ARG,
            "--email",
            "a@b.example",
            "--role",
            "builder",
            "--workspace",
            "nope",
        ],
        "error: --workspace must be a Workspace id (UUID)",
    ),
    (
        ["user", "invite", "--org", ORG_ARG, "--email", "a@b", "--role", "builder"],
        "error: invalid email address",
    ),
    (["user", "invite", "--org", ORG_ARG, "--email", "a@b.example", "--role", "boss"], E11),
    (
        [
            "user",
            "invite",
            "--org",
            ORG_ARG,
            "--email",
            "a@b.example",
            "--role",
            "builder",
            "--role",
            "viewer",
        ],
        "error: give at most one Organization role and one Workspace role",
    ),
    (
        ["user", "invite", "--org", ORG_ARG, "--email", "a@b.example", "--role", "builder"],
        "error: a Workspace role needs --workspace",
    ),
    (
        [
            "user",
            "invite",
            "--org",
            ORG_ARG,
            "--email",
            "a@b.example",
            "--role",
            "org_admin",
            "--workspace",
            str(WS),
        ],
        "error: --workspace needs a Workspace role",
    ),
    (
        [
            "user",
            "invite",
            "--org",
            ORG_ARG,
            "--email",
            "a@b.example",
            "--role",
            "org_admin",
            "--name",
            "",
        ],
        "error: display name must be 1-200 characters",
    ),
    (["user", "link", "--org", ORG_ARG, "--email", "linh@"], "error: invalid email address"),
]


@pytest.mark.usefixtures("no_database")
@pytest.mark.parametrize(("argv", "expected"), VALIDATION_CASES)
def test_invalid_input_exits_1_with_the_exact_message_before_any_database_access(
    argv: list[str], expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(argv, capsys) == (1, "", f"{expected}\n")


@pytest.mark.usefixtures("no_database")
def test_malformed_email_exits_1_before_database(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["org", "create", "--name", "Mekong Devworks", "--owner", "a@@b.example"]

    assert _run(argv, capsys) == (1, "", "error: invalid email address\n")


SERVICE_ERRORS = [
    ("create_organization", AC1_ARGV, "an Organization with this name already exists"),
    (
        "create_workspace",
        ["workspace", "create", "--org", ORG_ARG, "--name", "W"],
        "a Workspace with this name already exists in this Organization",
    ),
    (
        "create_workspace",
        ["workspace", "create", "--org", ORG_ARG, "--name", "W"],
        "Organization not found",
    ),
    (
        "invite_user",
        [
            "user",
            "invite",
            "--org",
            ORG_ARG,
            "--email",
            "a@b.example",
            "--role",
            "builder",
            "--workspace",
            str(WS),
        ],
        "Workspace not found in this Organization",
    ),
    (
        "invite_user",
        ["user", "invite", "--org", ORG_ARG, "--email", "a@b.example", "--role", "org_admin"],
        "a user with this email already exists in this Organization",
    ),
    (
        "issue_link",
        ["user", "link", "--org", ORG_ARG, "--email", "a@b.example"],
        "user not found in this Organization",
    ),
]


@pytest.mark.parametrize(("function", "argv", "message"), SERVICE_ERRORS)
def test_service_errors_print_error_line_and_exit_1(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    function: str,
    argv: list[str],
    message: str,
) -> None:
    _fake(monkeypatch, function, ProvisioningError(message))

    assert _run(argv, capsys) == (1, "", f"error: {message}\n")


@pytest.mark.parametrize(
    ("argv", "missing"),
    [
        (["org", "create", "--owner", "o@example.com"], "--name"),
        (["org", "create", "--name", "X"], "--owner"),
        (["workspace", "create", "--name", "W"], "--org"),
        (["user", "invite", "--org", ORG_ARG, "--email", "a@b.example"], "--role"),
        (["user", "link", "--org", ORG_ARG], "--email"),
    ],
)
def test_missing_required_flag_is_a_usage_error(
    argv: list[str], missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.out == ""
    assert f"error: the following arguments are required: {missing}" in captured.err


@pytest.mark.parametrize("argv", [["org", "delete"], ["user"], ["workspace", "list"]])
def test_unknown_subcommand_is_a_usage_error(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)

    assert exit_info.value.code == 2


@pytest.mark.parametrize(
    ("function", "argv", "command"),
    [
        ("create_organization", AC1_ARGV, "org create"),
        (
            "create_workspace",
            ["workspace", "create", "--org", ORG_ARG, "--name", "W"],
            "workspace create",
        ),
        (
            "invite_user",
            ["user", "invite", "--org", ORG_ARG, "--email", "a@b.example", "--role", "org_admin"],
            "user invite",
        ),
        ("issue_link", ["user", "link", "--org", ORG_ARG, "--email", "a@b.example"], "user link"),
    ],
)
def test_unexpected_error_prints_class_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    function: str,
    argv: list[str],
    command: str,
) -> None:
    class OperationalError(Exception):
        pass

    leak = OperationalError(
        f"connection to postgresql://ei_ai_app:{DB_PASSWORD}@db failed; Key (lower(name))=(x)"
    )
    _fake(monkeypatch, function, leak)

    code, out, err = _run(argv, capsys)

    assert (code, out, err) == (1, "", f"error: {command} failed (OperationalError)\n")


def test_no_secret_in_log_records(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _fake(monkeypatch, "create_organization", CREATED)
    caplog.set_level(logging.DEBUG)

    code, out, _ = _run(AC1_ARGV, capsys)

    assert code == 0
    assert SECRET in out
    logged = "\n".join(
        f"{record.getMessage()} {record.args!r} {record.exc_text or ''}"
        for record in caplog.records
    )
    assert SECRET not in logged
    assert "linh.tran" not in logged


@pytest.mark.parametrize("value", [None, ""])
@pytest.mark.parametrize(
    ("function", "argv"),
    [
        ("create_organization", AC1_ARGV),
        (
            "invite_user",
            ["user", "invite", "--org", ORG_ARG, "--email", "a@b.example", "--role", "org_admin"],
        ),
        ("issue_link", ["user", "link", "--org", ORG_ARG, "--email", "a@b.example"]),
    ],
)
def test_link_commands_need_admin_base_url_in_production(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: str | None,
    function: str,
    argv: list[str],
) -> None:
    monkeypatch.setenv("EI_AI_ENV", "production")
    if value is not None:
        monkeypatch.setenv("ADMIN_BASE_URL", value)
    calls = _fake(monkeypatch, function, CREATED)

    assert _run(argv, capsys) == (1, "", "configuration error: ADMIN_BASE_URL is required\n")
    assert calls == []


def test_workspace_create_does_not_read_admin_base_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EI_AI_ENV", "production")
    _fake(monkeypatch, "create_workspace", CreatedWorkspace(WS, "W"))

    code, _, err = _run(["workspace", "create", "--org", ORG_ARG, "--name", "W"], capsys)

    assert (code, err) == (0, "")


def test_link_uses_the_configured_admin_base_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ADMIN_BASE_URL", "https://admin.example.com/")
    _fake(monkeypatch, "issue_link", IssuedLink(USER, SECRET))

    _, out, _ = _run(["user", "link", "--org", ORG_ARG, "--email", "a@b.example"], capsys)

    assert out == (
        "Set-password link (valid 24 h, shown once): "
        f"https://admin.example.com/set-password#token={ORG}.{SECRET}\n"
    )


def test_invalid_admin_base_url_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ADMIN_BASE_URL", "admin.example.com")
    calls = _fake(monkeypatch, "issue_link", IssuedLink(USER, SECRET))

    assert _run(["user", "link", "--org", ORG_ARG, "--email", "a@b.example"], capsys) == (
        1,
        "",
        "configuration error: ADMIN_BASE_URL must be an http or https URL\n",
    )
    assert calls == []


def test_missing_database_url_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL")

    assert _run(AC1_ARGV, capsys) == (1, "", "configuration error: DATABASE_URL is required\n")


def test_commands_do_not_need_valkey_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("VALKEY_URL")
    _fake(monkeypatch, "issue_link", IssuedLink(USER, SECRET))

    assert _run(["user", "link", "--org", ORG_ARG, "--email", "a@b.example"], capsys) == (
        0,
        f"{LINK}\n",
        "",
    )
