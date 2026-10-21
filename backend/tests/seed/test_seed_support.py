from pathlib import Path

import pytest

from support import seed as seed_support

ENV_NAME = "EI_AI_SEED_PASSWORD"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(seed_support, "_REPO_ROOT", tmp_path)
    monkeypatch.delenv(ENV_NAME, raising=False)
    return tmp_path


def test_demo_seed_password_prefers_the_environment(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / ".env").write_text(f"{ENV_NAME}=From-Dotenv-1\n", "utf-8")
    (repo / ".env.example").write_text(f"{ENV_NAME}=From-Example-1\n", "utf-8")
    monkeypatch.setenv(ENV_NAME, "From-Env-Var-1")

    assert seed_support.demo_seed_password() == "From-Env-Var-1"


def test_demo_seed_password_uses_dotenv_before_the_example(repo: Path) -> None:
    (repo / ".env").write_text(f"# note\n{ENV_NAME}=From-Dotenv-1\n", "utf-8")
    (repo / ".env.example").write_text(f"{ENV_NAME}=From-Example-1\n", "utf-8")

    assert seed_support.demo_seed_password() == "From-Dotenv-1"


def test_demo_seed_password_falls_back_to_the_example_then_the_test_value(repo: Path) -> None:
    (repo / ".env").write_text("OTHER=1\n", "utf-8")
    (repo / ".env.example").write_text(f"{ENV_NAME}=From-Example-1\n", "utf-8")
    assert seed_support.demo_seed_password() == "From-Example-1"

    (repo / ".env.example").unlink()
    assert seed_support.demo_seed_password() == seed_support.TEST_SEED_PASSWORD
