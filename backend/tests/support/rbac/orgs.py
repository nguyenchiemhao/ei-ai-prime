"""An Organization with named people in chosen roles, and a client that acts as any of them.

Test-only (never imported by ``src``). Rows are created through the application role in a tenant
transaction, like the product; ``purge_org_ids`` removes everything afterwards. The client uses the
production app with the static bearer verifier, so each person is a verified identity (D32).
"""

import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.principal import Principal
from ei_ai.crypto.lifecycle import create_org_key
from ei_ai.db.tenant import tenant_transaction
from ei_ai.knowledge.answers.chat_model import AnswerModel
from ei_ai.knowledge.indexing.embedder import ChunkEmbedder
from ei_ai.knowledge.retrieval.reranker import Reranker
from ei_ai.main import create_app
from ei_ai.readiness import Readiness
from ei_ai.storage.files import OrgFileStore
from support.crypto import TEST_MASTER_KEY
from support.identity import StaticBearerVerifier

# (Organization role, {workspace key: Workspace role})
PersonSpec = tuple[str | None, Mapping[str, str]]


@dataclass(frozen=True)
class Person:
    name: str
    user_id: uuid.UUID
    email: str
    display_name: str
    token: str


@dataclass(frozen=True)
class RoleOrg:
    org_id: uuid.UUID
    workspaces: Mapping[str, uuid.UUID]
    people: Mapping[str, Person]
    suffix: str

    def headers(self, name: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.people[name].token}"}

    def user(self, name: str) -> uuid.UUID:
        return self.people[name].user_id

    def workspace(self, key: str) -> uuid.UUID:
        return self.workspaces[key]


async def create_role_org(
    engine: AsyncEngine,
    people: Mapping[str, PersonSpec],
    workspaces: Sequence[str] = ("x", "y"),
) -> RoleOrg:
    """An Organization with the Workspaces ``workspaces`` and one user per entry of ``people``,
    created in that order (so the member order of a Workspace is the order given)."""
    suffix = uuid.uuid4().hex[:8]
    org_id = uuid.uuid4()
    workspace_ids = {key: uuid.uuid4() for key in workspaces}
    persons: dict[str, Person] = {}
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:org, :name)"),
            {"org": org_id, "name": f"Org roles {suffix}"},
        )
        for key, workspace_id in workspace_ids.items():
            await conn.execute(
                text("INSERT INTO workspaces (id, org_id, name) VALUES (:id, :org, :name)"),
                {"id": workspace_id, "org": org_id, "name": f"Workspace {key} {suffix}"},
            )
        for name, (org_role, roles) in people.items():
            person = Person(
                name=name,
                user_id=uuid.uuid4(),
                email=f"{name}-{suffix}@example.invalid",
                display_name=f"Person {name} {suffix}",
                token=f"token-{name}-{suffix}",
            )
            persons[name] = person
            await conn.execute(
                text(
                    "INSERT INTO users (id, org_id, email, display_name)"
                    " VALUES (:id, :org, :email, :name)"
                ),
                {
                    "id": person.user_id,
                    "org": org_id,
                    "email": person.email,
                    "name": person.display_name,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO memberships (org_id, user_id, org_role)"
                    " VALUES (:org, :user, :role)"
                ),
                {"org": org_id, "user": person.user_id, "role": org_role},
            )
            for key, role in roles.items():
                await conn.execute(
                    text(
                        "INSERT INTO workspace_memberships (org_id, workspace_id, user_id, role)"
                        " VALUES (:org, :ws, :user, :role)"
                    ),
                    {
                        "org": org_id,
                        "ws": workspace_ids[key],
                        "user": person.user_id,
                        "role": role,
                    },
                )
        # Uploads encrypt with the Organization's data key, as for a provisioned Organization.
        await create_org_key(conn, org_id, TEST_MASTER_KEY)
    return RoleOrg(org_id=org_id, workspaces=workspace_ids, people=persons, suffix=suffix)


async def _ok() -> None:
    return None


def role_app(
    engine: AsyncEngine,
    orgs: Sequence[RoleOrg],
    extra_routers: Sequence[APIRouter] = (),
    file_store: OrgFileStore | None = None,
    embedder: ChunkEmbedder | None = None,
    answer_model: AnswerModel | None = None,
    reranker: Reranker | None = None,
) -> FastAPI:
    """The production app where every person of ``orgs`` can authenticate with their token.
    ``file_store`` is where originals go (none: uploads cannot store a file); ``embedder``,
    ``answer_model`` and ``reranker`` are the models of the ask route (none: it answers 503)."""
    principals = {
        person.token: Principal(user_id=person.user_id, org_id=org.org_id)
        for org in orgs
        for person in org.people.values()
    }
    app = create_app(
        readiness=Readiness(database=_ok, valkey=_ok),
        identity_verifiers=(StaticBearerVerifier(principals),),
        engine=engine,
        file_store=file_store,
        embedder=embedder,
        answer_model=answer_model,
        reranker=reranker,
    )
    for router in extra_routers:
        app.include_router(router)
    return app


@asynccontextmanager
async def role_client(
    engine: AsyncEngine,
    *orgs: RoleOrg,
    extra_routers: Sequence[APIRouter] = (),
    file_store: OrgFileStore | None = None,
    embedder: ChunkEmbedder | None = None,
    answer_model: AnswerModel | None = None,
    reranker: Reranker | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    app = role_app(engine, orgs, extra_routers, file_store, embedder, answer_model, reranker)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
