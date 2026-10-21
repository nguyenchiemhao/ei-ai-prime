"""The Platform Operator commands ``ei-ai model add`` and ``ei-ai model try`` (EA-24).

The Organization comes from the operator's ``--org`` (platform plane, like ``ei-ai org``).
Output is English only. Unexpected errors print the exception class only: their messages can hold
SQL values, URLs or connection strings (D52).

Exit codes: 0 done, 1 failed, 2 refused (bad arguments).
"""

import argparse
import asyncio
import logging
import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import MODEL_CATALOG_ENTRY_ADDED, PLATFORM_OPERATOR, record_event
from ei_ai.db.engine import run_with_app_engine
from ei_ai.db.tenant import tenant_transaction
from ei_ai.model_gateway.catalog_rows import insert_manifest_entry
from ei_ai.model_gateway.cli_common import (
    CommandFailed,
    CommandRefused,
    organization_exists,
    parse_max_tokens,
    parse_org_id,
    parse_ref,
)
from ei_ai.model_gateway.errors import ModelError
from ei_ai.model_gateway.manifest import load_platform_models
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.model_gateway.try_command import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_PROMPT,
    TryRequest,
    try_model,
)
from ei_ai.settings import CliSettings, ModelSettings, SettingsError


def add_model_parsers(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add the ``model`` subcommands to the ``ei-ai`` parser."""
    model = commands.add_parser("model", help="model catalog (Platform Operator)")
    actions = model.add_subparsers(dest="action", required=True)
    add = actions.add_parser("add", help="copy a platform model into an Organization's catalog")
    add.add_argument("--org", required=True, metavar="ORG_ID")
    add.add_argument("--model", required=True, metavar="MODEL_ID@VERSION")
    try_ = actions.add_parser("try", help="stream one chat answer through the Model Gateway")
    try_.add_argument("--org", required=True, metavar="ORG_ID")
    try_.add_argument("--model", required=True, metavar="MODEL_ID@VERSION")
    try_.add_argument("--prompt", default=DEFAULT_PROMPT, metavar="TEXT")
    try_.add_argument("--max-tokens", default=str(DEFAULT_MAX_TOKENS), metavar="N")


async def add_model(engine: AsyncEngine, org_id: uuid.UUID, ref: ModelRef) -> str:
    """Copy the manifest entry of ``ref`` into the Organization's catalog, audited once, in one
    tenant transaction. Returns the stdout line."""
    models = load_platform_models()
    entry = models.find(ref)
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        if not await organization_exists(conn, org_id):
            raise CommandFailed("Organization not found")
        if entry is None:
            raise CommandFailed(f"unknown model {ref}; known: {', '.join(models.known_refs())}")
        new_id = await insert_manifest_entry(conn, org_id, entry)
        if new_id is None:
            return f"already present: {ref}"
        await record_event(
            conn, org_id, PLATFORM_OPERATOR, MODEL_CATALOG_ENTRY_ADDED, "model", new_id
        )
    return f"added: {ref} ({entry.kind}, {entry.deployment})"


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


@contextmanager
def _gateway_log_silenced() -> Iterator[None]:
    """The CLI prints its own ``done:``/error line: the gateway's metadata line must not reach
    stderr through Python's last-resort handler during the run."""
    gateway_logger = logging.getLogger("ei_ai.model_gateway")
    handler, propagate = logging.NullHandler(), gateway_logger.propagate
    gateway_logger.addHandler(handler)
    gateway_logger.propagate = False
    try:
        yield
    finally:
        gateway_logger.removeHandler(handler)
        gateway_logger.propagate = propagate


def _parse(args: argparse.Namespace) -> TryRequest:
    """The checked arguments, before any setting is read (exit 2 wins over exit 1)."""
    is_try = args.action == "try"
    return TryRequest(
        org_id=parse_org_id(args.org),
        ref=parse_ref(args.model),
        prompt=args.prompt if is_try else DEFAULT_PROMPT,
        max_tokens=parse_max_tokens(args.max_tokens) if is_try else DEFAULT_MAX_TOKENS,
    )


def _run_add(request: TryRequest, database_url: str) -> int:
    line = asyncio.run(
        run_with_app_engine(database_url, lambda e: add_model(e, request.org_id, request.ref))
    )
    print(line)
    return 0


def _run_try(request: TryRequest, database_url: str) -> int:
    settings = ModelSettings.from_env(os.environ)
    streamed = False

    def write(text: str) -> None:
        nonlocal streamed
        streamed = True
        _write(text)

    try:
        with _gateway_log_silenced():
            line = asyncio.run(try_model(database_url, settings, request, write))
    finally:
        if streamed:
            _write("\n")
    print(line)
    return 0


def run_model_command(args: argparse.Namespace) -> int:
    """Run one parsed ``model`` command; returns the exit code."""
    try:
        request = _parse(args)
    except CommandRefused as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        database_url = CliSettings.from_env(os.environ).database_url
        run = _run_add if args.action == "add" else _run_try
        return run(request, database_url)
    except SettingsError as error:
        print(f"configuration error: {error}", file=sys.stderr)
    except ModelError as error:
        print(f"error: {error.code.value}: {error}", file=sys.stderr)
    except CommandFailed as error:
        print(f"error: {error}", file=sys.stderr)
    except Exception as error:
        print(f"error: model {args.action} failed ({type(error).__name__})", file=sys.stderr)
    return 1
