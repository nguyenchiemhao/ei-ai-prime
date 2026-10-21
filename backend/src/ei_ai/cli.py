"""Command line entry point: ``ei-ai seed demo``, ``ei-ai db upgrade``, ``ei-ai db current`` and
the Platform Operator commands ``org create``, ``workspace create``, ``user invite``, ``user link``,
``model add`` and ``model try``.

Exit codes: 0 done, 1 failed, 2 refused/usage.
"""

import argparse
import os
import sys
from collections.abc import Sequence

from ei_ai.db.migrate import current_revision, guard_violations, upgrade_head
from ei_ai.db.migrations.roles import MigrationRoleError
from ei_ai.model_gateway.commands import add_model_parsers, run_model_command
from ei_ai.provisioning.commands import (
    COMMAND_GROUPS,
    add_provisioning_parsers,
    run_provisioning_command,
)
from ei_ai.provisioning.validation import ProvisioningError
from ei_ai.seed.demo import SeedRefused, load_demo_data, run_demo_seed
from ei_ai.settings import MigrationSettings, SettingsError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ei-ai")
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed", help="load demo data")
    seed.add_subparsers(dest="dataset", required=True).add_parser(
        "demo", help="Mekong Devworks demo data (local and test only)"
    )
    database = commands.add_parser("db", help="database migrations (run as the migration role)")
    actions = database.add_subparsers(dest="action", required=True)
    actions.add_parser("upgrade", help="apply migrations to head, then run the schema guard")
    actions.add_parser("current", help="print the current revision")
    add_provisioning_parsers(commands)
    add_model_parsers(commands)
    return parser


def _seed() -> int:
    # The guard needs only EI_AI_ENV (unset means production): it runs before any other setting
    # is read, so a refused seed exits 2 whatever else is configured.
    environment = os.environ.get("EI_AI_ENV", "production")
    try:
        summary = run_demo_seed(environment, lambda manifest: load_demo_data(os.environ, manifest))
    except SeedRefused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    except SettingsError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 1
    except ProvisioningError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        # Exception class only: messages can carry connection strings (D52).
        print(f"error: seed demo failed ({type(error).__name__})", file=sys.stderr)
        return 1
    print(summary)
    return 0


def _migration_url() -> str | None:
    try:
        return MigrationSettings.from_env(os.environ).migration_database_url
    except SettingsError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return None


def _db_upgrade() -> int:
    url = _migration_url()
    if url is None:
        return 1
    try:
        upgrade_head(url)
        print(f"database revision: {current_revision(url)}")
        violations = guard_violations(url)
    except MigrationRoleError as error:
        print(f"db upgrade refused: {error}", file=sys.stderr)  # our own safe message
        return 1
    except Exception as error:
        # Exception class only: messages can carry connection strings (D52).
        print(f"db upgrade failed ({type(error).__name__})", file=sys.stderr)
        return 1
    for violation in violations:
        print(f"schema guard: {violation}", file=sys.stderr)
    if violations:
        print(f"schema guard: {len(violations)} violations", file=sys.stderr)
        return 1
    print("schema guard: 0 violations")
    return 0


def _db_current() -> int:
    url = _migration_url()
    if url is None:
        return 1
    try:
        print(f"database revision: {current_revision(url)}")
    except Exception as error:
        print(f"db current failed ({type(error).__name__})", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)  # argparse exits 2 on anything unknown
    if args.command == "seed":
        return _seed()
    if args.command in COMMAND_GROUPS:
        return run_provisioning_command(args)
    if args.command == "model":
        return run_model_command(args)
    return _db_upgrade() if args.action == "upgrade" else _db_current()
