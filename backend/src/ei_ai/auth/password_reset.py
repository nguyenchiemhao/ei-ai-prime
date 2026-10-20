"""Forgot password: a reset link for every account of an email (EA-22, R16, R45).

Local and test only. The prototype has no mail, so the link is printed to stdout, once, on one
line that carries no email and no wording about credentials. Other environments issue nothing.
Each account's token and audit event commit in that account's own tenant transaction (D46); the
directory lookup is the only cross-tenant read. ``issue_token`` replaces the user's older unused
links, so only the newest link works (R45).
"""

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import SYSTEM_ACTOR, USER_SET_PASSWORD_LINK_ISSUED, record_event
from ei_ai.auth.directory import SignInDirectory
from ei_ai.auth.set_password import format_token, issue_token
from ei_ai.auth.sign_in import normalise_email
from ei_ai.db.tenant import tenant_transaction

PRINTING_ENVIRONMENTS = frozenset({"local", "test"})


async def request_reset(
    engine: AsyncEngine,
    directory: SignInDirectory,
    email: str,
    environment: str,
    base_url: str,
) -> None:
    """Issue and print one link per account found; nothing at all outside local/test."""
    if environment not in PRINTING_ENVIRONMENTS:
        return
    for account in await directory.find_accounts(normalise_email(email)):
        async with engine.connect() as conn, tenant_transaction(conn, account.org_id):
            secret = await issue_token(conn, account.org_id, account.user_id)
            await record_event(
                conn,
                account.org_id,
                SYSTEM_ACTOR,
                USER_SET_PASSWORD_LINK_ISSUED,
                "user",
                account.user_id,
            )
        token = format_token(account.org_id, secret)
        print(f"Reset link (valid 24 h, shown once): {base_url}/reset#token={token}", flush=True)
