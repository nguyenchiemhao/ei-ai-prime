import pytest

from ei_ai.seed.demo import SeedRefused, load_manifest, run_demo_seed


def _reachable() -> None:
    return None


def test_manifest_holds_mekong_devworks_people_ops_and_six_members() -> None:
    manifest = load_manifest()

    assert manifest.organization == "Mekong Devworks"
    assert manifest.workspace == "People Ops"
    assert [member.name for member in manifest.members] == [
        "Linh Tran",
        "Minh Pham",
        "Thao Nguyen",
        "Quang Le",
        "Hà Vũ",
        "Son Hoang",
    ]
    assert manifest.members[0].roles == ["Org Admin", "Workspace Admin"]
    assert all(member.email.endswith("@mekongdevworks.example") for member in manifest.members)


@pytest.mark.parametrize("environment", ["production", "staging", ""])
def test_refuses_outside_local_and_test(environment: str) -> None:
    called: list[str] = []

    with pytest.raises(SeedRefused):
        run_demo_seed(environment, lambda: called.append("db"))

    assert called == [], "the guard must run before any database access"


@pytest.mark.parametrize("environment", ["local", "test"])
def test_runs_in_local_and_test(environment: str) -> None:
    summary = run_demo_seed(environment, _reachable)

    assert "Mekong Devworks" in summary
    assert "People Ops" in summary
    assert "Members: 6" in summary


def test_second_run_prints_the_same_summary() -> None:
    assert run_demo_seed("local", _reachable) == run_demo_seed("local", _reachable)


def test_summary_says_rows_come_from_fnd04() -> None:
    summary = run_demo_seed("local", _reachable)

    assert "FND-04" in summary
    assert "EA-21" in summary
    assert "no rows" in summary.lower()


def test_database_failure_propagates() -> None:
    def unreachable() -> None:
        raise ConnectionError("db down")

    with pytest.raises(ConnectionError):
        run_demo_seed("local", unreachable)
