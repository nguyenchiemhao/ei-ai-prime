"""The message of a background job: what to run, and for which Organization."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ei_ai.tenancy.context import TenantContext, is_org_field


@dataclass(frozen=True)
class JobEnvelope:
    """``org_id`` is set only by :func:`envelope_for`."""

    kind: str
    org_id: UUID
    payload: Mapping[str, object]


@dataclass(frozen=True)
class JobContext:
    """What a handler gets: its Organization and a session already inside that tenant's
    transaction. There is deliberately no engine, so a handler cannot open another tenant."""

    org_id: UUID
    session: AsyncSession


def _has_org_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(is_org_field(str(key)) or _has_org_field(item) for key, item in value.items())
    if isinstance(value, list | tuple):
        return any(_has_org_field(item) for item in value)
    return False


def envelope_for(tenant: TenantContext, kind: str, payload: Mapping[str, object]) -> JobEnvelope:
    """The envelope of a job for the Organization of ``tenant`` (the verified request context).

    The Organization is never taken from the payload, a request body or model output (D32), so a
    payload that carries an Organization field is refused.
    """
    if _has_org_field(payload):
        raise ValueError("job payload must not carry an Organization field")
    return JobEnvelope(kind=kind, org_id=tenant.org_id, payload=dict(payload))
