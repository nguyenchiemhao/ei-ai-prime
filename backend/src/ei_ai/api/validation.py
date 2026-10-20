"""Validation errors answer a fixed body: the default one echoes the rejected input."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def _invalid_request(_request: Request, _error: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "invalid_request"})


def install_validation_handler(app: FastAPI) -> None:
    """Any ``RequestValidationError`` becomes 422 ``{"detail": "invalid_request"}``, no input.

    A sign-in body with a password must never come back in an error response.
    """
    app.add_exception_handler(RequestValidationError, _invalid_request)
