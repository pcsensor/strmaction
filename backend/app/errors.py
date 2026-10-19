"""统一错误格式：{"error": {"code": "...", "message": "..."}}。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra or {}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_request: Request, exc: APIError):
        payload: dict[str, Any] = {"code": exc.code, "message": exc.message}
        payload.update(exc.extra)
        return JSONResponse({"error": payload}, status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return JSONResponse(
            {"error": {"code": f"HTTP_{exc.status_code}", "message": detail}},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(x) for x in first.get("loc", [])[1:])
        return JSONResponse(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"{location}: {first.get('msg', '参数不合法')}",
                    "fields": exc.errors()[:8],
                }
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception):  # pragma: no cover
        print(f"[error] {type(exc).__name__}: {exc}")
        return JSONResponse(
            {"error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误"}},
            status_code=500,
        )
