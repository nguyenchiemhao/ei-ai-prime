"""The Platform Operator command ``ei-ai index retrieve`` (EA-36): the shared ``retrieve()`` as a
simulated person over a Workspace or chosen collections and folders.

Prints the principal, the searched and skipped scope, the passages and a summary: ids, counts and
scores only, never chunk text or the query (D52). Arguments are checked before any database or
model access. Exit codes: 0 done (also with 0 passages), 1 failed, 2 refused.
"""

import argparse
import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import PLATFORM_OPERATOR
from ei_ai.db.engine import run_with_app_engine
from ei_ai.jobs.envelope import JobContext, JobEnvelope
from ei_ai.jobs.registry import JobRegistry
from ei_ai.jobs.runner import run_tenant_job
from ei_ai.knowledge.errors import InvalidGroup
from ei_ai.knowledge.retrieval.principal import RetrievalPrincipal, simulated_principal
from ei_ai.knowledge.retrieval.reranker import GatewayReranker, Reranker, platform_rerank_ref
from ei_ai.knowledge.retrieval.scope import KnowledgeScope
from ei_ai.knowledge.retrieval.scope_rows import workspace_collection_ids, workspace_exists
from ei_ai.knowledge.retrieval.service import (
    DEFAULT_K,
    MAX_K,
    MAX_QUESTION_CHARS,
    RetrievalResult,
    retrieve,
)
from ei_ai.model_gateway.cli_common import (
    CommandFailed,
    CommandRefused,
    ensure_organization,
    parse_org_id,
)
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError
from ei_ai.model_gateway.factory import build_gateway
from ei_ai.settings import CliSettings, ModelSettings, SettingsError

_WORKSPACE = "--workspace must be a Workspace id (UUID)"
_COLLECTION = "--collection must be a collection id (UUID)"
_FOLDER = "--folder must be a folder id (UUID)"
_K = f"--k must be an integer from 1 to {MAX_K}"
_AS = "--as must be anonymous or authenticated"
_GROUP_NEEDS_AUTH = "--group needs --as authenticated"
_GROUP = "--group must be a valid group name (at most 100)"
_QUERY = f"--query must be 1 to {MAX_QUESTION_CHARS} characters"


@dataclass(frozen=True)
class RetrieveArgs:
    org_id: uuid.UUID
    workspace_id: uuid.UUID
    query: str
    principal: RetrievalPrincipal
    collection_ids: tuple[uuid.UUID, ...]
    folder_ids: tuple[uuid.UUID, ...]
    k: int


def add_retrieve_parser(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add ``index retrieve``; ``--as`` and ``--k`` are checked by hand so the messages are ours."""
    parser = actions.add_parser(
        "retrieve", help="permission-filtered passages as a simulated person (ids only, no text)"
    )
    parser.add_argument("--org", required=True, metavar="ORG_ID")
    parser.add_argument("--workspace", required=True, metavar="WORKSPACE_ID")
    parser.add_argument("--query", required=True, metavar="TEXT")
    parser.add_argument("--as", dest="principal", metavar="anonymous|authenticated")
    parser.add_argument("--group", action="append", default=[], metavar="NAME")
    parser.add_argument("--collection", action="append", default=[], metavar="COLLECTION_ID")
    parser.add_argument("--folder", action="append", default=[], metavar="FOLDER_ID")
    parser.add_argument("--k", default=str(DEFAULT_K), metavar="N")


def _uuids(raw: Sequence[str], message: str) -> tuple[uuid.UUID, ...]:
    try:
        return tuple(uuid.UUID(value.strip()) for value in raw)
    except ValueError:
        raise CommandRefused(message) from None


def _parse_k(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise CommandRefused(_K) from None
    if not 1 <= value <= MAX_K:
        raise CommandRefused(_K)
    return value


def _principal(kind: str | None, groups: Sequence[str]) -> RetrievalPrincipal:
    if kind == "anonymous":
        if groups:
            raise CommandRefused(_GROUP_NEEDS_AUTH)
        return simulated_principal("anonymous")
    if kind != "authenticated":
        raise CommandRefused(_AS)
    try:
        return simulated_principal("authenticated", groups)
    except InvalidGroup:
        raise CommandRefused(_GROUP) from None


def parse_arguments(args: argparse.Namespace) -> RetrieveArgs:
    """The checked arguments; ``CommandRefused`` (exit 2) for the first bad one."""
    org_id = parse_org_id(args.org)
    workspace_id = _uuids([args.workspace], _WORKSPACE)[0]
    collections = _uuids(args.collection, _COLLECTION)
    folders = _uuids(args.folder, _FOLDER)
    k = _parse_k(args.k)
    principal = _principal(args.principal, args.group)
    query = args.query.strip()
    if not 1 <= len(query) <= MAX_QUESTION_CHARS:
        raise CommandRefused(_QUERY)
    return RetrieveArgs(org_id, workspace_id, query, principal, collections, folders, k)


@asynccontextmanager
async def build_reranker(engine: AsyncEngine) -> AsyncIterator[Reranker | None]:
    """The platform reranker over the Model Gateway, or ``None`` when ``RERANK_MODEL_REF`` is
    unset; closes the gateway afterwards. Module-level so tests can replace it. Raises
    ``SettingsError`` for a value that is not a local rerank model of the manifest."""
    ref = platform_rerank_ref(os.environ)
    if ref is None:
        yield None
        return
    gateway = build_gateway(ModelSettings.from_env(os.environ), engine)
    try:
        yield GatewayReranker(gateway, ref)
    finally:
        await gateway.aclose()


def _lines(result: RetrievalResult) -> list[str]:
    trace = result.trace
    lines = [
        f"principal: {trace.principal} groups={trace.group_count} simulated=yes",
        *(f"searched: {collection_id}" for collection_id in trace.searched),
        *(f"skipped: {s.id} kind={s.kind} reason={s.reason}" for s in trace.skipped),
    ]
    for rank, passage in enumerate(result.passages, start=1):
        rerank = "-" if passage.rerank_score is None else f"{passage.rerank_score:.4f}"
        lines.append(
            f"passage: {rank} chunk={passage.chunk_id} document={passage.document_id}"
            f" collection={passage.collection_id} ordinal={passage.ordinal}"
            f" score={passage.retrieval_score:.4f} rerank={rerank}"
        )
    lines.append(
        f"done: searched={len(trace.searched)} skipped={len(trace.skipped)}"
        f" candidates={len(trace.candidates)} passages={len(result.passages)}"
        f" retrieval=vector rerank={trace.rerank}"
    )
    return lines


async def _retrieve(engine: AsyncEngine, args: RetrieveArgs) -> int:
    from ei_ai.knowledge.indexing import commands  # late: commands imports this module

    await ensure_organization(engine, args.org_id)
    results: list[RetrievalResult] = []
    async with commands.build_embedder(engine) as embedder, build_reranker(engine) as reranker:
        ctx = ModelCallContext(org_id=args.org_id, actor=PLATFORM_OPERATOR)
        # Only ``run_tenant_job`` builds the verified ``JobContext`` that ``nearest`` needs, so
        # the retrieval runs as a one-off job on a private registry (not the global ``JOBS``).
        registry = JobRegistry()

        @registry.register("index.retrieve")
        async def retrieve_job(job: JobContext, payload: Mapping[str, object]) -> None:
            conn = await job.session.connection()
            if not await workspace_exists(conn, job.org_id, args.workspace_id):
                raise CommandFailed("workspace not found")
            collections = args.collection_ids
            if not collections and not args.folder_ids:
                collections = await workspace_collection_ids(conn, job.org_id, args.workspace_id)
            scope = KnowledgeScope(args.workspace_id, collections, args.folder_ids)
            results.append(
                await retrieve(
                    job.session,
                    job,
                    args.query,
                    args.principal,
                    scope,
                    embedder=embedder,
                    ctx=ctx,
                    reranker=reranker,
                    k=args.k,
                )
            )

        await run_tenant_job(engine, JobEnvelope("index.retrieve", args.org_id, {}), registry)
    for line in _lines(results[0]):
        print(line)
    return 0


def run_retrieve_command(args: argparse.Namespace) -> int:
    """Run ``index retrieve``; returns the exit code."""
    try:
        parsed = parse_arguments(args)
    except CommandRefused as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        database_url = CliSettings.from_env(os.environ).database_url

        async def work(engine: AsyncEngine) -> int:
            return await _retrieve(engine, parsed)

        return asyncio.run(run_with_app_engine(database_url, work))
    except SettingsError as error:
        print(f"configuration error: {error}", file=sys.stderr)
    except ModelError as error:
        print(f"error: {error.code.value}: {error}", file=sys.stderr)
    except CommandFailed as error:
        print(f"error: {error}", file=sys.stderr)
    except Exception as error:
        print(f"error: index retrieve failed ({type(error).__name__})", file=sys.stderr)
    return 1
