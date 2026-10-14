import pytest

from ei_ai import cli

ENV = {
    "DATABASE_URL": "postgresql://ei_ai_app:s3cret-pw@db:5432/ei_ai",
    "VALKEY_URL": "redis://valkey:6379/0",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, environment: str) -> None:
    monkeypatch.setenv("EI_AI_ENV", environment)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


def test_seed_demo_prints_summary_and_exits_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_env(monkeypatch, "local")
    monkeypatch.setattr(cli, "check_database_sync", lambda url: None)

    assert cli.main(["seed", "demo"]) == 0
    assert "Members: 6" in capsys.readouterr().out


def test_seed_demo_exits_2_in_production(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_env(monkeypatch, "production")

    assert cli.main(["seed", "demo"]) == 2
    captured = capsys.readouterr()
    assert "local or test" in captured.err
    assert "s3cret-pw" not in captured.out + captured.err


def test_seed_demo_exits_1_when_database_is_unreachable_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_env(monkeypatch, "local")

    def unreachable(url: str) -> None:
        raise ConnectionError(f"cannot reach {url}")

    monkeypatch.setattr(cli, "check_database_sync", unreachable)

    assert cli.main(["seed", "demo"]) == 1
    captured = capsys.readouterr()
    assert "ConnectionError" in captured.err
    assert "s3cret-pw" not in captured.out + captured.err


def test_missing_settings_exit_1_and_name_the_variable(
    clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["seed", "demo"]) == 1
    assert "DATABASE_URL" in capsys.readouterr().err


def test_unknown_command_exits_2() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["nope"])

    assert exit_info.value.code == 2
