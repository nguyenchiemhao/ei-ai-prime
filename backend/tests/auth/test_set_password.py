import hashlib
import re
import secrets
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import pytest

from ei_ai.auth.set_password import (
    LINK_TTL,
    format_token,
    hash_secret,
    issue_token,
    new_secret,
    parse_token,
    set_password_link,
)

ORG = uuid.UUID("0192a000-0000-7000-8000-00000000ea21")
SECRET = "A" * 21 + "b" * 20 + "_-"


def test_link_is_valid_24_hours() -> None:
    assert timedelta(hours=24) == LINK_TTL


def test_new_secret_is_43_urlsafe_chars_and_unique() -> None:
    first, second = new_secret(), new_secret()

    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", second)
    assert first != second


def test_hash_is_sha256_hex_of_the_secret() -> None:
    digest = hash_secret(SECRET)

    assert digest == hashlib.sha256(SECRET.encode("utf-8")).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest != SECRET


def test_token_is_org_id_dot_secret_and_round_trips() -> None:
    token = format_token(ORG, SECRET)

    assert token == f"{ORG}.{SECRET}"
    assert parse_token(token) == (ORG, SECRET)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "abc",
        str(ORG),
        f"{ORG}.",
        f"not-a-uuid.{SECRET}",
        f"{str(ORG)[:-1]}.{SECRET}",
        f"{ORG}.{SECRET[:42]}",
        f"{ORG}.{SECRET}x",
        f"{ORG}.{SECRET[:42]}/",
        f"{ORG}.{SECRET[:42]}.",
        f".{SECRET}",
    ],
)
def test_parse_rejects_malformed(token: str) -> None:
    assert parse_token(token) is None


def test_link_points_at_set_password_on_the_admin_url() -> None:
    link = set_password_link("http://localhost:3000", ORG, SECRET)

    assert link == f"http://localhost:3000/set-password#token={ORG}.{SECRET}"


def test_token_sits_in_the_fragment_never_in_path_or_query() -> None:
    # A fragment is never sent to a server: no access log, proxy or Referer sees the secret.
    parts = urlsplit(set_password_link("https://admin.example.com", ORG, SECRET))

    assert parts.path == "/set-password"
    assert parts.query == ""
    assert parts.fragment == f"token={ORG}.{SECRET}"
    assert SECRET not in f"{parts.scheme}://{parts.netloc}{parts.path}?{parts.query}"


def test_new_secret_comes_from_the_os_csprng(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int | None] = []

    def spy(nbytes: int | None = None) -> str:
        calls.append(nbytes)
        return "C" * 43

    monkeypatch.setattr(secrets, "token_urlsafe", spy)

    assert new_secret() == "C" * 43
    assert calls == [32]


async def test_issue_token_binds_link_ttl_for_the_expiry() -> None:
    class _FakeConnection:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def execute(self, statement: Any, params: dict[str, Any]) -> None:
            self.calls.append((str(statement), params))

    conn = _FakeConnection()

    secret = await issue_token(conn, ORG, ORG)  # type: ignore[arg-type]

    insert_sql, insert_params = conn.calls[-1]
    assert insert_sql.startswith("INSERT INTO set_password_tokens")
    assert "now() + :ttl" in insert_sql
    assert insert_params["ttl"] == LINK_TTL
    assert insert_params["hash"] == hash_secret(secret)
