"""
全局异常处理器
================
统一所有错误的返回格式，确保 API 响应一致性
"""
import logging
import traceback
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

logger = logging.getLogger(__name__)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """请求验证错误 - 422"""
    errors = []
    for err in exc.errors():
        errors.append({
            "field": ".".join(str(e) for e in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        })
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "message": "请求参数验证失败",
            "errors": errors,
        },
    )


async def http_exception_handler(
    request: Request, exc
) -> JSONResponse:
    """HTTP 异常 - 统一格式"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
        },
    )


async def global_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """全局异常捕获 - 500"""
    logger.error(
        f"未捕获异常 [{request.method} {request.url.path}]: {exc}\n"
        f"{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "服务器内部错误",
        },
    )
