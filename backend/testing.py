"""Small synchronous ASGI client for tests that cannot create worker threads.

Starlette's ``TestClient`` is convenient, but it runs the ASGI app through an AnyIO
thread portal.  Some restricted CI/sandbox runtimes cannot create that worker and the
suite then waits forever before producing a response.  This adapter keeps the existing
synchronous test style while driving HTTPX's ASGI transport on the current thread.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import httpx


class ASGITestClient:
    __test__ = False

    def __init__(self, app: Any) -> None:
        self.app = app

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=True)

        async def inline_to_thread(function: Any, /, *args: Any, **call_kwargs: Any) -> Any:
            return function(*args, **call_kwargs)

        # Endpoints correctly offload blocking provider calls in production.  Tests replace
        # those providers with instant fakes, so execute them inline when this no-thread
        # transport is in use.
        with patch.object(asyncio, "to_thread", inline_to_thread):
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=True,
            ) as client:
                return await client.request(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return asyncio.run(self._request(method, url, **kwargs))

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)
