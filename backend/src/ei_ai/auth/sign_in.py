"""Signing in with email + password, and signing out (spec Flows "Sign-in", "Sign-out").

The directory names the candidate accounts (the only cross-tenant read, R42); everything after
runs as ``ei_ai_app`` in the candidate Organization's tenant transaction with an explicit
``org_id`` (D46). Transaction boundaries are fixed and no lock is held while hashing (R43): per
candidate a committed reservation that counts the attempt before its password is checked
(reserve, then refund: parallel attempts cannot exceed the 5 guesses of AC3), the Argon2 verify
outside any transaction, then one success transaction that also gives the other candidates their
reservation back, or, when nothing matched, the reservations stand as the failures.
Every rejection is the same ``None``, whatever the reason (AC2). Nothing here logs (D52).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import USER_SIGNED_IN, USER_SIGNED_OUT, record_event, user_actor
from ei_ai.auth.credentials import (
    Reservation,
    record_lockout,
    refund_attempt,
    reserve_attempt,
    reset_after_success,
)
from ei_ai.auth.directory import Account, SignInDirectory
from ei_ai.auth.passwords import dummy_verify, verify_password
from ei_ai.auth.sessions import create_session, delete_session
from ei_ai.auth.tokens import parse_token
from ei_ai.db.tenant import tenant_transaction
from ei_ai.workspaces.memberships import default_workspace_id


@dataclass(frozen=True)
class SignedIn:
    org_id: uuid.UUID
    user_id: uuid.UUID
    cookie: str
    default_workspace_id: uuid.UUID | None


def normalise_email(email: str) -> str:
    """The stored form of an email (the ``users`` CHECK): no surrounding spaces, lower case."""
    return email.strip().lower()


async def _reserve(engine: AsyncEngine, account: Account) -> Reservation | None:
    """Count the attempt on the account before checking it; None when it cannot match (no
    password, or locked: refused unchecked). Committed before any hashing."""
    async with engine.connect() as conn, tenant_transaction(conn, account.org_id):
        return await reserve_attempt(conn, account.org_id, account.user_id)


async def _refund(engine: AsyncEngine, account: Account, reservation: Reservation) -> None:
    async with engine.connect() as conn, tenant_transaction(conn, account.org_id):
        await refund_attempt(conn, account.org_id, account.user_id, reservation)


async def _record_lockout(engine: AsyncEngine, account: Account) -> None:
    async with engine.connect() as conn, tenant_transaction(conn, account.org_id):
        await record_lockout(conn, account.org_id, account.user_id)


async def _delete_session(engine: AsyncEngine, cookie: str, audit: bool) -> bool:
    """Delete the cookie's session inside the cookie's Organization, auditing ``user.signed_out``
    if asked; False when there was none (a malformed cookie, or a secret presented with another
    Organization's id, finds nothing)."""
    parsed = parse_token(cookie)
    if parsed is None:
        return False
    org_id, secret = parsed
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        user_id = await delete_session(conn, org_id, secret)
        if user_id is None:
            return False
        if audit:
            await record_event(conn, org_id, user_actor(user_id), USER_SIGNED_OUT, "user", user_id)
    return True


async def _succeed(
    engine: AsyncEngine, account: Account, reservation: Reservation
) -> SignedIn | None:
    """The success transaction: reset the counters (only if the hash checked still matches and no
    other attempt locked the account meanwhile), open a session and audit it. None means it no
    longer matches, and the attempt stays a failure."""
    org_id, user_id = account.org_id, account.user_id
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        if not await reset_after_success(conn, org_id, user_id, reservation):
            return None
        cookie = await create_session(conn, org_id, user_id)
        await record_event(conn, org_id, user_actor(user_id), USER_SIGNED_IN, "user", user_id)
        default = await default_workspace_id(conn, org_id, user_id)
    return SignedIn(org_id, user_id, cookie, default)


async def sign_in(
    engine: AsyncEngine,
    directory: SignInDirectory,
    email: str,
    password: str,
    previous_cookie: str | None,
) -> SignedIn | None:
    """A new session for the first candidate (in Organization id order) whose password matches;
    later candidates are neither reserved nor verified, and the earlier ones get their
    reservation back (R19). None when nothing matched: then every candidate with an unlocked
    credential keeps one counted failure, and the one that locked writes ``user.locked_out``.
    When no candidate had a hash to verify, one dummy verify keeps the timing of a wrong password
    (R11). On a match the request's previous session is deleted first (R8)."""
    reserved: list[tuple[Account, Reservation]] = []
    for account in await directory.find_accounts(normalise_email(email)):
        reservation = await _reserve(engine, account)
        if reservation is None:
            continue  # cannot match and is not counted (R9)
        reserved.append((account, reservation))
        if not await verify_password(reservation.password_hash, password):
            continue
        if previous_cookie is not None:
            await _delete_session(engine, previous_cookie, audit=False)
        signed_in = await _succeed(engine, account, reservation)
        if signed_in is not None:
            for other, other_reservation in reserved[:-1]:
                await _refund(engine, other, other_reservation)
            return signed_in
    if not reserved:
        await dummy_verify()
    for account, reservation in reserved:
        if reservation.just_locked:
            await _record_lockout(engine, account)
    return None


async def sign_out(engine: AsyncEngine, cookie: str) -> bool:
    """Delete the cookie's session and audit ``user.signed_out``; False when there was none."""
    return await _delete_session(engine, cookie, audit=True)
