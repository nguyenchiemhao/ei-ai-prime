# Key management and the vector namespace

EA-20 (FND-03). Each Organization has its own data key. Original files are stored encrypted with it, and each Organization's vectors live in their own partition (D46, ADR-001 section 3.3). This document is the operating guide. No route encrypts yet: the first callers are KB-02 (upload) and WGT-08 (conversations).

## Master key (KEK)

- One platform master key of 32 random bytes, written as exactly 64 hexadecimal characters. It wraps the data keys and protects nothing else.
- Source, exactly one of two: `EI_AI_MASTER_KEY` (the value) or `EI_AI_MASTER_KEY_FILE` (path to a file holding the 64 characters, for a Docker or Kubernetes secret mount). Both set, or neither, is a configuration error (below). Surrounding whitespace is stripped.
- Local development: `npm run up`, `npm run migrate`, `npm run reset` and `npm run backend -- <task>` generate a key into `.env` (git-ignored) on first run. They append it to an existing `.env` that lacks it and never change an existing value.
- Only the `api` and `backend-tools` services receive it. The `db`, `migrate`, `valkey`, `model`, `admin` and `widget` services never do, and the database never sees it.
- `kek_id` is a non-secret fingerprint (the first 16 hex characters of an HMAC of the key) stored with every wrapped data key. A wrong master key fails with `MasterKeyMismatch` instead of a generic error, and a later rotation can tell keys apart.
- The key is never logged, printed or put into an exception. Configuration errors name the variable, never the value, the path or the file content, and are printed by `org create` and `seed demo` with exit 1 and nothing written:

| Condition | Line |
|---|---|
| neither variable set (or both empty) | `configuration error: EI_AI_MASTER_KEY or EI_AI_MASTER_KEY_FILE is required` |
| both set | `configuration error: set only one of EI_AI_MASTER_KEY and EI_AI_MASTER_KEY_FILE` |
| `EI_AI_MASTER_KEY` not 64 hex characters | `configuration error: EI_AI_MASTER_KEY must be 64 hexadecimal characters` |
| `EI_AI_MASTER_KEY_FILE` missing, a directory or unreadable | `configuration error: EI_AI_MASTER_KEY_FILE cannot be read` |
| file content not 64 hex characters | `configuration error: EI_AI_MASTER_KEY_FILE must hold 64 hexadecimal characters` |

### Back up the master key

**Losing the master key loses the data.** Every data key is wrapped with it, so without it no Organization's encrypted file or conversation can be decrypted, and nothing can restore them. Store a copy outside the machine and outside the repository (a password manager or a secret store), separate from the database backups. In production, mount it as a secret file (`EI_AI_MASTER_KEY_FILE`). Rotation of the master key is out of scope for this ticket.

## Data keys and their storage

- One data key (DEK) per Organization: 32 random bytes generated in the application. It is never stored or logged in plaintext.
- It is stored wrapped, in table `organization_keys` (migration 0008): AES-256-GCM with the master key, a random 12-byte nonce and the Organization id as associated data. The 60-byte value is `nonce (12) || ciphertext (32) || tag (16)`. The associated data binds a wrapped key to its Organization: a row copied to another Organization does not unwrap.
- One row per Organization (unique `org_id`), with the standard tenant row-level security and DML grants. `destroyed_at` is set if and only if `wrapped_key` is NULL.
- **Never downgrade migration 0008 on a database that holds encrypted data:** the downgrade drops `organization_keys`, which destroys every wrapped key and crypto-shreds every Organization.
- `org create` creates the key with the Organization. There is no lazy creation on the tenant plane: encrypting for an Organization without a key fails closed with `KeyNotFound`.
- Organizations created before migration 0008 have no key. The migration cannot create one (the migrator has no master key and cannot see Organizations). The two demo Organizations get theirs the next time `npm run seed` runs (it adds a missing key and never replaces or recreates one). Any other older Organization has none until `npm run reset` or until it is created again (R33). There is no production data yet.

## Encrypt and decrypt

- `OrgCipher` (`backend/src/ei_ai/crypto/cipher.py`) takes the verified `TenantContext` (route) or `JobContext` (job) and the tenant session. The Organization never comes from a request body or a parameter (D32). Anything else raises `TypeError`.
- Every call reads the key row (with the explicit `org_id` filter and row-level security), unwraps it and seals or opens the data. There is no cache of unwrapped keys, so destroying a key takes effect at once.
- Blob format: the bytes `EIA` and `0x01` (magic and format version 1), then the nonce (12), the ciphertext and the tag (16), AES-256-GCM with the Organization's data key and associated data bound to the Organization id. Overhead 32 bytes. A wrong magic, a short blob, a tag mismatch or another Organization's context raises `DecryptionFailed` and returns no data.
- Plaintext above 64 MiB is refused with `ValueError`; KB-02 enforces the 50 MB upload limit at its boundary. Nonces are random 96 bits, and the GCM limit of 2^32 encryptions per key is far above any Organization's volume in the prototype (revisit with rotation).
- Destroying a key (`destroy_org_key`, tests only for now) sets `wrapped_key` to NULL: `KeyDestroyed` on every later use, so none of that Organization's files or conversations can be decrypted (AC5).
- Limits of the prototype (R8): old row versions (until VACUUM), WAL and database backups still hold the wrapped key, which the master key can unwrap until they expire. MVP-05 runs VACUUM on `organization_keys` after destruction. Real shredding of backups needs a KMS (out of scope). A deletion certificate must not promise more.

## Encrypted file store

- `OrgFileStore(root, cipher)` (`backend/src/ei_ai/storage/files.py`) with `put`, `get` and `delete`. Layout `<root>/<org_id>/<file_id>.bin`: Organization directory mode 0700, file mode 0600, each file is the plaintext plus 32 bytes. The file id is a random UUID made by the store, and paths are built only from `uuid.UUID` objects, so nothing can traverse.
- `put` encrypts, writes to a temporary file, fsyncs and renames, so no half-written file has a final name. `get` of an unknown id, or of another Organization's id, raises the same `FileNotFound` (no existence oracle). A foreign blob placed in the directory raises `DecryptionFailed`. Crypto and file I/O run in a worker thread.
- The root is a constructor argument. No service has a file-store directory or volume yet: KB-02 adds `EI_AI_FILE_STORE_DIR` and the `api` volume with the upload route.
- There is no tool that decrypts a customer file from the operator shell (R21, D6: operators do not see customer data). AC2, AC3 and AC5 are shown by the backend integration suites (`tests/integration/storage`, `tests/integration/crypto`).

## Vector namespace

- `chunk_embeddings` (migration 0009) is a table partitioned by list on `org_id` (`org_id`, `id`, `embedding vector(1024)`, `created_at`) with row-level security and the DML grants on the parent. KB-04 adds the chunk and document columns.
- Each Organization has its own partition `chunk_embeddings_<org id as 32 hex characters>` with its own `hnsw` index. The partition is owned by `ei_ai_migrator` and **no privilege is granted to `ei_ai_app`**: the application role only queries the parent. There is no DEFAULT partition, so an Organization without a partition cannot store vectors and its queries return nothing (fail closed).
- `nearest(session, tenant, query, k)` filters on the partition key with the Organization of the context, so PostgreSQL scans only that Organization's partition (AC4, checked in the test with `EXPLAIN` under a custom plan). Row-level security is the second layer.
- Who creates a partition (R2): the application role has no DDL, so the operator runs the migrator command after `org create`, with the stack up (`npm run up`). Neither `org create` nor the seed creates partitions.

```
docker compose --profile tools run --rm migrate ei-ai db vector-partition --org ORG_ID
```

- Output `vector partition created: <org_id>`, or `vector partition already present: <org_id>` on a repeat, exit 0. An unknown Organization prints `error: Organization not found`, exit 1; a missing or malformed `--org` is a usage error, exit 2. In the `api` container the command stops with `configuration error: MIGRATION_DATABASE_URL is required` (that service has no migrator credentials).
- **Lock warning:** creating or dropping a partition takes an ACCESS EXCLUSIVE lock on the `chunk_embeddings` parent. Every Organization's vector queries wait for it, briefly. Run the command at quiet times. MVP-05's drop flow inherits this.
- The command waits at most 5 seconds for that lock (`lock_timeout`), so it never queues behind a long query and blocks everyone else. If the lock is not free in time, nothing is created and it prints `db vector-partition failed (LockNotAvailable)`, exit 1: run it again later.

## Upgrading a developer machine

- A `.env` created before EA-20 has no `EI_AI_MASTER_KEY`. `npm run down`, `seed`, `ps` and `logs` then fail with `required variable EI_AI_MASTER_KEY is missing a value: run npm run up to create .env` until `npm run up`, `npm run migrate`, `npm run reset` or `npm run backend -- <task>` has run once.
- Run `npm run seed` again to give the demo Organizations their keys. Add partitions with the command above when you need vectors.

## Throughput (NFR1)

Requirement: encrypt and decrypt a 50 MB file in less than 1.5 s on the dev machine. `npm run backend -- bench-crypto` runs `OrgFileStore.put` (encrypt, write, fsync) and `get` (read, decrypt) on 50 MiB of random bytes for one Organization, with one warm-up and five timed runs each.

| Date | Machine | `put` median | `get` median | Limit |
|---|---|---|---|---|
| 2026-10-22 | AMD Ryzen 5 5600G, 14 GB RAM, Windows 11 with Docker Desktop (WSL2) | 131.8 ms | 99.6 ms | 1500 ms |

Output line: `file crypto 50 MiB: put_median_ms=131.8 get_median_ms=99.6 runs=5`. Both are far below the limit, so the requirement is met.
