import pytest

from ei_ai import cli
from ei_ai.db.migrations.roles import MigrationRoleError
from ei_ai.db.schema_guard import Violation
from ei_ai.provisioning.validation import ProvisioningError
from ei_ai.seed.demo import DemoManifest

ENV = {
    "DATABASE_URL": "postgresql://ei_ai_app:s3cret-pw@db:5432/ei_ai",
    "VALKEY_URL": "redis://valkey:6379/0",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, environment: str) -> None:
    monkeypatch.setenv("EI_AI_ENV", environment)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


def _must_not_load(env: object, manifests: tuple[DemoManifest, ...]) -> str:
    raise AssertionError("the environment guard must run before settings or the database")


def test_seed_demo_prints_summary_and_exits_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_env(monkeypatch, "local")
    loaded: list[list[str]] = []

    def load(env: object, manifests: tuple[DemoManifest, ...]) -> str:
        loaded.append([manifest.organization for manifest in manifests])
        return "Demo seed: Mekong Devworks\n  Members: 10\nDemo seed: Sông Hàn Retail\n  Members: 2"

    monkeypatch.setattr(cli, "load_demo_data", load)

    assert cli.main(["seed", "demo"]) == 0
    captured = capsys.readouterr()
    assert "Members: 10" in captured.out
    assert "Demo seed: Sông Hàn Retail" in captured.out
    assert captured.err == ""
    assert loaded == [["Mekong Devworks", "Sông Hàn Retail"]]


@pytest.mark.parametrize("admin_url", [None, ""])
@pytest.mark.parametrize("database_url", [None, ENV["DATABASE_URL"]])
def test_seed_demo_exits_2_in_production(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    admin_url: str | None,
    database_url: str | None,
) -> None:
    _set_env(monkeypatch, "production")
    if database_url is None:
        monkeypatch.delenv("DATABASE_URL")
    monkeypatch.delenv("ADMIN_BASE_URL", raising=False)
    if admin_url is not None:
        monkeypatch.setenv("ADMIN_BASE_URL", admin_url)
    monkeypatch.setattr(cli, "load_demo_data", _must_not_load)

    assert cli.main(["seed", "demo"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "refused: the demo seed runs only in local or test environments\n"


def test_seed_demo_is_refused_when_the_environment_is_unset(
    clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env.setattr(cli, "load_demo_data", _must_not_load)

    assert cli.main(["seed", "demo"]) == 2
    assert "local or test" in capsys.readouterr().err


def test_seed_demo_exits_1_when_database_is_unreachable_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_env(monkeypatch, "local")

    def unreachable(env: object, manifests: tuple[DemoManifest, ...]) -> str:
        raise ConnectionError(f"cannot reach {ENV['DATABASE_URL']}")

    monkeypatch.setattr(cli, "load_demo_data", unreachable)

    assert cli.main(["seed", "demo"]) == 1
    captured = capsys.readouterr()
    assert captured.err == "error: seed demo failed (ConnectionError)\n"
    assert "s3cret-pw" not in captured.out + captured.err


def test_seed_demo_prints_a_provisioning_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_env(monkeypatch, "local")
    message = 'an Organization named "Mekong Devworks" already exists with another id'

    def taken(env: object, manifests: tuple[DemoManifest, ...]) -> str:
        raise ProvisioningError(message)

    monkeypatch.setattr(cli, "load_demo_data", taken)

    assert cli.main(["seed", "demo"]) == 1
    assert capsys.readouterr().err == f"error: {message}\n"


def test_missing_settings_exit_1_and_name_the_variable(
    clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env.setenv("EI_AI_ENV", "local")

    assert cli.main(["seed", "demo"]) == 1
    assert capsys.readouterr().err == "configuration error: DATABASE_URL is required\n"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "EI_AI_SEED_PASSWORD is required"),
        ("", "EI_AI_SEED_PASSWORD is required"),
        ("Q" * 129, "EI_AI_SEED_PASSWORD must be at most 128 characters"),
    ],
)
def test_seed_password_problems_are_configuration_errors_without_the_value(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: str | None,
    message: str,
) -> None:
    _set_env(monkeypatch, "local")
    monkeypatch.delenv("EI_AI_SEED_PASSWORD", raising=False)
    if value is not None:
        monkeypatch.setenv("EI_AI_SEED_PASSWORD", value)

    assert cli.main(["seed", "demo"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"configuration error: {message}\n"
    if value:
        assert value not in captured.err


def test_the_seed_no_longer_reads_the_admin_base_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_env(monkeypatch, "local")
    monkeypatch.delenv("EI_AI_SEED_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_BASE_URL", "admin.example.com")

    assert cli.main(["seed", "demo"]) == 1
    assert capsys.readouterr().err == "configuration error: EI_AI_SEED_PASSWORD is required\n"


def test_unknown_command_exits_2() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["nope"])

    assert exit_info.value.code == 2


MIGRATION_URL = "postgresql://ei_ai_migrator:s3cret-pw@db:5432/ei_ai"


def _set_migration_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EI_AI_ENV", "local")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", MIGRATION_URL)


def test_db_upgrade_exits_0_and_prints_the_guard_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_migration_env(monkeypatch)
    upgraded: list[str] = []
    monkeypatch.setattr(cli, "upgrade_head", upgraded.append)
    monkeypatch.setattr(cli, "current_revision", lambda url: "0001")
    monkeypatch.setattr(cli, "guard_violations", lambda url: [])

    assert cli.main(["db", "upgrade"]) == 0

    out = capsys.readouterr().out
    assert upgraded == [MIGRATION_URL]
    assert "database revision: 0001" in out
    assert "schema guard: 0 violations" in out


def test_db_upgrade_exits_1_when_guard_reports_violations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_migration_env(monkeypatch)
    monkeypatch.setattr(cli, "upgrade_head", lambda url: None)
    monkeypatch.setattr(cli, "current_revision", lambda url: "0001")
    monkeypatch.setattr(
        cli,
        "guard_violations",
        lambda url: [
            Violation("G12", "guard_probe", "no org_id column"),
            Violation("G2", "t", "x"),
        ],
    )

    assert cli.main(["db", "upgrade"]) == 1

    captured = capsys.readouterr()
    assert "G12 guard_probe" in captured.err
    assert "G2 t" in captured.err
    assert "0 violations" not in captured.out


def test_db_upgrade_exits_1_naming_the_missing_variable(
    clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["db", "upgrade"]) == 1
    assert "MIGRATION_DATABASE_URL" in capsys.readouterr().err


def test_db_upgrade_failure_prints_the_exception_class_never_the_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_migration_env(monkeypatch)

    def refused(url: str) -> None:
        raise ConnectionError(f"cannot reach {url}")

    monkeypatch.setattr(cli, "upgrade_head", refused)

    assert cli.main(["db", "upgrade"]) == 1
    captured = capsys.readouterr()
    assert "ConnectionError" in captured.err
    assert "s3cret-pw" not in captured.out + captured.err


def test_db_current_prints_the_revision(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_migration_env(monkeypatch)
    monkeypatch.setattr(cli, "current_revision", lambda url: "0001")

    assert cli.main(["db", "current"]) == 0
    assert "database revision: 0001" in capsys.readouterr().out


def test_db_current_failure_prints_the_exception_class_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_migration_env(monkeypatch)

    def refused(url: str) -> str:
        raise ConnectionError(f"cannot reach {url}")

    monkeypatch.setattr(cli, "current_revision", refused)

    assert cli.main(["db", "current"]) == 1
    assert "s3cret-pw" not in capsys.readouterr().err


def test_db_upgrade_prints_the_message_of_a_refused_migration_role(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_migration_env(monkeypatch)

    def refused(url: str) -> None:
        raise MigrationRoleError("migrations must run as the owner role ei_ai_migrator")

    monkeypatch.setattr(cli, "upgrade_head", refused)

    assert cli.main(["db", "upgrade"]) == 1
    captured = capsys.readouterr()
    assert "ei_ai_migrator" in captured.err
    assert "s3cret-pw" not in captured.out + captured.err
