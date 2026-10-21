"""``ei-ai model try``: one streaming chat call through the gateway, printed as it arrives.

The answer goes to stdout only, never to ``logging`` (D52); the last stdout line is the
``done:`` line with metadata only.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import PLATFORM_OPERATOR
from ei_ai.db.engine import run_with_app_engine
from ei_ai.model_gateway.cli_common import ensure_organization
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.factory import build_gateway
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.model_gateway.results import ChatCompleted, ChatMessage, TextDelta
from ei_ai.settings import ModelSettings

DEFAULT_PROMPT = "Xin chào, hãy giới thiệu ngắn gọn về bạn."
DEFAULT_MAX_TOKENS = 64


@dataclass(frozen=True)
class TryRequest:
    org_id: uuid.UUID
    ref: ModelRef
    prompt: str
    max_tokens: int


def done_line(done: ChatCompleted, first_token_ms: int, total_ms: int) -> str:
    """The last stdout line: ref, short digest, tokens, attempts and timings."""
    digest = "none" if done.digest is None else done.digest[: len("sha256:") + 12]
    return (
        f"done: model={done.model_ref} digest={digest}"
        f" prompt_tokens={done.usage.prompt_tokens}"
        f" completion_tokens={done.usage.completion_tokens}"
        f" attempts={done.attempts} first_token_ms={first_token_ms} total_ms={total_ms}"
    )


async def _stream(
    engine: AsyncEngine, settings: ModelSettings, request: TryRequest, write: Callable[[str], None]
) -> str:
    await ensure_organization(engine, request.org_id)
    gateway = build_gateway(settings, engine)
    ctx = ModelCallContext(org_id=request.org_id, actor=PLATFORM_OPERATOR)
    started = time.perf_counter()
    first_token: float | None = None
    try:
        async for event in gateway.stream_chat(
            ctx,
            request.ref,
            [ChatMessage("user", request.prompt)],
            max_tokens=request.max_tokens,
        ):
            if isinstance(event, TextDelta):
                first_token = first_token or time.perf_counter()
                write(event.text)
            else:
                total = time.perf_counter()
                first = first_token or total
                return done_line(
                    event, round((first - started) * 1000), round((total - started) * 1000)
                )
    finally:
        await gateway.aclose()
    raise RuntimeError("the stream ended without a completion event")


async def try_model(
    database_url: str,
    settings: ModelSettings,
    request: TryRequest,
    write: Callable[[str], None],
) -> str:
    """Stream the answer through ``write``; returns the ``done:`` line."""
    return await run_with_app_engine(
        database_url, lambda engine: _stream(engine, settings, request, write)
    )
