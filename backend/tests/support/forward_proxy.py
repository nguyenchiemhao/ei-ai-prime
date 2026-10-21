"""Test-only HTTP forward proxy on 127.0.0.1 (EA-24 AC6): records and relays absolute-form
requests to loopback targets, one request per connection. ``stop()`` simulates "proxy down".

Never imported by ``src``. It refuses any target that is not 127.0.0.1, so a test can never
reach the real network through it.
"""

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from support.fake_model_server import free_loopback_socket


@dataclass
class ForwardProxy:
    request_lines: list[str] = field(default_factory=list)
    host_headers: list[str] = field(default_factory=list)
    url: str = ""
    _loop: asyncio.AbstractEventLoop | None = None
    _server: asyncio.Server | None = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, target, version = lines[0].split(" ", 2)
            headers = [line for line in lines[1:] if line]
            self.request_lines.append(lines[0])
            host = next(
                (h.split(":", 1)[1].strip() for h in headers if h.lower().startswith("host:")), ""
            )
            self.host_headers.append(host)
            length = next(
                (
                    int(h.split(":", 1)[1])
                    for h in headers
                    if h.lower().startswith("content-length:")
                ),
                0,
            )
            body = await reader.readexactly(length) if length else b""
            parts = urlsplit(target)
            if parts.hostname != "127.0.0.1" or parts.port is None:
                writer.write(
                    b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                return
            kept = [
                h
                for h in headers
                if not h.lower().startswith(("connection:", "proxy-connection:", "keep-alive:"))
            ]
            path = parts.path + (f"?{parts.query}" if parts.query else "")
            upstream_reader, upstream_writer = await asyncio.open_connection(
                "127.0.0.1", parts.port
            )
            request = f"{method} {path} {version}\r\n" + "".join(f"{h}\r\n" for h in kept)
            upstream_writer.write(request.encode("latin-1") + b"Connection: close\r\n\r\n" + body)
            await upstream_writer.drain()
            while chunk := await upstream_reader.read(65536):
                writer.write(chunk)
                await writer.drain()
            upstream_writer.close()
        except (asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            writer.close()

    async def _start(self) -> None:
        sock = free_loopback_socket()
        self._server = await asyncio.start_server(self._handle, sock=sock)
        port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        """Close the listening socket: new connections are refused from now on."""
        if self._loop is not None and self._server is not None:
            server = self._server
            asyncio.run_coroutine_threadsafe(_close(server), self._loop).result(timeout=5)


async def _close(server: asyncio.Server) -> None:
    server.close()
    await server.wait_closed()


@contextmanager
def running_forward_proxy() -> Iterator[ForwardProxy]:
    """A fresh proxy on its own event loop thread (use as a function-scoped fixture)."""
    proxy = ForwardProxy()
    loop = asyncio.new_event_loop()
    proxy._loop = loop
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    asyncio.run_coroutine_threadsafe(proxy._start(), loop).result(timeout=5)
    try:
        yield proxy
    finally:
        if proxy._server is not None and proxy._server.is_serving():
            proxy.stop()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()
