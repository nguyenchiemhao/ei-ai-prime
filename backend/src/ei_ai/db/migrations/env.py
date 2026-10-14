"""Alembic environment: online mode only, as the migration/owner role.

The URL is set in code (``ei_ai.db.migrate.alembic_config``) or read from
``MIGRATION_DATABASE_URL``.
"""

import os

from alembic import context
from sqlalchemy import create_engine, pool, text

from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.db.migrations.roles import check_migration_role
from ei_ai.settings import MigrationSettings

config = context.config


def _url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    return configured or MigrationSettings.from_env(os.environ).migration_database_url


def run_migrations_online() -> None:
    engine = create_engine(to_sqlalchemy_url(_url()), poolclass=pool.NullPool)
    with engine.connect() as connection:
        name, is_superuser = connection.execute(
            text("SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user")
        ).one()
        check_migration_role(name, is_superuser=is_superuser)
        connection.commit()  # end the implicit transaction of the role query
        context.configure(connection=connection, transaction_per_migration=True)
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("offline migrations are not supported (they would skip the role check)")
run_migrations_online()
