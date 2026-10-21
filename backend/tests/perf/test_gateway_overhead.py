"""NFR (EA-24): the Model Gateway adds less than 20 ms per call.

Run with ``npm run backend -- bench-gateway`` (excluded from the unit and integration runs).

The same non-streaming chat request runs 100 times (after 10 warm-up calls), alternating between
(a) the OpenAI SDK straight to the fake model server and (b) ``ModelGateway`` with the real
``DbCatalog`` (tenant transaction on PostgreSQL), the ``GET /v1/models`` pin check and the
``LoggingObserver``. The added time is median(b) - median(a); p95 is printed for information.
The fake server answers at once, so the numbers are the gateway's own cost.
"""

import os
import statistics
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import httpx2
import openai
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.factory import build_gateway
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.model_gateway.results import ChatMessage
from ei_ai.settings import ModelSettings
from support.fake_model_server import FakeModelServer, running_fake_model_server
from support.tenants import (
    FIXTURE_MODEL_ID,
    FIXTURE_MODEL_VERSION,
    OrgRows,
    create_org_rows,
    purge_org_rows,
)

pytestmark = pytest.mark.benchmark

WARMUP = 10
RUNS = 100
MAX_OVERHEAD_MS = 20.0
MESSAGES = [{"role": "user", "content": "hi"}]


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(to_sqlalchemy_url(os.environ["DATABASE_URL"]), pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def org(engine: AsyncEngine) -> AsyncIterator[OrgRows]:
    rows = await create_org_rows(engine, "Bench")
    try:
        yield rows
    finally:
        await purge_org_rows(engine, rows)


@pytest.fixture
def server() -> Iterator[FakeModelServer]:
    yield from running_fake_model_server()


async def _timed(call: Callable[[], Awaitable[object]]) -> float:
    started = time.perf_counter()
    await call()
    return (time.perf_counter() - started) * 1000


async def test_gateway_overhead_is_below_20_ms(
    engine: AsyncEngine, org: OrgRows, server: FakeModelServer
) -> None:
    served = f"{FIXTURE_MODEL_ID}@sha256-{org.model_digest.removeprefix('sha256:')[:12]}"
    server.listed_ids = [served]
    settings = ModelSettings(environment="test", local_base_url=server.base_url)
    gateway = build_gateway(settings, engine)
    pool = httpx2.AsyncClient(trust_env=False)
    sdk = openai.AsyncOpenAI(
        api_key="bench", base_url=server.base_url, http_client=pool, max_retries=0
    )
    ctx = ModelCallContext(org_id=org.org_id, actor="platform-operator")
    ref = ModelRef(FIXTURE_MODEL_ID, FIXTURE_MODEL_VERSION)
    messages = [ChatMessage("user", "hi")]

    async def direct() -> object:
        return await sdk.chat.completions.create(model=served, messages=MESSAGES)  # type: ignore[arg-type]

    async def through_gateway() -> object:
        return await gateway.chat(ctx, ref, messages)

    try:
        for _ in range(WARMUP):
            await direct()
            await through_gateway()
        baseline, gated = [], []
        for _ in range(RUNS):
            baseline.append(await _timed(direct))
            gated.append(await _timed(through_gateway))
    finally:
        await gateway.aclose()
        await pool.aclose()

    median_overhead = statistics.median(gated) - statistics.median(baseline)
    p95 = statistics.quantiles(gated, n=20)[-1] - statistics.quantiles(baseline, n=20)[-1]
    print(
        f"\nmedian_direct_ms={statistics.median(baseline):.2f}"
        f" median_gateway_ms={statistics.median(gated):.2f}"
        f" median_overhead_ms={median_overhead:.2f} p95_overhead_ms={p95:.2f}"
    )
    assert median_overhead <= MAX_OVERHEAD_MS
