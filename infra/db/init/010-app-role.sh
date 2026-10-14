#!/bin/sh
# Creates the application login role and the vector extension (runs once, when the data volume is
# first initialised, as the superuser). No table is created here: the schema, the role's grants on it
# and the RLS policies come from the migrations, which run as ei_ai_migrator (020-migrator-role.sh).
# The role can never bypass RLS and never owns an object.
set -eu

psql -v ON_ERROR_STOP=1 -v pw="$APP_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE ei_ai_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'pw';
GRANT CONNECT ON DATABASE ei_ai TO ei_ai_app;
GRANT USAGE ON SCHEMA public TO ei_ai_app;
CREATE EXTENSION IF NOT EXISTS vector;
SQL
