"""The Platform Operator commands ``ei-ai index reindex``, ``index status`` and ``index search``.

Platform plane like ``ei-ai model``: the Organization comes from the operator's ``--org``. Each
document is indexed in its own tenant transaction, so one failure never rolls back the others.
Output is English only and carries ids, counts and codes, never chunk text or the query (D52).

Exit codes: 0 done, 1 failed, 2 refused (bad arguments).
"""

import argparse
import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import PLATFORM_OPERATOR
from ei_ai.db.engine import run_with_app_engine
from ei_ai.db.tenant import tenant_transaction
from ei_ai.jobs.envelope import JobContext, JobEnvelope
from ei_ai.jobs.registry import JobRegistry
from ei_ai.jobs.runner import run_tenant_job
from ei_ai.knowledge.indexing.embedder import ChunkEmbedder, GatewayEmbedder
from ei_ai.knowledge.indexing.embedding_model import platform_embedding_ref
from ei_ai.knowledge.indexing.index_rows import ready_document_ids
from ei_ai.knowledge.indexing.indexer import index_document
from ei_ai.knowledge.indexing.query import embed_query
from ei_ai.knowledge.indexing.status_rows import chunk_ordinals, index_counts
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
from ei_ai.vectors.search import ACCESS_LEVELS, MAX_K, VectorFilter, nearest

DEFAULT_K = 5
_DOCUMENT = "--document must be a document id (UUID)"
_COLLECTION = "--collection must be a collection id (UUID)"
_K = f"--k must be an integer from 1 to {MAX_K}"


def add_index_parsers(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add the ``index`` subcommands to the ``ei-ai`` parser."""
    index = commands.add_parser("index", help="vector index (Platform Operator)")
    actions = index.add_subparsers(dest="action", required=True)
    reindex = actions.add_parser("reindex", help="embed ready documents again")
    reindex.add_argument("--org", required=True, metavar="ORG_ID")
    reindex.add_argument("--document", metavar="DOCUMENT_ID")
    status = actions.add_parser("status", help="count indexed, not indexed and stale documents")
    status.add_argument("--org", required=True, metavar="ORG_ID")
    status.add_argument("--document", metavar="DOCUMENT_ID")
    search = actions.add_parser("search", help="nearest chunks of a text (ids only, no text)")
    search.add_argument("--org", required=True, metavar="ORG_ID")
    search.add_argument("--query", required=True, metavar="TEXT")
    search.add_argument("--k", default=str(DEFAULT_K), metavar="N")
    search.add_argument("--collection", metavar="COLLECTION_ID")


@asynccontextmanager
async def build_embedder(engine: AsyncEngine) -> AsyncIterator[ChunkEmbedder]:
    """The platform embedder over the Model Gateway; closes the gateway afterwards.

    Module-level so tests can replace it with a fake embedder. Raises ``SettingsError`` when
    ``EMBEDDING_MODEL_REF`` or the model settings are invalid.
    """
    ref = platform_embedding_ref(os.environ)
    gateway = build_gateway(ModelSettings.from_env(os.environ), engine)
    try:
        yield GatewayEmbedder(gateway, ref)
    finally:
        await gateway.aclose()


def _parse_uuid(raw: str | None, message: str) -> uuid.UUID | None:
    if raw is None:
        return None
    try:
        return uuid.UUID(raw.strip())
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


def _failure_label(error: Exception) -> str:
    return error.code.value if isinstance(error, ModelError) else type(error).__name__


async def _reindex_one(
    engine: AsyncEngine,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    embedder: ChunkEmbedder,
    ctx: ModelCallContext,
) -> int | None:
    """Reindexes one document in its own tenant transaction; the vector count, or None when the
    document is unknown, of another Organization or not ready."""
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        result = await index_document(conn, org_id, document_id, embedder, ctx)
    return None if result is None else result.vectors


async def _reindex(engine: AsyncEngine, org_id: uuid.UUID, document_id: uuid.UUID | None) -> int:
    await ensure_organization(engine, org_id)
    async with build_embedder(engine) as embedder:
        ctx = ModelCallContext(org_id=org_id, actor=PLATFORM_OPERATOR)
        if document_id is not None:
            ids = [document_id]
        else:
            async with engine.connect() as conn, tenant_transaction(conn, org_id):
                ids = await ready_document_ids(conn, org_id)
        documents = vectors = failed = 0
        for current in ids:
            try:
                count = await _reindex_one(engine, org_id, current, embedder, ctx)
            except Exception as error:
                failed += 1
                print(f"failed: {current} ({_failure_label(error)})")
                continue
            if count is None:
                if document_id is not None:
                    raise CommandFailed("document not found")
                continue  # no longer ready since the listing
            documents += 1
            vectors += count
            print(f"indexed: {current} vectors={count}")
        print(f"done: documents={documents} vectors={vectors} failed={failed} model={embedder.ref}")
    return 1 if failed else 0


async def _status(engine: AsyncEngine, org_id: uuid.UUID, document_id: uuid.UUID | None) -> int:
    await ensure_organization(engine, org_id)
    async with build_embedder(engine) as embedder:
        async with engine.connect() as conn, tenant_transaction(conn, org_id):
            counts = await index_counts(conn, org_id, embedder.ref, document_id)
        if counts is None:
            raise CommandFailed("document not found")
        print(
            f"ready_documents={counts.ready_documents} indexed={counts.indexed}"
            f" not_indexed={counts.not_indexed} stale={counts.stale} vectors={counts.vectors}"
            f" model={embedder.ref}"
        )
    return 0


async def _search(
    engine: AsyncEngine,
    org_id: uuid.UUID,
    query: str,
    k: int,
    collection_id: uuid.UUID | None,
) -> int:
    await ensure_organization(engine, org_id)
    async with build_embedder(engine) as embedder:
        ctx = ModelCallContext(org_id=org_id, actor=PLATFORM_OPERATOR)
        vector = await embed_query(embedder, ctx, query)
        # Operator tool with no principal: unfiltered by access level on purpose (not a user
        # path); only --collection narrows the search. A filter with no access levels matches
        # nothing, so --collection lists every level.
        where = (
            VectorFilter(
                collection_ids=(collection_id,), access_levels=tuple(sorted(ACCESS_LEVELS))
            )
            if collection_id
            else None
        )
        lines: list[str] = []
        # Only ``run_tenant_job`` builds the verified ``JobContext`` that ``nearest`` needs, so
        # the search runs as a one-off job on a private registry (not the global ``JOBS``).
        registry = JobRegistry()

        @registry.register("index.search")
        async def search_job(job: JobContext, payload: Mapping[str, object]) -> None:
            hits = await nearest(job.session, job, vector, k, model=embedder.ref, where=where)
            ordinals = await chunk_ordinals(job.session, job.org_id, [h.chunk_id for h in hits])
            lines.extend(
                f"{rank} distance={hit.distance:.4f} document={hit.document_id}"
                f" chunk={hit.chunk_id} ordinal={ordinals[hit.chunk_id]}"
                f" collection={hit.collection_id}"
                for rank, hit in enumerate(hits, start=1)
            )

        await run_tenant_job(engine, JobEnvelope("index.search", org_id, {}), registry)
    for line in lines:
        print(line)
    return 0


def run_index_command(args: argparse.Namespace) -> int:
    """Run one parsed ``index`` command; returns the exit code."""
    is_search = args.action == "search"
    try:
        org_id = parse_org_id(args.org)
        document_id = None if is_search else _parse_uuid(args.document, _DOCUMENT)
        k = _parse_k(args.k) if is_search else DEFAULT_K
        collection_id = _parse_uuid(args.collection, _COLLECTION) if is_search else None
    except CommandRefused as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        database_url = CliSettings.from_env(os.environ).database_url

        async def work(engine: AsyncEngine) -> int:
            if args.action == "reindex":
                return await _reindex(engine, org_id, document_id)
            if args.action == "status":
                return await _status(engine, org_id, document_id)
            return await _search(engine, org_id, args.query, k, collection_id)

        return asyncio.run(run_with_app_engine(database_url, work))
    except SettingsError as error:
        print(f"configuration error: {error}", file=sys.stderr)
    except ModelError as error:
        print(f"error: {error.code.value}: {error}", file=sys.stderr)
    except CommandFailed as error:
        print(f"error: {error}", file=sys.stderr)
    except Exception as error:
        print(f"error: index {args.action} failed ({type(error).__name__})", file=sys.stderr)
    return 1
