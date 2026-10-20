"""``Cache-Control: no-store`` on every ``/auth/*`` response (R37).

A pure ASGI middleware added outermost, so it also covers the answers produced outside any route:
the CSRF middleware's 403 and the validation handler's 422.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_AUTH_PREFIX = "/auth/"


class NoStoreAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(_AUTH_PREFIX):
            await self._app(scope, receive, send)
            return

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self._app(scope, receive, send_no_store)
