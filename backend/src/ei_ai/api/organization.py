"""The Organization of the verified identity."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ei_ai.api.deps import TenantSession
from ei_ai.api.errors import ErrorCode
from ei_ai.db.models import Organization
from ei_ai.tenancy.context import TenantContext, require_tenant

router = APIRouter()


class CurrentOrganization(BaseModel):
    id: UUID
    name: str


@router.get(
    "/organization",
    response_model=CurrentOrganization,
    responses={
        401: {"model": ErrorCode, "description": "No valid identity (detail: unauthenticated)"},
        404: {"model": ErrorCode, "description": "The Organization does not exist (not_found)"},
    },
    summary="The Organization of the verified identity",
)
async def get_organization(
    tenant: Annotated[TenantContext, Depends(require_tenant)],
    session: TenantSession,
) -> CurrentOrganization:
    """Always the Organization of the verified token or session. An ``org_id`` sent in a header or
    query parameter is ignored (D32); the database also restricts the query to that Organization
    (D46), so the explicit filter below is the first of two layers."""
    row = (
        await session.execute(
            select(Organization.id, Organization.name).where(Organization.id == tenant.org_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    return CurrentOrganization(id=row.id, name=row.name)
