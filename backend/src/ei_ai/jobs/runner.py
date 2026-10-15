"""Runs a job inside the tenant context of its envelope (D46, layer 2)."""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_session
from ei_ai.jobs.envelope import JobContext, JobEnvelope
from ei_ai.jobs.registry import JOBS, JobRegistry

logger = logging.getLogger("ei_ai.jobs")


async def run_tenant_job(
    engine: AsyncEngine, envelope: JobEnvelope, registry: JobRegistry = JOBS
) -> None:
    """Run the handler of ``envelope.kind`` in a tenant transaction for ``envelope.org_id``.

    The transaction commits when the handler returns and rolls back when it raises, and the
    tenant setting never outlives it. A failure is logged with the kind, the Organization and the
    exception class only (never the payload or the message, D52) and re-raised.
    """
    handler = registry.handler(envelope.kind)
    if not isinstance(envelope.org_id, UUID):
        raise TypeError(f"org_id must be a uuid.UUID, got {type(envelope.org_id).__name__}")
    try:
        async with tenant_session(engine, envelope.org_id) as session:
            await handler(JobContext(org_id=envelope.org_id, session=session), envelope.payload)
    except Exception as error:
        logger.error(
            "tenant_job_failed kind=%s org_id=%s error=%s",
            envelope.kind,
            envelope.org_id,
            type(error).__name__,
        )
        raise
