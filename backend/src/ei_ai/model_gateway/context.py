"""Who is calling a model, and for which Organization."""

import uuid
from dataclasses import dataclass

from ei_ai.audit.events import user_actor
from ei_ai.tenancy.context import TenantContext


@dataclass(frozen=True)
class ModelCallContext:
    """The caller of one gateway call.

    ``org_id`` comes only from the verified identity (D32, D46): the ``Principal`` /
    ``TenantContext`` of a request, or the Platform Operator's ``--org``. Never from a request
    body, a query string or model output. ``actor`` is the audit actor (``platform-operator`` or
    ``user:<id>``). ``assistant_id`` and ``channel_id`` only feed the trace and usage records.
    """

    org_id: uuid.UUID
    actor: str
    assistant_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None

    @classmethod
    def from_tenant(
        cls,
        tenant: TenantContext,
        *,
        assistant_id: uuid.UUID | None = None,
        channel_id: uuid.UUID | None = None,
    ) -> "ModelCallContext":
        """The context of a signed-in user's request."""
        return cls(
            org_id=tenant.org_id,
            actor=user_actor(tenant.user_id),
            assistant_id=assistant_id,
            channel_id=channel_id,
        )
