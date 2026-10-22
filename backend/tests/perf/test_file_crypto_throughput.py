"""NFR (EA-20): encrypting and decrypting a 50 MiB file takes less than 1.5 s.

Run with ``npm run backend -- bench-crypto`` (excluded from the unit and integration runs).

One fixture Organization (with its data key) and one ``OrgFileStore`` in a temporary directory.
``put`` (encrypt, write, fsync) and ``get`` (read, decrypt) each run once as a warm-up and five
times timed on 50 MiB of random bytes; the median of the timed runs is compared with the limit.
"""

import os
import statistics
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ei_ai.crypto.cipher import OrgCipher
from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.db.tenant import tenant_transaction
from ei_ai.storage.files import OrgFileStore
from ei_ai.tenancy.context import TenantContext
from support.crypto import TEST_MASTER_KEY
from support.tenants import OrgRows, create_org_rows, purge_org_rows

pytestmark = pytest.mark.benchmark

SIZE = 50 * 1024 * 1024
WARMUP = 1
RUNS = 5
LIMIT_MS = 1500.0


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(to_sqlalchemy_url(os.environ["DATABASE_URL"]), pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def org(engine: AsyncEngine) -> AsyncIterator[OrgRows]:
    rows = await create_org_rows(engine, "CryptoBench")
    try:
        yield rows
    finally:
        await purge_org_rows(engine, rows)


async def test_50_mib_put_and_get_each_under_1_5_s(
    engine: AsyncEngine, org: OrgRows, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    tenant = TenantContext(org_id=org.org_id, user_id=org.user_id)
    store = OrgFileStore(tmp_path, OrgCipher(TEST_MASTER_KEY))
    data = os.urandom(SIZE)
    puts: list[float] = []
    gets: list[float] = []
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        for run in range(WARMUP + RUNS):
            started = time.perf_counter()
            file_id = await store.put(conn, tenant, data)
            put_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            restored = await store.get(conn, tenant, file_id)
            get_ms = (time.perf_counter() - started) * 1000
            assert restored == data
            await store.delete(tenant, file_id)
            if run >= WARMUP:
                puts.append(put_ms)
                gets.append(get_ms)
    put_median = statistics.median(puts)
    get_median = statistics.median(gets)
    line = (
        f"file crypto 50 MiB: put_median_ms={put_median:.1f} get_median_ms={get_median:.1f}"
        f" runs={RUNS}"
    )
    # The reporter starts a new line only when the cursor is not at one: no blank line before.
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        print(line)
    else:
        reporter.write_line(line)
    assert put_median < LIMIT_MS
    assert get_median < LIMIT_MS
