"""Tenant-scoped Valkey keys: ``org:<org_id>:<namespace>[:<part>...]`` (ADR-001 section 3.11)."""

import re
from uuid import UUID

TENANT_KEY_PATTERN = re.compile(
    r"^org:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:"
)
_NAMESPACE = re.compile(r"[a-z][a-z0-9_-]*")


def _escape(part: str) -> str:
    """``%`` first, then ``:``: a part can never add a separator or forge a prefix, and two
    different part lists can never give the same key."""
    return part.replace("%", "%25").replace(":", "%3A")


def tenant_key(org_id: UUID, namespace: str, *parts: str) -> str:
    """The key for ``parts`` in ``namespace`` of one Organization. Application code does not call
    this: it uses ``TenantCache``, which takes the verified context. The function is public for the
    tests and the key scan."""
    if not isinstance(org_id, UUID):
        raise TypeError(f"org_id must be a uuid.UUID, got {type(org_id).__name__}")
    if not _NAMESPACE.fullmatch(namespace):
        raise ValueError("namespace must match ^[a-z][a-z0-9_-]*$")
    if not all(parts):
        raise ValueError("a key part must not be empty")
    return ":".join(["org", str(org_id), namespace, *(_escape(part) for part in parts)])


def is_tenant_key(key: str) -> bool:
    return TENANT_KEY_PATTERN.match(key) is not None
