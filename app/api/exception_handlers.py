from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import BizError, ErrorCode
from app.core.middleware import get_trace_id
from app.core.response import fail


def _with_trace(request: Request, payload: dict) -> dict:
    payload["trace_id"] = get_trace_id(request)
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def biz_error_handler(request: Request, exc: BizError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=_with_trace(request, fail(exc.code, exc.message)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic 校验失败统一映射为 1001
        return JSONResponse(
            status_code=400,
            content=_with_trace(
                request,
                fail(ErrorCode.PARAM_INVALID, "参数校验失败", exc.errors()),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # 404 等 HTTP 异常统一映射
        code = {
            401: ErrorCode.UNAUTHENTICATED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
        }.get(exc.status_code, ErrorCode.UNKNOWN)
        return JSONResponse(
            status_code=exc.status_code,
            content=_with_trace(request, fail(int(code), str(exc.detail))),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # 兜底：不要暴露堆栈
        return JSONResponse(
            status_code=500,
            content=_with_trace(
                request,
                fail(ErrorCode.UNKNOWN, "服务端未知错误"),
            ),
        )