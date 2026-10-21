"""Demo seed: loads the packaged manifests into the database, idempotently (FND-04, EA-94).

The environment guard runs first: outside local/test nothing else happens (no settings beyond
``EI_AI_ENV``, no manifest, no engine, no database access). Each manifest carries a fixed
Organization id and is loaded in its own tenant transaction, in ``MANIFEST_FILES`` order, without
any cross-tenant read; an Organization that fails leaves the earlier ones committed.

The seed creates only what is missing and never updates or deletes a row. A member who already
exists keeps their roles; they only join a manifest Workspace created in this run (R10). Every
account marked ``shared_password`` without a credential gets one hashed from
``EI_AI_SEED_PASSWORD``; an existing credential is never read or replaced. No set-password token
is issued. Reset the local database (``npm run reset``) for a clean demo.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.engine import run_with_app_engine
from ei_ai.db.tenant import tenant_transaction
from ei_ai.model_gateway.catalog_rows import ensure_platform_models
from ei_ai.provisioning.service import raise_if_violated
from ei_ai.seed.manifest import DemoManifest, load_manifests
from ei_ai.seed.summary import SeedResult, format_summary
from ei_ai.seed.writes import (
    SeedRun,
    apply_password,
    ensure_knowledge,
    ensure_member,
    ensure_organization,
    ensure_workspaces,
)
from ei_ai.settings import CliSettings, seed_password

__all__ = ["DemoManifest", "SeedRefused", "SeedResult", "load_demo_data", "run_demo_seed"]

SEED_ENVIRONMENTS = ("local", "test")


class SeedRefused(Exception):
    """The demo seed must not run in this environment."""


async def seed_manifest(engine: AsyncEngine, manifest: DemoManifest, password: str) -> SeedResult:
    """Create what is missing of one manifest in its own tenant transaction, with audit events,
    and the platform models of the model catalog (without audit events)."""
    org_id = manifest.organization_id
    try:
        async with engine.connect() as conn, tenant_transaction(conn, org_id):
            run = SeedRun(conn, org_id)
            org_created = await ensure_organization(run, manifest)
            workspaces = await ensure_workspaces(run, manifest)
            members = [await ensure_member(run, workspaces, m) for m in manifest.members]
            applied = [
                await apply_password(run, user_id, password)
                for (user_id, _), member in zip(members, manifest.members, strict=True)
                if member.shared_password
            ]
            collections, folders = await ensure_knowledge(run, manifest, workspaces)
            # The platform models (EA-24): no audit event and no output line.
            await ensure_platform_models(conn, org_id)
    except IntegrityError as error:
        raise_if_violated(
            error,
            "organizations_name_lower_key",
            f'an Organization named "{manifest.organization}" already exists with another id',
        )
        raise
    return SeedResult(
        organization_created=org_created,
        workspaces=tuple((name, ws_id, created) for name, (ws_id, created) in workspaces.items()),
        members_created=tuple(created for _, created in members),
        collections_created=collections,
        folders_created=folders,
        passwords_applied=sum(applied),
        audit_events=run.events,
    )


async def _seed_all(engine: AsyncEngine, manifests: Sequence[DemoManifest], password: str) -> str:
    """Seed the manifests in order; the summary of every Organization."""
    summaries = [format_summary(m, await seed_manifest(engine, m, password)) for m in manifests]
    return "\n".join(summaries)


def load_demo_data(env: Mapping[str, str], manifests: tuple[DemoManifest, ...]) -> str:
    """Read the settings and the seed password, load the manifests and return the summary.

    Raises ``SettingsError`` before any database access when a setting is missing or invalid.
    """
    settings = CliSettings.from_env(env)
    password = seed_password(env)
    return asyncio.run(
        run_with_app_engine(settings.database_url, lambda e: _seed_all(e, manifests, password))
    )


def run_demo_seed(environment: str, load: Callable[[tuple[DemoManifest, ...]], str]) -> str:
    """Guard the environment, then load the manifests with ``load`` and return its summary.

    Raises SeedRefused outside local/test before ``load`` or the manifests are touched.
    """
    if environment not in SEED_ENVIRONMENTS:
        raise SeedRefused(
            f"the demo seed runs only in {' or '.join(SEED_ENVIRONMENTS)} environments"
        )
    return load(load_manifests())
