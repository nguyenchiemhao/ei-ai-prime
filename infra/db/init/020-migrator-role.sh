#!/bin/sh
# Creates the migration/owner login role (runs once, after 010-app-role.sh, as the superuser).
# ei_ai_migrator owns every table, function and the alembic_version table, and is the only role
# that may run DDL. It is not a superuser and cannot bypass RLS: the tables FORCE row-level security,
# so even the owner sees nothing without a tenant context. The application role (ei_ai_app) never
# owns anything; its grants on tables come from the migrations, which run as ei_ai_migrator.
set -eu

psql -v ON_ERROR_STOP=1 -v pw="$MIGRATION_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE ei_ai_migrator LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'pw';
GRANT CONNECT ON DATABASE ei_ai TO ei_ai_migrator;
GRANT USAGE, CREATE ON SCHEMA public TO ei_ai_migrator;
-- Explicit although PostgreSQL 15+ already withholds CREATE on public from everyone else.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
