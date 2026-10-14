import pytest

from ei_ai.db import migrate


def test_alembic_config_points_at_the_packaged_migrations_and_keeps_percent_signs() -> None:
    config = migrate.alembic_config("postgresql://ei_ai_migrator:p%40ss@db:5432/ei_ai")

    assert config.get_main_option("script_location") == "ei_ai.db:migrations"
    assert config.get_main_option("sqlalchemy.url") == (
        "postgresql://ei_ai_migrator:p%40ss@db:5432/ei_ai"
    )


@pytest.mark.parametrize("environment", ["production", "", "staging"])
def test_roundtrip_is_refused_outside_local_and_test(
    monkeypatch: pytest.MonkeyPatch, environment: str, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EI_AI_ENV", environment)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://ei_ai_migrator:s3cret-pw@db/ei_ai")

    def must_not_run(url: str) -> None:
        raise AssertionError("the round trip must not touch the database")

    monkeypatch.setattr(migrate, "downgrade_base", must_not_run)

    assert migrate.main(["roundtrip"]) == 2
    assert "s3cret-pw" not in capsys.readouterr().err


def test_roundtrip_downgrades_then_upgrades_in_test(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setenv("EI_AI_ENV", "test")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://ei_ai_migrator:pw@db/ei_ai")
    monkeypatch.setattr(migrate, "downgrade_base", lambda url: calls.append("down"))
    monkeypatch.setattr(migrate, "upgrade_head", lambda url: calls.append("up"))

    assert migrate.main(["roundtrip"]) == 0
    assert calls == ["down", "up"]


def test_unknown_subcommand_is_a_usage_error() -> None:
    assert migrate.main(["nope"]) == 2
