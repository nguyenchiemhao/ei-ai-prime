"""Fixtures of the demo seed integration tests."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.seed.manifest import DemoManifest
from support.seed import variant_manifests
from support.tenants import purge_org_ids


@pytest.fixture
async def variants(app_engine: AsyncEngine) -> AsyncIterator[tuple[DemoManifest, ...]]:
    """Variants of both packaged manifests (Mekong first); purged afterwards."""
    manifests = variant_manifests()
    try:
        yield manifests
    finally:
        await purge_org_ids(app_engine, *(manifest.organization_id for manifest in manifests))
