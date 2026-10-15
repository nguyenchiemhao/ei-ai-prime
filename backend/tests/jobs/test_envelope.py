"""A job's Organization comes from the verified request context, never from its payload (D32)."""

import uuid
from dataclasses import FrozenInstanceError

import pytest

from ei_ai.jobs.envelope import JobEnvelope, envelope_for
from ei_ai.tenancy.context import TenantContext

TENANT = TenantContext(org_id=uuid.uuid4(), user_id=uuid.uuid4())


def test_envelope_takes_the_organization_from_the_tenant_context() -> None:
    envelope = envelope_for(TENANT, "ingest.document", {"document": "d1"})

    assert envelope == JobEnvelope(
        kind="ingest.document", org_id=TENANT.org_id, payload={"document": "d1"}
    )


def test_envelope_cannot_be_changed_after_creation() -> None:
    envelope = envelope_for(TENANT, "ingest.document", {})

    with pytest.raises(FrozenInstanceError):
        envelope.org_id = uuid.uuid4()  # type: ignore[misc]


@pytest.mark.parametrize(
    "payload",
    [
        {"org_id": str(uuid.uuid4())},
        {"orgId": "x"},
        {"X-Tenant-Id": "x"},
        {"outer": {"organization_id": "x"}},
        {"items": [{"tenant_id": "x"}]},
    ],
)
def test_payload_with_an_organization_field_is_refused(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="job payload must not carry an Organization field") as e:
        envelope_for(TENANT, "ingest.document", payload)

    assert "x" not in str(e.value).replace("Organization field", "")


def test_payload_with_other_fields_is_accepted() -> None:
    envelope = envelope_for(TENANT, "ingest.document", {"workspace_id": "w", "items": [{"id": 1}]})

    assert envelope.payload == {"workspace_id": "w", "items": [{"id": 1}]}
