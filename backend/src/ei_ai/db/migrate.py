"""Run the Alembic migrations from code (no alembic.ini).

``python -m ei_ai.db.migrate roundtrip`` (downgrade to base, then upgrade to head) exists for the
FND-01 verification only; it is refused unless EI_AI_ENV is local or test and is not exposed through
``ei-ai`` or an npm script.
"""

import os
import sys
from collections.abc import Sequence

import psycopg
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from ei_ai.db.catalog import read_catalog
from ei_ai.db.engine import to_libpq_url, to_sqlalchemy_url
from ei_ai.db.schema_guard import Violation, find_violations
from ei_ai.settings import MigrationSettings, SettingsError


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", "ei_ai.db:migrations")
    # Config values go through ConfigParser interpolation, so a literal "%" must be doubled.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade_head(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


def downgrade_base(url: str) -> None:
    command.downgrade(alembic_config(url), "base")


def current_revision(url: str) -> str | None:
    engine = create_engine(to_sqlalchemy_url(url))
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def guard_violations(url: str) -> list[Violation]:
    """Run the schema guard on the live database (as the migration role).

    The guard judges the schema after the migrations have been committed: it is a CI and review
    gate (``ei-ai db upgrade`` exits 1), not a runtime barrier that undoes an unsafe migration.
    """
    with psycopg.connect(to_libpq_url(url)) as connection:
        return find_violations(read_catalog(connection))


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["roundtrip"]:
        print("usage: python -m ei_ai.db.migrate roundtrip", file=sys.stderr)
        return 2
    if os.environ.get("EI_AI_ENV") not in ("local", "test"):
        print("refused: roundtrip runs only with EI_AI_ENV=local or test", file=sys.stderr)
        return 2
    try:
        url = MigrationSettings.from_env(os.environ).migration_database_url
    except SettingsError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 1
    downgrade_base(url)
    upgrade_head(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
