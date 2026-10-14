"""The shape of API errors: a code that frontends translate, never text, ids or SQL."""

from pydantic import BaseModel


class ErrorCode(BaseModel):
    detail: str
