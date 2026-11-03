"""ASGI-level request-size guard.

FastAPI resolves an `UploadFile` parameter by having Starlette fully
parse the multipart body *before* the route handler runs (dependency
resolution happens ahead of the handler body) - so a Content-Length
check written inside `upload_document` itself can never run "before
the body is read." Rejecting on Content-Length before any multipart
parsing starts requires sitting in front of routing entirely, which is
what ASGI middleware is for.

Verified against the current Starlette docs/source (starlette==1.10.0,
checked 2026-11-04): `BaseHTTPMiddleware.__init__(self, app, dispatch=None)`
and `dispatch(self, request: Request, call_next) -> Response` are still
the current shape.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class MaxContentLengthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, max_bytes: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_bytes = int(content_length)
            except ValueError:
                declared_bytes = None
            if declared_bytes is not None and declared_bytes > self._max_bytes:
                return JSONResponse(
                    {"detail": f"request exceeds the {self._max_bytes}-byte limit"},
                    status_code=413,
                )
        return await call_next(request)
