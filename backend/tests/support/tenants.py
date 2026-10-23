"""Test-only helpers: Organizations with one row in every tenant table, and their removal.

Never imported by ``src``. Rows are created through the application role in a tenant transaction
(exactly like the product), so the fixtures exercise the real policies and grants.
"""

import os
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import psycopg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.crypto.lifecycle import create_org_key
from ei_ai.db.tenant import tenant_transaction
from ei_ai.vectors.partitions import create_vector_partition, drop_vector_partition
from support.crypto import TEST_MASTER_KEY

# Every table of the schema, children first (the order in which fixture rows can be deleted).
DELETE_ORDER = (
    "chunk_embeddings",
    "document_chunks",
    "documents",
    "folders",
    "collections",
    "admin_sessions",
    "user_credentials",
    "audit_events",
    "set_password_tokens",
    "workspace_memberships",
    "memberships",
    "workspaces",
    "users",
    "model_catalog",
    "organization_keys",
    "organizations",
)


# Not a real hash: it only has to satisfy the argon2id prefix CHECK of ``user_credentials``.
FIXTURE_PASSWORD_HASH = "$argon2id$v=19$m=19456,t=2,p=1$fixture"

# The model row of every fixture Organization: the same ref everywhere, its own random digest.
FIXTURE_MODEL_ID = "fixture-chat"
FIXTURE_MODEL_VERSION = "v1"


def tenant_key_column(table: str) -> str:
    """The column that holds the Organization of a row (the Organization is its own tenant)."""
    return "id" if table == "organizations" else "org_id"


@dataclass(frozen=True)
class FixtureNames:
    """The visible names of the fixture rows of one Organization. They carry a random suffix, so
    no ordinary text ("user agent", "org admin") can contain one by accident."""

    organization: str
    workspace: str
    user: str


def fixture_names(label: str, suffix: str) -> FixtureNames:
    tag = f"{label} {suffix}"
    return FixtureNames(organization=f"Org {tag}", workspace=f"Workspace {tag}", user=f"User {tag}")


@dataclass(frozen=True)
class OrgRows:
    """The ids of the fixture rows of one Organization (all random UUIDv4)."""

    org_id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    workspace_membership_id: uuid.UUID
    audit_event_id: uuid.UUID
    set_password_token_id: uuid.UUID
    user_credential_id: uuid.UUID
    admin_session_id: uuid.UUID
    model_catalog_entry_id: uuid.UUID
    collection_id: uuid.UUID
    folder_id: uuid.UUID
    organization_key_id: uuid.UUID
    chunk_embedding_id: uuid.UUID
    # A second, empty folder: the folder DELETE isolation case needs one that holds no document.
    empty_folder_id: uuid.UUID
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    # The digest of the fixture model row: random, so each Organization has its own.
    model_digest: str
    label: str
    suffix: str

    @property
    def names(self) -> FixtureNames:
        return fixture_names(self.label, self.suffix)

    def row_id(self, table: str) -> uuid.UUID:
        return {
            "organizations": self.org_id,
            "workspaces": self.workspace_id,
            "users": self.user_id,
            "memberships": self.membership_id,
            "workspace_memberships": self.workspace_membership_id,
            "audit_events": self.audit_event_id,
            "set_password_tokens": self.set_password_token_id,
            "user_credentials": self.user_credential_id,
            "admin_sessions": self.admin_session_id,
            "model_catalog": self.model_catalog_entry_id,
            "collections": self.collection_id,
            "folders": self.folder_id,
            "organization_keys": self.organization_key_id,
            "chunk_embeddings": self.chunk_embedding_id,
            "empty_folders": self.empty_folder_id,
            "documents": self.document_id,
            "document_chunks": self.chunk_id,
        }[table]

    @property
    def email(self) -> str:
        return f"{self.user_id}@example.invalid"

    def markers(self) -> frozenset[str]:
        """Strings that identify this Organization's fixture data: every row id, the user's email
        and the names. Any of them in a response for another Organization is a leak."""
        names = self.names
        ids = {str(self.row_id(table)) for table in DELETE_ORDER}
        ids.add(str(self.empty_folder_id))
        return frozenset({*ids, self.email, names.organization, names.workspace, names.user})


@dataclass(frozen=True)
class TwoOrgs:
    a: OrgRows
    b: OrgRows


# Per table the app role may update: the column and a harmless value for the cross-org UPDATE test.
UPDATE_SETS = {
    "organizations": ("name", "renamed-by-intruder"),
    "workspaces": ("name", "renamed-by-intruder"),
    "users": ("display_name", "renamed-by-intruder"),
    "memberships": ("org_role", "org_admin"),
    "workspace_memberships": ("role", "viewer"),
    "audit_events": ("actor", "renamed-by-intruder"),
    "set_password_tokens": ("token_hash", "0" * 64),
    "user_credentials": ("failed_attempts", 3),
    "admin_sessions": ("token_hash", "0" * 64),
    "model_catalog": ("display_name", "renamed-by-intruder"),
    "collections": ("name", "renamed-by-intruder"),
    "folders": ("name", "renamed-by-intruder"),
    "organization_keys": ("kek_id", "0" * 16),
    "chunk_embeddings": ("created_at", datetime(2000, 1, 1, tzinfo=UTC)),
    "documents": ("name", "renamed-by-intruder"),
    "document_chunks": ("text", "renamed-by-intruder"),
}


async def create_org_rows(engine: AsyncEngine, label: str) -> OrgRows:
    rows = OrgRows(
        org_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        workspace_membership_id=uuid.uuid4(),
        audit_event_id=uuid.uuid4(),
        set_password_token_id=uuid.uuid4(),
        user_credential_id=uuid.uuid4(),
        admin_session_id=uuid.uuid4(),
        model_catalog_entry_id=uuid.uuid4(),
        collection_id=uuid.uuid4(),
        folder_id=uuid.uuid4(),
        organization_key_id=uuid.UUID(int=0),  # replaced once the key row exists
        chunk_embedding_id=uuid.uuid4(),
        empty_folder_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        model_digest=f"sha256:{secrets.token_hex(32)}",
        label=label,
        suffix=uuid.uuid4().hex[:8],
    )
    names = rows.names
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": rows.org_id, "name": names.organization},
        )
        await conn.execute(
            text("INSERT INTO workspaces (id, org_id, name) VALUES (:id, :org, :name)"),
            {"id": rows.workspace_id, "org": rows.org_id, "name": names.workspace},
        )
        await conn.execute(
            text(
                "INSERT INTO users (id, org_id, email, display_name)"
                " VALUES (:id, :org, :email, :name)"
            ),
            {
                "id": rows.user_id,
                "org": rows.org_id,
                "email": rows.email,
                "name": names.user,
            },
        )
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id) VALUES (:id, :org, :user)"),
            {"id": rows.membership_id, "org": rows.org_id, "user": rows.user_id},
        )
        await conn.execute(
            text(
                "INSERT INTO workspace_memberships (id, org_id, workspace_id, user_id, role)"
                " VALUES (:id, :org, :ws, :user, 'member')"
            ),
            {
                "id": rows.workspace_membership_id,
                "org": rows.org_id,
                "ws": rows.workspace_id,
                "user": rows.user_id,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO audit_events (id, org_id, actor, action, target_type, target_id)"
                " VALUES (:id, :org, 'platform-operator', 'organization.created',"
                " 'organization', :org)"
            ),
            {"id": rows.audit_event_id, "org": rows.org_id},
        )
        await conn.execute(
            text(
                "INSERT INTO set_password_tokens (id, org_id, user_id, token_hash, expires_at)"
                " VALUES (:id, :org, :user, :hash, now() + interval '24 hours')"
            ),
            {
                "id": rows.set_password_token_id,
                "org": rows.org_id,
                "user": rows.user_id,
                "hash": secrets.token_hex(32),
            },
        )
        await conn.execute(
            text(
                "INSERT INTO user_credentials (id, org_id, user_id, password_hash)"
                " VALUES (:id, :org, :user, :hash)"
            ),
            {
                "id": rows.user_credential_id,
                "org": rows.org_id,
                "user": rows.user_id,
                "hash": FIXTURE_PASSWORD_HASH,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO admin_sessions (id, org_id, user_id, token_hash)"
                " VALUES (:id, :org, :user, :hash)"
            ),
            {
                "id": rows.admin_session_id,
                "org": rows.org_id,
                "user": rows.user_id,
                "hash": secrets.token_hex(32),
            },
        )
        await conn.execute(
            text(
                "INSERT INTO model_catalog (id, org_id, kind, display_name, model_id, version,"
                " digest, deployment, provider)"
                " VALUES (:id, :org, 'chat', :name, :model_id, :version, :digest, 'local',"
                " 'local-chat')"
            ),
            {
                "id": rows.model_catalog_entry_id,
                "org": rows.org_id,
                "name": f"Model {label} {rows.suffix}",
                "model_id": FIXTURE_MODEL_ID,
                "version": FIXTURE_MODEL_VERSION,
                "digest": rows.model_digest,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO collections (id, org_id, workspace_id, name, access_level)"
                " VALUES (:id, :org, :ws, :name, 'authenticated')"
            ),
            {
                "id": rows.collection_id,
                "org": rows.org_id,
                "ws": rows.workspace_id,
                "name": f"Collection {label} {rows.suffix}",
            },
        )
        await conn.execute(
            text(
                "INSERT INTO folders (id, org_id, collection_id, name, depth)"
                " VALUES (:id, :org, :collection, :name, 1)"
            ),
            {
                "id": rows.folder_id,
                "org": rows.org_id,
                "collection": rows.collection_id,
                "name": f"Folder {label} {rows.suffix}",
            },
        )
        await conn.execute(
            text(
                "INSERT INTO folders (id, org_id, collection_id, name, depth)"
                " VALUES (:id, :org, :collection, :name, 1)"
            ),
            {
                "id": rows.empty_folder_id,
                "org": rows.org_id,
                "collection": rows.collection_id,
                "name": f"Empty folder {label} {rows.suffix}",
            },
        )
        await conn.execute(
            text(
                "INSERT INTO documents (id, org_id, collection_id, folder_id, name, format,"
                " size_bytes, status, page_count, chunk_count, extracted_text, uploaded_by,"
                " file_id)"
                " VALUES (:id, :org, :collection, :folder, :name, 'txt', 100, 'ready', 1, 1,"
                " 'qa', :user, gen_random_uuid())"
            ),
            {
                "id": rows.document_id,
                "org": rows.org_id,
                "collection": rows.collection_id,
                "folder": rows.folder_id,
                "name": f"Document {label} {rows.suffix}",
                "user": rows.user_id,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO document_chunks (id, org_id, document_id, ordinal, text,"
                " char_start, char_end, token_estimate)"
                " VALUES (:id, :org, :document, 0, 'qa', 0, 2, 1)"
            ),
            {"id": rows.chunk_id, "org": rows.org_id, "document": rows.document_id},
        )
        key_id = await create_org_key(conn, rows.org_id, TEST_MASTER_KEY)
    # The partition needs the owner role and the committed Organization row (R2, R24).
    with _migrator_connection() as migrator:
        create_vector_partition(migrator, rows.org_id)
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text(
                "INSERT INTO chunk_embeddings (id, org_id, embedding)"
                " VALUES (:id, :org, array_fill(0.1::real, ARRAY[1024])::vector)"
            ),
            {"id": rows.chunk_embedding_id, "org": rows.org_id},
        )
    return replace(rows, organization_key_id=key_id)


def _migrator_connection() -> psycopg.Connection:
    """Owner-role connection (autocommit) for the vector partition commands only."""
    return psycopg.connect(os.environ["MIGRATION_DATABASE_URL"], autocommit=True)


async def count_org_rows(engine: AsyncEngine, org_id: uuid.UUID) -> dict[str, int]:
    """Row count per tenant table for one Organization, read in its own tenant transaction."""
    counts = {}
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        for table in DELETE_ORDER:
            sql = f"SELECT count(*) FROM {table} WHERE {tenant_key_column(table)} = :org"
            counts[table] = (await conn.execute(text(sql), {"org": org_id})).scalar_one()
    return counts


async def purge_org_rows(engine: AsyncEngine, *orgs: OrgRows) -> None:
    """Delete everything the fixture Organizations own (see ``purge_org_ids``)."""
    await purge_org_ids(engine, *(org.org_id for org in orgs))


async def purge_org_ids(engine: AsyncEngine, *org_ids: uuid.UUID) -> None:
    """Delete everything an Organization owns through the application role, one tenant
    transaction per Organization: the fixture rows and any row a test created for it (e.g. by a
    positive-control POST, a CLI command or the provisioning service).

    This is the product path: every table has a DELETE grant and the standard policy, so no owner
    privilege is used and row-level security is never altered. The explicit ``org_id`` filter
    and the policy both apply. Afterwards the Organization's vector partition, if any, is dropped
    over an owner-role connection, so no empty partition is left behind.
    """
    for org_id in org_ids:
        async with engine.connect() as conn, tenant_transaction(conn, org_id):
            for table in DELETE_ORDER:
                key = tenant_key_column(table)
                await conn.execute(text(f"DELETE FROM {table} WHERE {key} = :org"), {"org": org_id})
    with _migrator_connection() as migrator:
        for org_id in org_ids:
            drop_vector_partition(migrator, org_id)
