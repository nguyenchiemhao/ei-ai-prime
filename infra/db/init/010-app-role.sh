#!/bin/sh
# Creates the application login role and the vector extension (runs once, when the data volume is
# first initialised, as the superuser). No table is created here: the schema, the roles' grants on it
# and the RLS policies belong to the migrations of FND-01. The role can never bypass RLS.
set -eu

psql -v ON_ERROR_STOP=1 -v pw="$APP_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE ei_ai_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'pw';
GRANT CONNECT ON DATABASE ei_ai TO ei_ai_app;
GRANT USAGE ON SCHEMA public TO ei_ai_app;
CREATE EXTENSION IF NOT EXISTS vector;
SQL
