"""Command line entry point: ``ei-ai seed demo``. Exit codes: 0 done, 1 failed, 2 refused/usage."""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

from ei_ai.readiness import check_database
from ei_ai.seed.demo import SeedRefused, run_demo_seed
from ei_ai.settings import Settings, SettingsError


def check_database_sync(database_url: str) -> None:
    asyncio.run(check_database(database_url))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ei-ai")
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed", help="load demo data")
    seed.add_subparsers(dest="dataset", required=True).add_parser(
        "demo", help="Mekong Devworks demo data (local and test only)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _parser().parse_args(argv)  # only "seed demo" exists; argparse exits 2 on anything else
    try:
        settings = Settings.from_env(os.environ)
    except SettingsError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 1
    try:
        summary = run_demo_seed(
            settings.environment, lambda: check_database_sync(settings.database_url)
        )
    except SeedRefused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        # Exception class only: messages can carry connection strings (D52).
        print(f"seed failed ({type(error).__name__})", file=sys.stderr)
        return 1
    print(summary)
    return 0
