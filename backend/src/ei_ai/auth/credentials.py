"""Rows of ``user_credentials``: the attempt reservation (lockout bookkeeping), its refund, the
reset on success, and the upsert.

A sign-in attempt is counted before its password is checked (reserve, then refund): the
reservation applies the failure rule to an unlocked credential and hands out the hash, so
parallel attempts cannot all be checked before the 5th failure is recorded (AC3); an attempt
that finds the account locked is refused unchecked. A match resets the counters, and the other
candidates of the same email get their reservation back (R19). No lock is held while hashing
(R43): each step is its own short transaction.

Every function runs inside the caller's tenant transaction and filters by ``org_id`` explicitly
(D46). Nothing here logs a hash; ``reserve_attempt`` hands it only to the verifier.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.audit.events import SYSTEM_ACTOR, USER_LOCKED_OUT, record_event
from ei_ai.auth.lockout import LOCK, MAX_FAILURES, WINDOW


@dataclass(frozen=True)
class Reservation:
    """One attempt, counted as a failure until its password matches.

    ``locked_until`` is the lock this attempt set (it took the last slot), else None; the
    counters before it let a refund restore them exactly.
    """

    password_hash: str
    locked_until: datetime | None
    attempts_before: int
    window_before: datetime | None

    @property
    def just_locked(self) -> bool:
        return self.locked_until is not None


_UNLOCKED = "(locked_until IS NULL OR locked_until <= now())"

# Takes the row lock (for the rest of this short transaction) and reads the counters the
# reservation will change; a row that is locked, or locked by a concurrent attempt meanwhile,
# gives no row.
_LOCK_ROW = f"""
SELECT failed_attempts, failure_window_started_at FROM user_credentials
WHERE org_id = :org AND user_id = :user AND {_UNLOCKED}
FOR UPDATE
"""

# The rule of ``lockout.next_failure_state`` in one statement, written against the target row only
# (no sub-select), so every expression is evaluated on the latest committed row. A failure more
# than WINDOW after the window opened (or with no window) restarts at 1, otherwise counts up
# (``<=``: exactly WINDOW is still inside, like ``now - started > WINDOW`` in Python); reaching
# MAX_FAILURES sets the lock and resets the counters. ``failed_attempts = 0`` after it means
# "this attempt locked".
_IN_WINDOW = (
    "(failure_window_started_at IS NOT NULL AND now() - failure_window_started_at <= :window)"
)
_ATTEMPTS = f"(CASE WHEN {_IN_WINDOW} THEN failed_attempts + 1 ELSE 1 END)"
_RESERVE = f"""
UPDATE user_credentials SET
    failed_attempts = CASE WHEN {_ATTEMPTS} >= :max THEN 0 ELSE {_ATTEMPTS} END,
    failure_window_started_at = CASE
        WHEN {_ATTEMPTS} >= :max THEN NULL
        WHEN {_IN_WINDOW} THEN failure_window_started_at
        ELSE now() END,
    locked_until = CASE WHEN {_ATTEMPTS} >= :max THEN now() + :lock ELSE locked_until END
WHERE org_id = :org AND user_id = :user AND {_UNLOCKED}
RETURNING password_hash, CASE WHEN failed_attempts = 0 THEN locked_until END AS own_lock
"""

_OWN_LOCK = "locked_until = CAST(:own_lock AS timestamptz)"

# The lock this attempt set: restore the counters it replaced. Otherwise take one attempt back
# (a window left empty closes); a lock set by another attempt stays.
_REFUND = f"""
UPDATE user_credentials SET
    failed_attempts = CASE WHEN {_OWN_LOCK} THEN :attempts_before ELSE failed_attempts - 1 END,
    failure_window_started_at = CASE
        WHEN {_OWN_LOCK} THEN CAST(:window_before AS timestamptz)
        WHEN failed_attempts = 1 THEN NULL
        ELSE failure_window_started_at END,
    locked_until = CASE WHEN {_OWN_LOCK} THEN NULL ELSE locked_until END
WHERE org_id = :org AND user_id = :user
    AND ({_OWN_LOCK} OR ({_UNLOCKED} AND failed_attempts > 0))
"""


async def reserve_attempt(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID
) -> Reservation | None:
    """Count one attempt before its password is checked; the hash to check it against. None when
    the user never set a password or the account is locked: the attempt cannot match and is not
    counted (R9)."""
    params = {"org": org_id, "user": user_id}
    before = (await conn.execute(text(_LOCK_ROW), params)).one_or_none()
    if before is None:
        return None
    row = (
        await conn.execute(
            text(_RESERVE), {**params, "window": WINDOW, "lock": LOCK, "max": MAX_FAILURES}
        )
    ).one()
    return Reservation(
        row.password_hash, row.own_lock, before.failed_attempts, before.failure_window_started_at
    )


async def refund_attempt(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID, reservation: Reservation
) -> None:
    """Give back a reservation whose attempt matched another candidate (R19)."""
    await conn.execute(
        text(_REFUND),
        {
            "org": org_id,
            "user": user_id,
            "own_lock": reservation.locked_until,
            "attempts_before": reservation.attempts_before,
            "window_before": reservation.window_before,
        },
    )


async def reset_after_success(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID, reservation: Reservation
) -> bool:
    """Clear the counters and the lock if the hash is still the one that matched and the account
    is not locked, except by this attempt's own reservation. False means the password changed or
    another attempt locked the account meanwhile (the attempt stays a failure)."""
    result = await conn.execute(
        text(
            "UPDATE user_credentials"
            " SET failed_attempts = 0, failure_window_started_at = NULL, locked_until = NULL"
            " WHERE org_id = :org AND user_id = :user AND password_hash = :hash"
            f" AND ({_UNLOCKED} OR {_OWN_LOCK})"
        ),
        {
            "org": org_id,
            "user": user_id,
            "hash": reservation.password_hash,
            "own_lock": reservation.locked_until,
        },
    )
    return bool(result.rowcount == 1)


async def record_lockout(conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Audit ``user.locked_out`` (actor ``system``) for the failed attempt that locked."""
    await record_event(conn, org_id, SYSTEM_ACTOR, USER_LOCKED_OUT, "user", user_id)


async def upsert_credential(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID, password_hash: str
) -> None:
    """Store a new hash and clear the failure counters and the lock."""
    await conn.execute(
        text(
            "INSERT INTO user_credentials (org_id, user_id, password_hash)"
            " VALUES (:org, :user, :hash)"
            " ON CONFLICT (org_id, user_id) DO UPDATE SET"
            " password_hash = EXCLUDED.password_hash, password_set_at = now(),"
            " failed_attempts = 0, failure_window_started_at = NULL, locked_until = NULL"
        ),
        {"org": org_id, "user": user_id, "hash": password_hash},
    )
