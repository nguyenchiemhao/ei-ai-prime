"""Provisioning service of the platform plane: Organizations, Workspaces, invitations, links.

Each function validates its input first (no database access on invalid input), then runs in
one tenant transaction for the target Organization: the rows and their audit events commit
together or not at all. Conflicts and missing objects raise ``ProvisioningError``; any other
database error propagates unchanged (the CLI prints only its class name, D52).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import (
    ORGANIZATION_CREATED,
    PLATFORM_OPERATOR,
    USER_INVITED,
    USER_SET_PASSWORD_LINK_ISSUED,
    WORKSPACE_CREATED,
    WORKSPACE_MEMBER_ADDED,
    record_event,
    record_role_change,
)
from ei_ai.auth.set_password import issue_token
from ei_ai.db.constraints import violated_constraint
from ei_ai.db.tenant import tenant_transaction
from ei_ai.members.rows import find_user_id, insert_member, insert_workspace_member
from ei_ai.provisioning.rows import (
    insert_organization,
    insert_workspace,
    organization_exists,
    workspace_exists,
    workspace_member_exists,
)
from ei_ai.provisioning.validation import (
    ProvisioningError,
    normalise_display_name,
    normalise_email,
    normalise_org_name,
    normalise_workspace_name,
    split_roles,
)

DEFAULT_WORKSPACE_NAME = "Default"
ORGANIZATION_NAME_TAKEN = "an Organization with this name already exists"
_ORG_NOT_FOUND = "Organization not found"
_NOT_A_WORKSPACE_ROLE = "--role must be a Workspace role"


@dataclass(frozen=True)
class CreatedOrganization:
    org_id: uuid.UUID
    org_name: str
    workspace_id: uuid.UUID
    workspace_name: str
    owner_id: uuid.UUID
    owner_email: str
    secret: str


@dataclass(frozen=True)
class CreatedWorkspace:
    workspace_id: uuid.UUID
    name: str


@dataclass(frozen=True)
class InvitedUser:
    user_id: uuid.UUID
    email: str
    roles: tuple[str, ...]
    secret: str


@dataclass(frozen=True)
class IssuedLink:
    user_id: uuid.UUID
    secret: str


@dataclass(frozen=True)
class AddedMember:
    user_id: uuid.UUID
    email: str
    role: str


def raise_if_violated(error: IntegrityError, constraint: str, message: str) -> None:
    """Raise ``ProvisioningError(message)`` when ``error`` violated ``constraint``."""
    if violated_constraint(error) == constraint:
        # "from None": the original error text holds the conflicting key values.
        raise ProvisioningError(message) from None


def default_display_name(display_name: str | None, email: str) -> str:
    """The trimmed display name, or the local part of the email when none is given."""
    return email.partition("@")[0] if display_name is None else normalise_display_name(display_name)


async def new_org_id(engine: AsyncEngine) -> uuid.UUID:
    """A fresh UUIDv7 from the database, outside any tenant transaction."""
    async with engine.connect() as conn:
        org_id: uuid.UUID = (await conn.execute(text("SELECT uuid_generate_v7()"))).scalar_one()
    return org_id


async def create_organization(
    engine: AsyncEngine,
    name: str,
    owner_email: str,
    owner_name: str | None = None,
    workspace_name: str = DEFAULT_WORKSPACE_NAME,
) -> CreatedOrganization:
    """An Organization, its default Workspace and its Org Owner (also Workspace Admin), with a
    set-password token and five audit events (the three creations and the two role grants)."""
    org_name = normalise_org_name(name)
    email = normalise_email(owner_email)
    display_name = default_display_name(owner_name, email)
    ws_name = normalise_workspace_name(workspace_name)
    org_id = await new_org_id(engine)
    try:
        async with engine.connect() as conn, tenant_transaction(conn, org_id):
            await insert_organization(conn, org_id, org_name)
            ws_id = await insert_workspace(conn, org_id, ws_name)
            owner_id, secret = await insert_member(
                conn, org_id, email, display_name, "org_owner", (ws_id, "workspace_admin")
            )
            await record_event(
                conn,
                org_id,
                PLATFORM_OPERATOR,
                ORGANIZATION_CREATED,
                "organization",
                org_id,
            )
            await record_event(
                conn,
                org_id,
                PLATFORM_OPERATOR,
                WORKSPACE_CREATED,
                "workspace",
                ws_id,
            )
            await record_event(conn, org_id, PLATFORM_OPERATOR, USER_INVITED, "user", owner_id)
            # The founding user's roles are role changes like any other (AC6, old NULL).
            await record_role_change(
                conn,
                org_id,
                PLATFORM_OPERATOR,
                owner_id,
                workspace_id=None,
                old=None,
                new="org_owner",
            )
            await record_role_change(
                conn,
                org_id,
                PLATFORM_OPERATOR,
                owner_id,
                workspace_id=ws_id,
                old=None,
                new="workspace_admin",
            )
    except IntegrityError as error:
        raise_if_violated(error, "organizations_name_lower_key", ORGANIZATION_NAME_TAKEN)
        raise
    return CreatedOrganization(org_id, org_name, ws_id, ws_name, owner_id, email, secret)


async def create_workspace(engine: AsyncEngine, org_id: uuid.UUID, name: str) -> CreatedWorkspace:
    """A Workspace in an existing Organization, with one audit event."""
    ws_name = normalise_workspace_name(name)
    try:
        async with engine.connect() as conn, tenant_transaction(conn, org_id):
            if not await organization_exists(conn, org_id):
                raise ProvisioningError(_ORG_NOT_FOUND)
            ws_id = await insert_workspace(conn, org_id, ws_name)
            await record_event(
                conn,
                org_id,
                PLATFORM_OPERATOR,
                WORKSPACE_CREATED,
                "workspace",
                ws_id,
            )
    except IntegrityError as error:
        raise_if_violated(
            error,
            "workspaces_org_id_name_key",
            "a Workspace with this name already exists in this Organization",
        )
        raise
    return CreatedWorkspace(ws_id, ws_name)


def _invite_roles(
    roles: Sequence[str], workspace_id: uuid.UUID | None
) -> tuple[str | None, str | None]:
    """(Organization role, Workspace role) of an invitation; checks the --workspace pairing."""
    org_role, workspace_role = split_roles(roles)
    if workspace_role is not None and workspace_id is None:
        raise ProvisioningError("a Workspace role needs --workspace")
    if workspace_id is not None and workspace_role is None:
        raise ProvisioningError("--workspace needs a Workspace role")
    return org_role, workspace_role


async def invite_user(
    engine: AsyncEngine,
    org_id: uuid.UUID,
    email: str,
    roles: Sequence[str],
    workspace_id: uuid.UUID | None = None,
    display_name: str | None = None,
) -> InvitedUser:
    """A user of the Organization with its roles, a set-password token and one audit event."""
    address = normalise_email(email)
    name = default_display_name(display_name, address)
    org_role, workspace_role = _invite_roles(roles, workspace_id)
    workspace = (workspace_id, workspace_role) if workspace_id and workspace_role else None
    try:
        async with engine.connect() as conn, tenant_transaction(conn, org_id):
            if not await organization_exists(conn, org_id):
                raise ProvisioningError(_ORG_NOT_FOUND)
            if workspace_id is not None and not await workspace_exists(conn, org_id, workspace_id):
                raise ProvisioningError("Workspace not found in this Organization")
            user_id, secret = await insert_member(conn, org_id, address, name, org_role, workspace)
            await record_event(conn, org_id, PLATFORM_OPERATOR, USER_INVITED, "user", user_id)
            if org_role is not None:
                await record_role_change(
                    conn,
                    org_id,
                    PLATFORM_OPERATOR,
                    user_id,
                    workspace_id=None,
                    old=None,
                    new=org_role,
                )
            if workspace is not None:
                await record_role_change(
                    conn,
                    org_id,
                    PLATFORM_OPERATOR,
                    user_id,
                    workspace_id=workspace[0],
                    old=None,
                    new=workspace[1],
                )
    except IntegrityError as error:
        raise_if_violated(
            error,
            "users_org_id_email_key",
            "a user with this email already exists in this Organization",
        )
        raise
    granted = tuple(role for role in (org_role, workspace_role) if role is not None)
    return InvitedUser(user_id, address, granted, secret)


async def issue_link(engine: AsyncEngine, org_id: uuid.UUID, email: str) -> IssuedLink:
    """A fresh set-password token for an existing user; the user's unused tokens are deleted."""
    address = normalise_email(email)
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        if not await organization_exists(conn, org_id):
            raise ProvisioningError(_ORG_NOT_FOUND)
        user_id = await find_user_id(conn, org_id, address)
        if user_id is None:
            raise ProvisioningError("user not found in this Organization")
        secret = await issue_token(conn, org_id, user_id)
        await record_event(
            conn,
            org_id,
            PLATFORM_OPERATOR,
            USER_SET_PASSWORD_LINK_ISSUED,
            "user",
            user_id,
        )
    return IssuedLink(user_id, secret)


def _workspace_role(role: str) -> str:
    """The role when it is a Workspace role; an Organization role is refused."""
    workspace_role = split_roles([role])[1]
    if workspace_role is None:
        raise ProvisioningError(_NOT_A_WORKSPACE_ROLE)
    return workspace_role


async def add_workspace_member(
    engine: AsyncEngine, org_id: uuid.UUID, workspace_id: uuid.UUID, email: str, role: str
) -> AddedMember:
    """Put an existing user of the Organization into one of its Workspaces, with one audit
    event. The user's Organization role and set-password state are not touched."""
    address = normalise_email(email)
    workspace_role = _workspace_role(role)
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        if not await organization_exists(conn, org_id):
            raise ProvisioningError(_ORG_NOT_FOUND)
        if not await workspace_exists(conn, org_id, workspace_id):
            raise ProvisioningError("Workspace not found in this Organization")
        user_id = await find_user_id(conn, org_id, address)
        if user_id is None:
            raise ProvisioningError("user not found in this Organization")
        if await workspace_member_exists(conn, org_id, workspace_id, user_id):
            raise ProvisioningError("the user is already a member of this Workspace")
        await insert_workspace_member(conn, org_id, workspace_id, user_id, workspace_role)
        await record_event(conn, org_id, PLATFORM_OPERATOR, WORKSPACE_MEMBER_ADDED, "user", user_id)
        await record_role_change(
            conn,
            org_id,
            PLATFORM_OPERATOR,
            user_id,
            workspace_id=workspace_id,
            old=None,
            new=workspace_role,
        )
    return AddedMember(user_id, address, workspace_role)
