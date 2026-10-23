"""The shape of API errors: a code that frontends translate, never text, ids or SQL."""

from collections.abc import Sequence
from typing import NoReturn

from fastapi import HTTPException
from pydantic import BaseModel


class ErrorCode(BaseModel):
    detail: str


def raise_mapped(error: Exception, table: Sequence[tuple[type[Exception], int, str]]) -> NoReturn:
    """Raise the HTTP error (code only) that ``table`` maps ``error`` to; any other error is
    re-raised unchanged."""
    for kind, status, code in table:
        if isinstance(error, kind):
            raise HTTPException(status_code=status, detail=code) from None
    raise error
