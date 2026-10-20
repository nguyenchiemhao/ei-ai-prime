"""Credential rows against the real database: the reservation (the lockout rule in SQL), races,
boundaries, the lock duration, refund and reset."""

import asyncio
import dataclasses
import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ei_ai.auth.credentials import (
    Reservation,
    record_lockout,
    refund_attempt,
    reserve_attempt,
    reset_after_success,
    upsert_credential,
)
from ei_ai.auth.lockout import LOCK, MAX_FAILURES, WINDOW
from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.db.tenant import tenant_transaction
from support.tenants import FIXTURE_PASSWORD_HASH, OrgRows, TwoOrgs

pytestmark = pytest.mark.integration


async def _reserve(engine: AsyncEngine, org: OrgRows) -> Reservation | None:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        return await reserve_attempt(conn, org.org_id, org.user_id)


async def _fail(engine: AsyncEngine, org: OrgRows) -> bool:
    """One failed attempt as the sign-in counts it: the reservation stands, and the attempt that
    locked writes ``user.locked_out``. True when it just locked."""
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        reservation = await reserve_attempt(conn, org.org_id, org.user_id)
        if reservation is None or not reservation.just_locked:
            return False
        await record_lockout(conn, org.org_id, org.user_id)
        return True


async def _failures(engine: AsyncEngine, org: OrgRows, count: int) -> list[bool]:
    return [await _fail(engine, org) for _ in range(count)]


async def _row(engine: AsyncEngine, org: OrgRows) -> tuple[int, object, object]:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        row = (
            await conn.execute(
                text(
                    "SELECT failed_attempts, failure_window_started_at, locked_until"
                    " FROM user_credentials WHERE org_id = :org AND user_id = :user"
                ),
                {"org": org.org_id, "user": org.user_id},
            )
        ).one()
    return row.failed_attempts, row.failure_window_started_at, row.locked_until


async def _hash(engine: AsyncEngine, org_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        stored: str | None = (
            await conn.execute(
                text(
                    "SELECT password_hash FROM user_credentials"
                    " WHERE org_id = :org AND user_id = :user"
                ),
                {"org": org_id, "user": user_id},
            )
        ).scalar_one_or_none()
    return stored


async def _set(engine: AsyncEngine, org: OrgRows, assignments: str) -> None:
    """Move the credential's timestamps/counters with an UPDATE (never a mocked clock)."""
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        await conn.execute(
            text(f"UPDATE user_credentials SET {assignments} WHERE org_id = :org"),
            {"org": org.org_id},
        )


async def _locked_out_events(engine: AsyncEngine, org: OrgRows) -> list[str]:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        result = await conn.execute(
            text(
                "SELECT actor FROM audit_events WHERE org_id = :org"
                " AND action = 'user.locked_out' AND target_id = :user"
            ),
            {"org": org.org_id, "user": org.user_id},
        )
        return list(result.scalars())


async def _wait_for_a_row_lock_waiter(engine: AsyncEngine) -> None:
    """Until some transaction waits for a row lock (``pg_locks`` shows a lock not granted)."""
    for _ in range(500):
        async with engine.connect() as conn:
            waiting = (
                await conn.execute(text("SELECT count(*) FROM pg_locks WHERE NOT granted"))
            ).scalar_one()
            await conn.rollback()
        if waiting:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the second transaction never waited for the row lock")


async def test_reservation_hands_out_the_hash_and_counts_the_attempt(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a

    reservation = await _reserve(app_engine, a)

    assert reservation == Reservation(FIXTURE_PASSWORD_HASH, None, 0, None)
    assert reservation.just_locked is False
    attempts, window, locked_until = await _row(app_engine, a)
    assert attempts == 1 and window is not None and locked_until is None


async def test_reservation_without_a_credential_is_none(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        assert await reserve_attempt(conn, a.org_id, uuid.uuid4()) is None


async def test_fifth_failure_locks_for_exactly_15_minutes_and_audits_once(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    assert await _failures(app_engine, a, MAX_FAILURES - 1) == [False] * (MAX_FAILURES - 1)

    # now() is fixed per transaction: read in the locking transaction, the difference is exact.
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        reservation = await reserve_attempt(conn, a.org_id, a.user_id)
        assert reservation is not None and reservation.just_locked
        await record_lockout(conn, a.org_id, a.user_id)
        lock_left = (
            await conn.execute(
                text(
                    "SELECT locked_until - now() FROM user_credentials"
                    " WHERE org_id = :org AND user_id = :user"
                ),
                {"org": a.org_id, "user": a.user_id},
            )
        ).scalar_one()

    assert lock_left == LOCK == timedelta(minutes=15)
    attempts, window, locked_until = await _row(app_engine, a)
    assert (attempts, window) == (0, None)
    assert locked_until == reservation.locked_until
    assert await _locked_out_events(app_engine, a) == ["system"]


async def test_five_failures_over_16_minutes_do_not_lock(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    assert await _failures(app_engine, a, MAX_FAILURES - 1) == [False] * (MAX_FAILURES - 1)
    await _set(app_engine, a, "failure_window_started_at = now() - interval '16 minutes'")

    assert await _fail(app_engine, a) is False

    attempts, window, locked_until = await _row(app_engine, a)
    assert attempts == 1 and window is not None and locked_until is None
    assert await _locked_out_events(app_engine, a) == []


async def test_failure_exactly_at_the_window_edge_still_counts_inside_it(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    """``now()`` is fixed per transaction, so the window can be set to exactly 15:00 ago (and
    15:00 plus one microsecond) in the same transaction as the failure: SQL ``<=`` equals
    ``lockout.next_failure_state``'s ``now - started > WINDOW``."""
    a, b = two_orgs.a, two_orgs.b
    for org, extra, expected_locked in (
        (a, timedelta(0), True),
        (b, timedelta(microseconds=1), False),
    ):
        started_ago = WINDOW + extra
        async with app_engine.connect() as conn, tenant_transaction(conn, org.org_id):
            await conn.execute(
                text(
                    "UPDATE user_credentials SET failed_attempts = :n,"
                    " failure_window_started_at = now() - :ago WHERE org_id = :org"
                ),
                {"n": MAX_FAILURES - 1, "ago": started_ago, "org": org.org_id},
            )
            reservation = await reserve_attempt(conn, org.org_id, org.user_id)
            assert reservation is not None and reservation.just_locked is expected_locked


async def test_failure_after_the_lock_ends_counts_again(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await _failures(app_engine, a, MAX_FAILURES)
    await _set(app_engine, a, "locked_until = now() - interval '1 second'")

    assert await _fail(app_engine, a) is False

    assert (await _row(app_engine, a))[0] == 1


async def test_attempts_while_locked_are_refused_and_not_counted(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await _failures(app_engine, a, MAX_FAILURES)
    before = await _row(app_engine, a)

    assert [await _reserve(app_engine, a) for _ in range(3)] == [None] * 3

    assert await _row(app_engine, a) == before
    assert await _locked_out_events(app_engine, a) == ["system"]


async def test_concurrent_failures_are_both_counted(two_orgs: TwoOrgs) -> None:
    """Deterministic: the first transaction holds the row lock while the second one starts and
    waits for it; only then does the first commit."""
    a = two_orgs.a
    engine = create_async_engine(
        to_sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=3, max_overflow=0
    )
    try:
        await _set(engine, a, "failed_attempts = 3, failure_window_started_at = now()")

        async with engine.connect() as conn:
            async with tenant_transaction(conn, a.org_id):
                first = await reserve_attempt(conn, a.org_id, a.user_id)
                second_task = asyncio.create_task(_fail(engine, a))
                await _wait_for_a_row_lock_waiter(engine)
            second = await second_task

        # 3 + 2 = 5: a lost update would leave 4 and no lock.
        assert first is not None and first.just_locked is False
        assert second is True
        attempts, _, locked_until = await _row(engine, a)
        assert attempts == 0 and locked_until is not None
        assert await _locked_out_events(engine, a) == ["system"]
    finally:
        await engine.dispose()


async def test_reservation_for_another_organizations_user_is_none(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        assert await reserve_attempt(conn, a.org_id, b.user_id) is None

    assert (await _row(app_engine, b))[0] == 0


async def test_reset_after_success_clears_counters(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await _failures(app_engine, a, 2)
    reservation = await _reserve(app_engine, a)
    assert reservation is not None

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        assert await reset_after_success(conn, a.org_id, a.user_id, reservation)

    assert await _row(app_engine, a) == (0, None, None)


async def test_reset_after_success_fails_when_hash_changed(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    reservation = await _reserve(app_engine, a)
    assert reservation is not None
    stale = dataclasses.replace(reservation, password_hash="$argon2id$stale")

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        assert not await reset_after_success(conn, a.org_id, a.user_id, stale)

    assert (await _row(app_engine, a))[0] == 1


async def test_reset_after_success_fails_when_another_attempt_locked(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    """A right password whose reservation came before the locking one does not sign in."""
    a = two_orgs.a
    await _failures(app_engine, a, MAX_FAILURES - 2)
    earlier = await _reserve(app_engine, a)
    assert earlier is not None and not earlier.just_locked
    assert await _fail(app_engine, a) is True

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        assert not await reset_after_success(conn, a.org_id, a.user_id, earlier)

    assert (await _row(app_engine, a))[2] is not None


async def test_reset_after_success_lifts_the_lock_this_attempt_set(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    """The 5th attempt locks when it is reserved; if its password matches, it still signs in."""
    a = two_orgs.a
    await _failures(app_engine, a, MAX_FAILURES - 1)
    fifth = await _reserve(app_engine, a)
    assert fifth is not None and fifth.just_locked

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        assert await reset_after_success(conn, a.org_id, a.user_id, fifth)

    assert await _row(app_engine, a) == (0, None, None)
    assert await _locked_out_events(app_engine, a) == []


async def test_refund_takes_back_one_counted_attempt(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await _failures(app_engine, a, 2)
    before = await _row(app_engine, a)
    reservation = await _reserve(app_engine, a)
    assert reservation is not None

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await refund_attempt(conn, a.org_id, a.user_id, reservation)

    assert await _row(app_engine, a) == before


async def test_refund_of_the_first_attempt_closes_the_window(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    reservation = await _reserve(app_engine, a)
    assert reservation is not None

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await refund_attempt(conn, a.org_id, a.user_id, reservation)

    assert await _row(app_engine, a) == (0, None, None)


async def test_refund_of_the_locking_attempt_restores_the_counters(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await _failures(app_engine, a, MAX_FAILURES - 1)
    before = await _row(app_engine, a)
    fifth = await _reserve(app_engine, a)
    assert fifth is not None and fifth.just_locked

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await refund_attempt(conn, a.org_id, a.user_id, fifth)

    assert await _row(app_engine, a) == before
    assert before[0] == MAX_FAILURES - 1 and before[2] is None


async def test_refund_leaves_a_lock_of_another_attempt(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await _failures(app_engine, a, MAX_FAILURES - 2)
    earlier = await _reserve(app_engine, a)
    assert earlier is not None
    assert await _fail(app_engine, a) is True
    locked = await _row(app_engine, a)

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await refund_attempt(conn, a.org_id, a.user_id, earlier)

    assert await _row(app_engine, a) == locked


async def test_upsert_credential_replaces_hash_and_clears_lock(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await _failures(app_engine, a, MAX_FAILURES)
    new_hash = "$argon2id$new"

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await upsert_credential(conn, a.org_id, a.user_id, new_hash)

    assert await _hash(app_engine, a.org_id, a.user_id) == new_hash
    assert await _row(app_engine, a) == (0, None, None)


async def test_upsert_credential_inserts_for_a_user_without_one(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        user_id = (
            await conn.execute(
                text(
                    "INSERT INTO users (org_id, email, display_name)"
                    " VALUES (:org, :email, 'New') RETURNING id"
                ),
                {"org": a.org_id, "email": f"new.{uuid.uuid4().hex[:8]}@example.invalid"},
            )
        ).scalar_one()
        await upsert_credential(conn, a.org_id, user_id, "$argon2id$first")

    assert await _hash(app_engine, a.org_id, user_id) == "$argon2id$first"
