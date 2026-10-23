"""Test-only OpenAI-compatible model server on 127.0.0.1 (EA-24): scripted, records requests.

Served by uvicorn in a background thread on a free loopback port, so the gateway is tested
through real HTTP without any real network. Each test scripts the replies:

- ``listed_ids``: the ids ``GET /v1/models`` lists (llama.cpp lists its alias);
- ``models_replies`` / ``replies``: per-request ``Reply`` queues for ``/v1/models`` and for the
  completion, embedding and rerank endpoints; an empty queue answers with ``Reply()``;
- ``dimensions``: the size of every embedding (``[0.5, <position in the request>, -0.25]``, cut
  or padded with zeros).

Never imported by ``src``.
"""

import asyncio
import json
import socket
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route


@dataclass(frozen=True)
class Reply:
    """One scripted answer. ``model=None`` echoes the requested model (llama.cpp does that)."""

    status: int = 200
    delay: float = 0.0
    deltas: tuple[str, ...] = ("Xin", " chào")
    # Close the connection after this many deltas, without finishing the stream.
    drop_after: int | None = None
    model: str | None = None
    body: str = '{"error": {"message": "scripted failure"}}'
    prompt_tokens: int = 7
    completion_tokens: int = 2
    # A Set-Cookie header on the answer (a provider or its CDN sets cookies, R1-1).
    set_cookie: str | None = None
    # False: the stream starts straight with text, without the role-only first chunk.
    role_chunk: bool = True
    # The model id of every stream chunk after the first text delta (a mid-stream switch).
    later_model: str | None = None


@dataclass(frozen=True)
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: Any


class _Dropped(Exception):
    """Raised inside a streaming body to cut the connection mid-stream."""


@dataclass
class FakeModelServer:
    listed_ids: list[str] = field(default_factory=lambda: ["fake-model@sha256-000000000000"])
    models_replies: deque[Reply] = field(default_factory=deque)
    replies: deque[Reply] = field(default_factory=deque)
    requests: list[Recorded] = field(default_factory=list)
    base_url: str = ""
    dimensions: int = 3

    def paths(self) -> list[str]:
        return [request.path for request in self.requests]

    def count(self, path: str) -> int:
        return self.paths().count(path)

    def _next(self, queue: deque[Reply]) -> Reply:
        return queue.popleft() if queue else Reply()

    async def _record(self, request: Request) -> Any:
        raw = await request.body()
        body = json.loads(raw) if raw else None
        self.requests.append(
            Recorded(request.method, request.url.path, dict(request.headers), body)
        )
        return body

    async def models(self, request: Request) -> Response:
        await self._record(request)
        reply = self._next(self.models_replies)
        await asyncio.sleep(reply.delay)
        if reply.status != 200:
            return PlainTextResponse(reply.body, status_code=reply.status)
        data = [
            {"id": model_id, "object": "model", "owned_by": "fake"} for model_id in self.listed_ids
        ]
        return JSONResponse({"object": "list", "data": data})

    async def chat(self, request: Request) -> Response:
        body = await self._record(request)
        reply = self._next(self.replies)
        await asyncio.sleep(reply.delay)
        if reply.status != 200:
            return PlainTextResponse(reply.body, status_code=reply.status)
        model = reply.model or body["model"]
        if body.get("stream"):
            usage = bool((body.get("stream_options") or {}).get("include_usage"))
            return StreamingResponse(
                _events(reply, model, usage), media_type="text/event-stream", headers=_cookie(reply)
            )
        return JSONResponse(
            {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "".join(reply.deltas)},
                    }
                ],
                "usage": _usage(reply),
            },
            headers=_cookie(reply),
        )

    async def embeddings(self, request: Request) -> Response:
        body = await self._record(request)
        reply = self._next(self.replies)
        await asyncio.sleep(reply.delay)
        if reply.status != 200:
            return PlainTextResponse(reply.body, status_code=reply.status)
        inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
        data = [
            {"object": "embedding", "index": index, "embedding": self._vector(index)}
            for index, _ in enumerate(inputs)
        ]
        return JSONResponse(
            {
                "object": "list",
                "model": reply.model or body["model"],
                "data": data,
                "usage": {
                    "prompt_tokens": reply.prompt_tokens,
                    "total_tokens": reply.prompt_tokens,
                },
            }
        )

    def _vector(self, index: int) -> list[float]:
        return ([0.5, float(index), -0.25] + [0.0] * self.dimensions)[: self.dimensions]

    async def rerank(self, request: Request) -> Response:
        body = await self._record(request)
        reply = self._next(self.replies)
        await asyncio.sleep(reply.delay)
        if reply.status != 200:
            return PlainTextResponse(reply.body, status_code=reply.status)
        scores = [
            {"index": index, "relevance_score": round(1.0 - index * 0.25, 2)}
            for index, _ in enumerate(body["documents"])
        ]
        top_n = body.get("top_n") or len(scores)
        return JSONResponse(
            {
                "model": reply.model or body["model"],
                "results": scores[:top_n],
                "usage": {
                    "prompt_tokens": reply.prompt_tokens,
                    "total_tokens": reply.prompt_tokens,
                },
            }
        )

    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/v1/models", self.models, methods=["GET"]),
                Route("/v1/chat/completions", self.chat, methods=["POST"]),
                Route("/v1/embeddings", self.embeddings, methods=["POST"]),
                Route("/v1/rerank", self.rerank, methods=["POST"]),
            ]
        )


def _cookie(reply: Reply) -> dict[str, str] | None:
    return None if reply.set_cookie is None else {"set-cookie": reply.set_cookie}


def _usage(reply: Reply) -> dict[str, int]:
    return {
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
        "total_tokens": reply.prompt_tokens + reply.completion_tokens,
    }


def _chunk(model: str, delta: dict[str, Any], finish: str | None) -> str:
    payload = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload)}\n\n"


async def _events(reply: Reply, model: str, usage: bool) -> AsyncIterator[str]:
    if reply.role_chunk:
        yield _chunk(model, {"role": "assistant", "content": None}, None)
    for count, delta in enumerate(reply.deltas):
        if reply.drop_after is not None and count >= reply.drop_after:
            raise _Dropped
        yield _chunk(model, {"content": delta}, None)
        model = reply.later_model or model
        await asyncio.sleep(0)
    yield _chunk(model, {}, "stop")
    if usage:
        payload = {
            "id": "chatcmpl-fake",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [],
            "usage": _usage(reply),
        }
        yield f"data: {json.dumps(payload)}\n\n"
    yield "data: [DONE]\n\n"


def free_loopback_socket() -> socket.socket:
    # IPPROTO_TCP explicitly: asyncio sets TCP_NODELAY only on sockets whose proto is TCP, and
    # without it every response waits ~40 ms for a delayed ACK (Nagle).
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    return sock


def unused_loopback_url() -> str:
    """A loopback URL on a port nothing listens on (connection refused)."""
    sock = free_loopback_socket()
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/v1"


@contextmanager
def serve_in_thread(app: Starlette) -> Iterator[str]:
    """Serve ``app`` on a free loopback port; yields ``http://127.0.0.1:<port>``."""
    sock = free_loopback_socket()
    config = uvicorn.Config(app, log_level="critical", lifespan="off", timeout_graceful_shutdown=1)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("fake model server did not start")
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def running_fake_model_server() -> Iterator[FakeModelServer]:
    """A fresh fake server per test (use as a function-scoped fixture)."""
    fake = FakeModelServer()
    with serve_in_thread(fake.app()) as origin:
        fake.base_url = f"{origin}/v1"
        yield fake
