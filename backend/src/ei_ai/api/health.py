"""Liveness (/healthz) and readiness (/readyz) probes."""

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ei_ai.readiness import Readiness, Status, run_checks

router = APIRouter()


class HealthStatus(BaseModel):
    status: Literal["ok"]


class ReadinessChecks(BaseModel):
    database: Status
    valkey: Status


class ReadinessStatus(BaseModel):
    status: Status
    checks: ReadinessChecks


@router.get("/healthz", response_model=HealthStatus, summary="Liveness probe")
def healthz() -> HealthStatus:
    """The process is up. Never calls a dependency."""
    return HealthStatus(status="ok")


@router.get(
    "/readyz",
    response_model=ReadinessStatus,
    responses={503: {"model": ReadinessStatus, "description": "A dependency is unavailable"}},
    summary="Readiness probe",
)
async def readyz(request: Request, response: Response) -> ReadinessStatus:
    """Database and Valkey are reachable. Reports component names and ok/unavailable only."""
    readiness: Readiness = request.app.state.readiness
    results = await run_checks(readiness)
    healthy = all(value == "ok" for value in results.values())
    if not healthy:
        response.status_code = 503
    return ReadinessStatus(
        status="ok" if healthy else "unavailable", checks=ReadinessChecks(**results)
    )
