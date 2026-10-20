"""Demo seed: loads the Mekong Devworks manifest into the database, idempotently (FND-04).

The environment guard runs first: outside local/test nothing else happens (no settings beyond
``EI_AI_ENV``, no engine, no database access). The manifest carries a fixed Organization id, so
the seed finds an earlier load inside that Organization's own tenant transaction, without any
cross-tenant read. It creates only what is missing and never updates or deletes a row.

It never repairs memberships either: a member who already exists keeps exactly the rows they have.
If the Workspace was deleted or renamed by hand, a run recreates "People Ops" but does not add the
existing members to it (they still show ``already present``). Reset the local database
(``npm run reset``) for a clean demo.
"""

import asyncio
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ei_ai.audit.events import (
    ORGANIZATION_CREATED,
    PLATFORM_OPERATOR,
    USER_INVITED,
    WORKSPACE_CREATED,
    record_event,
)
from ei_ai.auth.set_password import set_password_link
from ei_ai.db.engine import run_with_app_engine
from ei_ai.db.tenant import tenant_transaction
from ei_ai.provisioning.rows import (
    find_user_id,
    find_workspace_id,
    insert_member,
    insert_organization,
    insert_workspace,
    organization_exists,
)
from ei_ai.provisioning.service import raise_if_violated
from ei_ai.provisioning.validation import ProvisioningError, normalise_email, split_roles
from ei_ai.settings import CliSettings, admin_base_url

SEED_ENVIRONMENTS = ("local", "test")


class SeedRefused(Exception):
    """The demo seed must not run in this environment."""


class Member(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=200)
    email: str
    roles: list[str] = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def email_is_normalised(cls, value: str) -> str:
        """The email must be valid and already trimmed and lowercase."""
        try:
            valid = normalise_email(value) == value
        except ProvisioningError as error:
            raise ValueError(str(error)) from None
        if not valid:
            raise ValueError("email must be trimmed and lowercase")
        return value

    @field_validator("roles")
    @classmethod
    def roles_are_codes(cls, value: list[str]) -> list[str]:
        """The roles must be known codes, at most one of each kind."""
        try:
            split_roles(value)
        except ProvisioningError as error:
            raise ValueError(str(error)) from None
        return value


class DemoManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: Literal[2]
    organization_id: uuid.UUID
    organization: str = Field(min_length=1, max_length=200)
    workspace: str = Field(min_length=1, max_length=200)
    members: list[Member] = Field(min_length=1)

    @model_validator(mode="after")
    def emails_are_unique(self) -> "DemoManifest":
        """No two members share an email."""
        emails = [member.email for member in self.members]
        if len(set(emails)) != len(emails):
            raise ValueError("member emails must be unique")
        return self


@dataclass(frozen=True)
class SeedResult:
    """What one run found or created; ``member_secrets`` holds, in manifest order, the
    set-password secret of each member created in this run and None for one already present."""

    workspace_id: uuid.UUID
    organization_created: bool
    workspace_created: bool
    member_secrets: tuple[str | None, ...]

    @property
    def audit_events(self) -> int:
        """Number of audit events this run wrote (one per created object)."""
        created = [self.organization_created, self.workspace_created]
        return sum(created) + sum(secret is not None for secret in self.member_secrets)


def load_manifest() -> DemoManifest:
    """The packaged Mekong Devworks manifest, validated."""
    text = resources.files("ei_ai.seed").joinpath("data/mekong-devworks.json").read_text("utf-8")
    return DemoManifest.model_validate(json.loads(text))


async def _ensure_organization(conn: AsyncConnection, manifest: DemoManifest) -> bool:
    """Create the demo Organization when missing; True when created."""
    org_id = manifest.organization_id
    if await organization_exists(conn, org_id):
        return False
    await insert_organization(conn, org_id, manifest.organization)
    await record_event(
        conn,
        org_id,
        PLATFORM_OPERATOR,
        ORGANIZATION_CREATED,
        "organization",
        org_id,
    )
    return True


async def _ensure_workspace(
    conn: AsyncConnection, manifest: DemoManifest
) -> tuple[uuid.UUID, bool]:
    """(Workspace id, created) of the manifest Workspace, creating it when missing."""
    org_id = manifest.organization_id
    found = await find_workspace_id(conn, org_id, manifest.workspace)
    if found is not None:
        return found, False
    ws_id = await insert_workspace(conn, org_id, manifest.workspace)
    await record_event(conn, org_id, PLATFORM_OPERATOR, WORKSPACE_CREATED, "workspace", ws_id)
    return ws_id, True


async def _ensure_member(
    conn: AsyncConnection, org_id: uuid.UUID, ws_id: uuid.UUID, member: Member
) -> str | None:
    """The new member's set-password secret, or None when the email is already a user."""
    if await find_user_id(conn, org_id, member.email) is not None:
        return None
    org_role, workspace_role = split_roles(member.roles)
    workspace = (ws_id, workspace_role) if workspace_role is not None else None
    user_id, secret = await insert_member(
        conn, org_id, member.email, member.name, org_role, workspace
    )
    await record_event(conn, org_id, PLATFORM_OPERATOR, USER_INVITED, "user", user_id)
    return secret


async def seed_manifest(engine: AsyncEngine, manifest: DemoManifest) -> SeedResult:
    """Create what is missing of the manifest in one tenant transaction, with audit events."""
    org_id = manifest.organization_id
    try:
        async with engine.connect() as conn, tenant_transaction(conn, org_id):
            org_created = await _ensure_organization(conn, manifest)
            ws_id, ws_created = await _ensure_workspace(conn, manifest)
            secrets = [await _ensure_member(conn, org_id, ws_id, m) for m in manifest.members]
    except IntegrityError as error:
        raise_if_violated(
            error,
            "organizations_name_lower_key",
            f'an Organization named "{manifest.organization}" already exists with another id',
        )
        raise
    return SeedResult(ws_id, org_created, ws_created, tuple(secrets))


def _status(created: bool) -> str:
    """The status word of one summary line."""
    return "created" if created else "already present"


def format_summary(manifest: DemoManifest, result: SeedResult, base_url: str) -> str:
    """The seed output; a run that creates nothing prints the same text every time."""
    org_id = manifest.organization_id
    lines = [
        f"Demo seed: {manifest.organization}",
        f"  Organization: {manifest.organization} ({org_id}):"
        f" {_status(result.organization_created)}",
        f"  Workspace: {manifest.workspace} ({result.workspace_id}):"
        f" {_status(result.workspace_created)}",
        f"  Members: {len(manifest.members)}",
    ]
    pairs = list(zip(manifest.members, result.member_secrets, strict=True))
    lines += [
        f"    - {member.name}: {', '.join(member.roles)}: {_status(secret is not None)}"
        for member, secret in pairs
    ]
    lines.append(f"  Audit events written: {result.audit_events}")
    links = [
        f"    - {member.email}: {set_password_link(base_url, org_id, secret)}"
        for member, secret in pairs
        if secret is not None
    ]
    if links:
        lines += ["  Set-password links (valid 24 h, shown once):", *links]
    else:
        lines.append(
            '  Set-password links: none (no member was created; use "ei-ai user link"'
            " for a new link)"
        )
    return "\n".join(lines)


def load_demo_data(env: Mapping[str, str], manifest: DemoManifest) -> str:
    """Read the settings, load the manifest into the database and return the summary.

    Raises ``SettingsError`` before any database access when a setting is missing or invalid.
    """
    settings = CliSettings.from_env(env)
    base_url = admin_base_url(env, settings.environment)
    result = asyncio.run(
        run_with_app_engine(settings.database_url, lambda e: seed_manifest(e, manifest))
    )
    return format_summary(manifest, result, base_url)


def run_demo_seed(environment: str, load: Callable[[DemoManifest], str]) -> str:
    """Guard the environment, then load the manifest with ``load`` and return its summary.

    Raises SeedRefused outside local/test before ``load`` is called.
    """
    if environment not in SEED_ENVIRONMENTS:
        raise SeedRefused(
            f"the demo seed runs only in {' or '.join(SEED_ENVIRONMENTS)} environments"
        )
    return load(load_manifest())
