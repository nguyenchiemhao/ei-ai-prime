"""A follow-up job keeps the Organization of the envelope that queued it, not a payload's (D32)."""

import uuid

import pytest

from ei_ai.jobs.envelope import JobEnvelope, envelope_for, follow_up
from ei_ai.tenancy.context import TenantContext

TENANT = TenantContext(org_id=uuid.uuid4(), user_id=uuid.uuid4())


def test_follow_up_envelope_keeps_the_org_and_refuses_org_fields() -> None:
    first = envelope_for(TENANT, "knowledge.document.ingest", {"document_id": "d1"})

    second = follow_up(first, "knowledge.document.index", {"document_id": "d1"})

    assert second == JobEnvelope(
        kind="knowledge.document.index", org_id=TENANT.org_id, payload={"document_id": "d1"}
    )
    for payload in (
        {"org_id": str(uuid.uuid4())},
        {"outer": {"organization_id": "x"}},
        {"items": [{"tenant_id": "x"}]},
    ):
        with pytest.raises(ValueError, match="job payload must not carry an Organization field"):
            follow_up(first, "knowledge.document.index", payload)
