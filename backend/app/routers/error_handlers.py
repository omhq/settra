from fastapi import Request
from fastapi.responses import JSONResponse

from app.cube.client import CubeAPIError
from app.errors import (
    AccessDeniedError,
    ApplicationError,
    InvalidInputError,
    InvalidOperationError,
    ResourceConflictError,
    ResourceNotFoundError,
)

APPLICATION_ERROR_STATUS = {
    InvalidOperationError: 400,
    InvalidInputError: 422,
    ResourceNotFoundError: 404,
    ResourceConflictError: 409,
    AccessDeniedError: 403,
}


def cube_api_error_detail(exc: CubeAPIError) -> dict[str, object]:
    return {
        "message": exc.message,
        "retryable": exc.retryable,
    }


async def application_error_handler(
    _request: Request,
    exc: ApplicationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=APPLICATION_ERROR_STATUS.get(type(exc), 400),
        content={"detail": exc.message},
    )


async def cube_api_error_handler(
    _request: Request,
    exc: CubeAPIError,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": cube_api_error_detail(exc)},
    )
