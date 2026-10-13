-- EA-11 PoC: two-layer tenant isolation in PostgreSQL (D46, F1, F2).
--   Layer 1 (application): every query carries an explicit "org_id = <org>" filter.
--   Layer 2 (database):    row-level security on every table, driven by a transaction-local setting.
-- This file runs once as the superuser "postgres" on first database start. In the product the same
-- statements live in Alembic migrations (FND-01), with each policy created in the migration of its table.

CREATE EXTENSION IF NOT EXISTS vector;

-- Application role (F1). It must never own tables, be a superuser or bypass RLS: owners and
-- BYPASSRLS roles skip all policies. The superuser "postgres" plays the migration/provisioning role.
CREATE ROLE poc_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT USAGE ON SCHEMA public TO poc_app;

-- Every table carries org_id (F1). "organizations" is keyed by id, so its RLS key is id.
CREATE TABLE organizations (
    id   uuid PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE documents (
    id     uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    title  text NOT NULL,
    -- Target of the composite foreign key below.
    UNIQUE (org_id, id)
);

-- Vectors (F2): one LIST partition per Organization, each with its own HNSW index (see provision_org).
-- 8 dimensions are enough for the PoC; the ADR records 1024 for bge-m3.
-- The composite foreign key (org_id, document_id) blocks cross-Organization references. This is
-- needed because referential-integrity checks bypass RLS (PostgreSQL docs, "Row Security Policies").
CREATE TABLE chunk_embeddings (
    org_id      uuid NOT NULL,
    id          uuid NOT NULL,
    document_id uuid NOT NULL,
    content     text NOT NULL,
    embedding   vector(8) NOT NULL,
    PRIMARY KEY (org_id, id),
    FOREIGN KEY (org_id, document_id) REFERENCES documents (org_id, id)
) PARTITION BY LIST (org_id);

-- Row-level security (F1, D46). FORCE makes the table owner subject to the policies as well.
-- NULLIF is required: after a transaction that used set_config(..., true) ends, current_setting()
-- returns '' (not NULL) in the same session, and ''::uuid would raise instead of matching nothing.
-- With no tenant context the key is NULL, the comparison is NULL and no row is visible.
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON organizations
    FOR ALL TO poc_app
    USING (id = NULLIF(current_setting('app.current_org', true), '')::uuid)
    WITH CHECK (id = NULLIF(current_setting('app.current_org', true), '')::uuid);

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents
    FOR ALL TO poc_app
    USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid);

-- The policy on the partitioned parent applies to every query that goes through the parent.
ALTER TABLE chunk_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunk_embeddings FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON chunk_embeddings
    FOR ALL TO poc_app
    USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid);

-- Grants only on the parent tables. Partitions get NO grants, so a direct "SELECT ... FROM <partition>"
-- (which would skip the parent's policy) is denied to the application role (D46, pitfall P62).
GRANT SELECT, INSERT, UPDATE, DELETE ON organizations, documents, chunk_embeddings TO poc_app;

-- Provisions one Organization: row + vector partition + HNSW index (F2).
-- Platform-operator path only (the FND-04 CLI in the product). It is never called from request
-- handling and the application role has no EXECUTE right on it.
CREATE FUNCTION provision_org(p_org uuid, p_name text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_partition text := 'chunk_embeddings_' || replace(p_org::text, '-', '_');
BEGIN
    INSERT INTO organizations (id, name) VALUES (p_org, p_name);
    EXECUTE format(
        'CREATE TABLE %I PARTITION OF chunk_embeddings FOR VALUES IN (%L)',
        v_partition, p_org
    );
    -- The per-Organization vector index: one HNSW graph per Organization, so one tenant's vectors
    -- never influence another tenant's recall or latency.
    EXECUTE format(
        'CREATE INDEX %I ON %I USING hnsw (embedding vector_cosine_ops)',
        v_partition || '_hnsw', v_partition
    );
END;
$$;

REVOKE ALL ON FUNCTION provision_org(uuid, text) FROM PUBLIC;
