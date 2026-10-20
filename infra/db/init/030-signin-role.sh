#!/bin/sh
# Creates the sign-in lookup login role (runs once, after 020-migrator-role.sh, as the superuser).
# EA-22 (R42, owner decision 2026-10-20): signing in by email + password has to find the user's
# Organization before any tenant is known, so this role is the only cross-tenant read. It gets
# CONNECT and schema USAGE here; its single grant, SELECT (id, org_id, email) ON users, and its
# one policy come from migration 0004 (run as ei_ai_migrator). Like every role it keeps the
# PostgreSQL PUBLIC defaults (TEMP on the database, EXECUTE on functions), which give no data
# access. It never owns an object, is a member of no role (NOINHERIT on top), cannot create
# objects in schema public and cannot bypass RLS.
set -eu

psql -v ON_ERROR_STOP=1 -v pw="$SIGNIN_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE ei_ai_signin LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'pw';
GRANT CONNECT ON DATABASE ei_ai TO ei_ai_signin;
GRANT USAGE ON SCHEMA public TO ei_ai_signin;
SQL
