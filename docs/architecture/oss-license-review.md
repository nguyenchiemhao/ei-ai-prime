# OSS libraries and licence review

- Status: Proposed
- Date: 2026-10-13
- Ticket: EA-12 (SET-02)
- Related: ADR-001 ([adr-001-tech-stack.md](adr-001-tech-stack.md))

Not legal advice. This is an engineering review of published licence terms, read from the project's licence file, the package registry or the model card on the date above (URL per row). The formal legal review before the first paying customer belongs to MVP-10 (EA-84), whose checklist already holds "OSS licence review for commercial distribution (from SET-02)".

## 1. Scope, assumptions and method

Scope: every third-party library, model, service and platform that the ADR chose, listed as an option or that the ticket names (file parsing, chunking, embedding and reranker weights, vector store, keyword search, model server, JWT, Vietnamese text, Dify/MaxKB/AnythingLLM), plus every pin of the product (`backend/pyproject.toml`, `compose.yaml` and the Dockerfiles; checked by `reviews_every_product_pin`). Our own core is not listed (D64).

Assumptions:

- Hosted edition (D1): the product is used over a network, so AGPL and SSPL obligations apply even without distributing anything.
- Self-hosted edition: customers receive container images, no source code (EA-12 proposal). Images are the same as the hosted ones (D6).
- Models are downloaded by revision and used on our servers or the customer's servers; they are not modified by us.

Licence policy:

- Allowed in shipped components: MIT, BSD-2-Clause, BSD-3-Clause, 0BSD, ISC, Apache-2.0, PostgreSQL, PSF-2.0, Zlib, MPL-2.0 (unmodified files), OFL-1.1 (fonts).
- Allowed with conditions: LGPL libraries used unmodified as separately installed packages (psycopg and the lxml wheel, with the conditions in the Conditions column); GPL and LGPL packages inside base OS images (aggregation: the image keeps its source pointers and pinned digests).
- Not allowed in shipped components: AGPL, SSPL, RSAL, BUSL, Elastic-2.0, Commons Clause, GPL code imported into our process, GPL programs when a permissive option exists, and model licences with non-commercial or field-of-use limits that we cannot flow down.

Method: licence and version read on 2026-10-13 from the PyPI JSON API and wheel `dist-info` files, the npm registry, the GitHub licence file, the Hugging Face model API (commit sha, licence tag) and the licence texts themselves for Redis, Vault, Dify, Gemma, Llama and Docker. Version rule: the PoC pin when one exists, otherwise the latest stable (non-pre-release) release on the registry on the review date; models use the Hugging Face commit sha. SET-03 re-checks a licence when it pins another major version. The Node check `docs/architecture/checks/oss-license-review.test.mjs` proves the structure of this file and its agreement with the ADR, not the correctness of a licence.

The Licence (SPDX) column gives the package licence plus the copyleft licences of libraries bundled in its binary wheel (lxml, psycopg); permissive bundled licences are listed in Conditions.

Vocabulary used in the tables:

- Verdict: `approved`, `approved with conditions`, `dev only` (allowed on developer or CI machines, not in shipped artefacts), `ideas only` (concepts may be reused, no code), `not approved` (an alternative exists), `do not use`.
- Shipped: `yes` (in the product or its images), `dev only`, `no` (not used, an option or fallback only).
- Risk: one of `Low`, `Weak copyleft`, `Aggregated OS packages`, `Strong copyleft`, `Network copyleft`, `Source-available`, `Restricted model terms`, `Custom terms`, `Commercial terms`, followed by a reason. The last six are red flags.

## 2. Library and model table

| Component | Version reviewed | Licence (SPDX) | Serves | Shipped | Risk | Verdict | Alternative | Conditions | Source |
|---|---|---|---|---|---|---|---|---|---|
| pypdf | 6.20.1 | BSD-3-Clause | File parsing: PDF text, KB-02 | yes | Low: permissive | approved | | Default PDF parser, replaces PyMuPDF | https://pypi.org/project/pypdf/6.20.1/ |
| pdfplumber | 0.11.10 | MIT | File parsing: PDF tables and layout, KB-02 | yes | Low: permissive | approved | | Optional, for tables; pulls pdfminer.six and pypdfium2 | https://pypi.org/project/pdfplumber/0.11.10/ |
| pdfminer.six | 20260107 | MIT | File parsing: PDF layout engine under pdfplumber, KB-02 | yes | Low: permissive | approved | | Transitive | https://pypi.org/project/pdfminer.six/20260107/ |
| pypdfium2 | 5.14.0 | BSD-3-Clause AND Apache-2.0 | File parsing: PDF rendering under pdfplumber, KB-02 | yes | Low: permissive, wheel bundles PDFium and third-party libraries | approved with conditions | | Wheel ships `licenses/` files for PDFium, FreeType (FTL credit line required), ICU, lcms, libjpeg-turbo, OpenJPEG, libpng, Abseil, AGG; copy them into the notices file | https://pypi.org/project/pypdfium2/5.14.0/ |
| PyMuPDF | 1.28.2 | AGPL-3.0-only OR LicenseRef-Artifex-Commercial | File parsing: PDF, KB-02 | no | Network copyleft: AGPL on our code unless a paid Artifex licence is bought | do not use | pypdf | The MuPDF engine under it is AGPL-3.0 as well | https://pypi.org/project/PyMuPDF/1.28.2/ https://github.com/ArtifexSoftware/mupdf |
| python-docx | 1.2.0 | MIT | File parsing: DOCX, KB-02 | yes | Low: permissive | approved | | Requires lxml | https://pypi.org/project/python-docx/1.2.0/ |
| lxml | 6.1.3 | BSD-3-Clause AND LGPL-2.1-only | File parsing: XML under python-docx, KB-02 | yes | Weak copyleft: binary wheel bundles libiconv (LGPL-2.1); lxml code is BSD-3-Clause | approved with conditions | | Keep the wheel's `LICENSES.txt` (zlib, iconv LGPL-2.1, libxml2, libxslt MIT) and the LGPL-2.1 text in the notices file; do not statically relink or repackage the wheel | https://pypi.org/project/lxml/6.1.3/ |
| openpyxl | 3.1.5 | MIT | File parsing: XLSX, KB-02 | yes | Low: permissive | approved | | | https://pypi.org/project/openpyxl/3.1.5/ |
| markdown-it-py | 4.2.0 | MIT | File parsing: Markdown, KB-02 | yes | Low: permissive | approved | | | https://pypi.org/project/markdown-it-py/4.2.0/ |
| charset-normalizer | 3.5.2 | MIT | File parsing: TXT encoding detection, KB-02 | yes | Low: permissive | approved | | Preferred over chardet | https://pypi.org/project/charset-normalizer/3.5.2/ |
| chardet | 7.6.0 | 0BSD | File parsing: TXT encoding detection, KB-02 | no | Low: 0BSD for the reviewed release; releases up to 5.2.0 are LGPL | approved with conditions | charset-normalizer | Not needed when charset-normalizer is used; if pinned, use 7.x or newer only | https://pypi.org/project/chardet/7.6.0/ https://pypi.org/project/chardet/5.2.0/ |
| langchain-text-splitters | 1.1.3 | MIT | Chunking helper, KB-03 | yes | Low: permissive | approved | | Optional; the chunker is our own code (D64) and this is only a helper | https://pypi.org/project/langchain-text-splitters/1.1.3/ |
| semchunk | 4.1.1 | MIT | Chunking helper, KB-03 | yes | Low: permissive | approved | | Optional; chunker is our own code (D64) | https://pypi.org/project/semchunk/4.1.1/ |
| tokenizers | 0.23.3 | Apache-2.0 | Token counting with the embedding model's tokenizer, KB-03 | yes | Low: permissive | approved | | Chunker is our own code (D64); this only counts tokens | https://pypi.org/project/tokenizers/0.23.3/ |
| Qwen3-4B-Instruct-2507 | rev cdbee75 | Apache-2.0 | LLM about 4B: default dev and CPU model, FND-07, PIPE | yes | Low: permissive weights | approved | | Official publisher repository; see section 3 | https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507 |
| Qwen3-4B-Instruct-2507-GGUF (unsloth) | rev a06e946 | Apache-2.0 | LLM about 4B: PoC GGUF file, F8, FND-07 | dev only | Low: permissive; third-party conversion | dev only | Qwen3-4B-Instruct-2507 | Conversion inherits the base licence; file sha256 verified at every model start (FND-07); the GPU production artefact is SET-04 | https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF |
| Qwen3-8B | rev b968826 | Apache-2.0 | LLM larger: GPU reference, FND-07 | yes | Low: permissive weights | approved | | | https://huggingface.co/Qwen/Qwen3-8B |
| Qwen3-14B | rev 40c0698 | Apache-2.0 | LLM larger: GPU reference, FND-07 | yes | Low: permissive weights | approved | | | https://huggingface.co/Qwen/Qwen3-14B |
| Phi-4-mini-instruct | rev cfbefac | MIT | LLM about 4B: candidate for EVL-04 | yes | Low: permissive weights | approved | | Vietnamese quality unmeasured (EVL-04) | https://huggingface.co/microsoft/Phi-4-mini-instruct |
| Gemma 3 4B (google/gemma-3-4b-it) | rev 093f9f3 | LicenseRef-Gemma | LLM about 4B: not a default | no | Restricted model terms: use policy flows down to every recipient, Google may restrict use remotely | not approved | Qwen3-4B-Instruct-2507 | Gated download; any use needs MVP-10 review first | https://ai.google.dev/gemma/terms https://huggingface.co/google/gemma-3-4b-it |
| Llama 3.2 3B (meta-llama/Llama-3.2-3B-Instruct) | rev 0cb88a4 | LicenseRef-Llama-3.2 | LLM about 4B: not a default | no | Restricted model terms: attribution, Llama-prefixed derivative names, 700M monthly-user clause, acceptable use policy | not approved | Qwen3-4B-Instruct-2507 | Gated download; any use needs MVP-10 review first | https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/LICENSE https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct |
| bge-m3 | rev 5617a9f | MIT | Embedding: default, KB-03, FND-07 | yes | Low: permissive weights | approved | | | https://huggingface.co/BAAI/bge-m3 |
| bge-reranker-v2-m3 | rev 953dc6f | Apache-2.0 | Reranker: default, KB-04, FND-07 | yes | Low: permissive weights | approved | | | https://huggingface.co/BAAI/bge-reranker-v2-m3 |
| bge-m3-Q8_0-GGUF (ggml-org) | rev 9eba04c | MIT | Embedding GGUF file pinned in the model catalog, FND-07, KB-04 | yes | Low: permissive; conversion by the llama.cpp maintainers | approved | | Conversion inherits the base licence; file and sha256 in section 3 | https://huggingface.co/ggml-org/bge-m3-Q8_0-GGUF |
| bge-reranker-v2-m3-GGUF (gpustack) | rev 3093af0 | Apache-2.0 | Reranker GGUF file pinned in the model catalog, FND-07, KB-04 | yes | Low: permissive; third-party conversion | approved | | Conversion inherits the base licence; file and sha256 in section 3 | https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF |
| Qwen3-Embedding-0.6B | rev 97b0c61 | Apache-2.0 | Embedding: alternative, FND-07 | yes | Low: permissive weights | approved | | | https://huggingface.co/Qwen/Qwen3-Embedding-0.6B |
| Qwen3-Reranker-0.6B | rev e61197e | Apache-2.0 | Reranker: alternative, FND-07 | yes | Low: permissive weights | approved | | | https://huggingface.co/Qwen/Qwen3-Reranker-0.6B |
| PostgreSQL 16 | 16 (image pgvector/pgvector:0.8.7-pg16) | PostgreSQL | Database with row-level security, F1, F3 | yes | Low: permissive | approved | | | https://www.postgresql.org/about/licence/ |
| pgvector | 0.8.7 (image pgvector/pgvector:0.8.7-pg16) | PostgreSQL | Vector store, F2, F5, KB-04 | yes | Low: permissive; GitHub reports NOASSERTION but the LICENSE text is the PostgreSQL Licence | approved | | Image base is Debian bookworm, see the base image row | https://github.com/pgvector/pgvector/blob/master/LICENSE |
| PostgreSQL full-text search and pg_trgm | 16 (contrib) | PostgreSQL | Keyword search, F5, KB-04 | yes | Low: permissive | approved | | Part of PostgreSQL | https://www.postgresql.org/about/licence/ |
| Qdrant | 1.19.2 | Apache-2.0 | Vector store fallback, ADR section 11 | no | Low: permissive | approved | | Fallback only | https://github.com/qdrant/qdrant/blob/master/LICENSE |
| OpenSearch | 3.9.0 | Apache-2.0 | Keyword search fallback, ADR section 11 | no | Low: permissive | approved | | Fallback only | https://github.com/opensearch-project/OpenSearch/blob/main/LICENSE.txt |
| ParadeDB pg_search | 0.26.1 | AGPL-3.0-only | Keyword search (BM25) | no | Network copyleft: AGPL extension | do not use | PostgreSQL full-text search and pg_trgm | | https://github.com/paradedb/paradedb/blob/dev/LICENSE |
| Elasticsearch | 9.5.5 | AGPL-3.0-only OR SSPL-1.0 OR Elastic-2.0 | Keyword search | no | Source-available: the repository is covered by AGPL, SSPL or Elastic License 2.0 | do not use | OpenSearch | | https://github.com/elastic/elasticsearch/blob/main/LICENSE.txt |
| MySQL Community Server | 26.7.0 | GPL-2.0-only | Relational database option | no | Strong copyleft: GPLv2 with additional linking permissions | not approved | PostgreSQL 16 with row-level security | Also lacks native row-level security (ADR section 3.2) | https://github.com/mysql/mysql-server/blob/trunk/LICENSE |
| MariaDB Server | 12.3.3 | GPL-2.0-only | Relational database option | no | Strong copyleft: GPLv2 server | not approved | PostgreSQL 16 with row-level security | Also lacks native row-level security (ADR section 3.2) | https://github.com/MariaDB/server/blob/main/COPYING |
| llama.cpp | b11580 (image ghcr.io/ggml-org/llama.cpp:server-b11580) | MIT | Model serving on CPU, F8, FND-07 | yes | Low: permissive | approved | | Image is built on Ubuntu 24.04, see the base image row | https://github.com/ggml-org/llama.cpp/blob/master/LICENSE https://github.com/ggml-org/llama.cpp/blob/b11580/.devops/cpu.Dockerfile |
| vLLM | 0.31.0 | Apache-2.0 | Model serving on GPU, F8, SET-04 | yes | Low: permissive | approved with conditions | | The GPU image contents (CUDA, PyTorch) are not reviewed here; SET-04 and MVP-10 check them | https://pypi.org/project/vllm/0.31.0/ |
| Ollama | 0.40.4 | MIT | Model serving option | no | Low: permissive | approved | | Licence is fine; not chosen, see ADR section 3.6 | https://github.com/ollama/ollama/blob/main/LICENSE |
| openai (Python SDK) | 3.29.0 | Apache-2.0 | Model gateway client, F8, FND-07 | yes | Low: permissive | approved | | | https://pypi.org/project/openai/3.29.0/ |
| httpx2 | 2.15.1 | BSD-3-Clause | HTTP client of the openai SDK 3.x (pydantic's httpx fork); the gateway transport builds its pools with it, FND-07 | yes | Low: permissive | approved | | Pinned in pyproject.toml because `ei_ai.model_gateway.transport` imports it; version and licence read from the installed wheel metadata (License-Expression) | https://pypi.org/project/httpx2/2.15.1/ https://github.com/pydantic/httpx2 |
| httpcore2 | 2.15.1 | BSD-3-Clause | Transitive dependency of httpx2, FND-07 | yes | Low: permissive | approved | | Not pinned in pyproject.toml; version read from the installed wheel metadata (License-Expression) | https://pypi.org/project/httpcore2/2.15.1/ |
| truststore | 0.10.5 | MIT | Transitive dependency of httpx2 (system certificate store), FND-07 | yes | Low: permissive | approved | | Not pinned in pyproject.toml; version read from the installed wheel metadata (License-Expression) | https://pypi.org/project/truststore/0.10.5/ |
| jiter | 0.17.0 | MIT | Transitive dependency of the openai SDK (JSON parser), FND-07 | yes | Low: permissive | approved | | Not pinned in pyproject.toml; version read from the installed wheel metadata (License-Expression) | https://pypi.org/project/jiter/0.17.0/ |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | Transitive dependency of the openai SDK, FND-07 | yes | Low: permissive | approved | | Not pinned in pyproject.toml; version and licence read from the installed wheel metadata (License); the MIT option is used | https://pypi.org/project/sniffio/1.3.1/ |
| FastAPI | 0.143.0 | MIT | Backend framework | yes | Low: permissive | approved | | | https://pypi.org/project/fastapi/0.143.0/ |
| Pydantic | 2.14.1 | MIT | Backend validation | yes | Low: permissive | approved | | | https://pypi.org/project/pydantic/2.14.1/ |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI server | yes | Low: permissive | approved | | | https://pypi.org/project/uvicorn/0.54.0/ |
| httpx | 0.28.1 | BSD-3-Clause | HTTP client, guarded egress, F14; today a dev dependency (FastAPI TestClient), the openai SDK 3.x uses httpx2 | yes | Low: permissive | approved | | | https://pypi.org/project/httpx/0.28.1/ |
| SQLAlchemy | 2.1.4 | MIT | Data access, FND-01 | yes | Low: permissive | approved | | | https://pypi.org/project/SQLAlchemy/2.1.4/ |
| Alembic | 1.20.0 | MIT | Migrations with RLS policies, FND-01 | yes | Low: permissive | approved | | | https://pypi.org/project/alembic/1.20.0/ |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | Transitive dependency of SQLAlchemy asyncio, FND-01 | yes | Low: permissive | approved | | Not pinned in pyproject.toml; version read from the installed wheel metadata (License-Expression) | https://pypi.org/project/greenlet/3.5.6/ |
| Mako | 1.4.3 | MIT | Transitive dependency of Alembic (migration script template), FND-01 | yes | Low: permissive | approved | | Not pinned in pyproject.toml; version read from the installed wheel metadata (License-Expression) | https://pypi.org/project/Mako/1.4.3/ |
| MarkupSafe | 3.0.4 | BSD-3-Clause | Transitive dependency of Mako, FND-01 | yes | Low: permissive | approved | | Not pinned in pyproject.toml; version read from the installed wheel metadata (License-Expression) | https://pypi.org/project/MarkupSafe/3.0.4/ |
| psycopg 3 (psycopg[binary]) | 3.3.6 | LGPL-3.0-only AND LGPL-2.1-only | PostgreSQL driver under SQLAlchemy and Procrastinate, FND-01 | yes | Weak copyleft: LGPL-3.0 library, acceptable only unmodified and replaceable | approved with conditions | asyncpg | Use unmodified from PyPI as a separately installed package; ship the LGPL-3.0 and GPL-3.0 texts and a source pointer (PyPI sdist) in the notices file; no single-file bundling of the backend; binary wheel also bundles libpq (PostgreSQL), OpenSSL 3 (Apache-2.0), libxcrypt (LGPL-2.1), Kerberos, SASL, LDAP, keyutils, selinux and pcre libraries listed in its `psycopg_binary.libs` folder; production images may use the Debian libpq5 package with `psycopg[c]` instead | https://pypi.org/project/psycopg/3.3.6/ https://raw.githubusercontent.com/psycopg/psycopg/master/LICENSE.txt |
| asyncpg | 0.32.0 | Apache-2.0 | Alternative PostgreSQL driver | no | Low: permissive | approved | | Switching would also mean replacing Procrastinate, which requires psycopg | https://pypi.org/project/asyncpg/0.32.0/ |
| Procrastinate | 3.10.0 | MIT | Background jobs on PostgreSQL, ingestion | yes | Low: permissive; depends on psycopg | approved with conditions | | Same LGPL conditions as psycopg | https://pypi.org/project/procrastinate/3.10.0/ |
| redis-py | 8.1.0 | MIT | Valkey client, rate limits | yes | Low: permissive; client library only, not the Redis server | approved | | Talks to Valkey (protocol-compatible) | https://pypi.org/project/redis/8.1.0/ |
| Valkey | 8.1.10 (image valkey/valkey:8.1.10-alpine) | BSD-3-Clause | Rate-limit store, F3 | yes | Low: permissive | approved | | Image base is Alpine, see the base image row | https://github.com/valkey-io/valkey/blob/unstable/COPYING |
| Redis server | 8.x; 7.4 and newer | LicenseRef-RSALv2 OR SSPL-1.0 OR AGPL-3.0-only | Rate-limit store option | no | Source-available: RSALv2 or SSPLv1 from 7.4, AGPLv3 added in 8.0; 7.2 and older are BSD-3-Clause | do not use | Valkey | | https://redis.io/legal/licenses/ https://github.com/redis/redis/blob/unstable/LICENSE.txt |
| MinIO | RELEASE.2025-10-15T17-29-55Z | AGPL-3.0-only | Object storage option | no | Network copyleft: AGPL server | do not use | own filesystem storage behind a storage interface (ADR section 3.5) | | https://github.com/minio/minio/blob/master/LICENSE |
| SeaweedFS | 4.48 | Apache-2.0 | Object storage fallback | no | Low: permissive | approved | | Fallback only | https://github.com/seaweedfs/seaweedfs/blob/master/LICENSE |
| HashiCorp Vault | 2.1.2; 1.15.0 and newer | BUSL-1.1 | Key management option | no | Source-available: Business Source License bars competing hosted or embedded offerings | do not use | OpenBao | | https://github.com/hashicorp/vault/blob/main/LICENSE |
| OpenBao | 2.7.1 | MPL-2.0 | Key management, later (FND-03) | no | Low: file-level copyleft, unmodified use | approved | | Not chosen yet; licence file of the release is kept if shipped | https://github.com/openbao/openbao/blob/main/LICENSE |
| Base image python:3.12.15-slim-bookworm | python:3.12.15-slim-bookworm (Debian 12) | GPL-2.0-or-later AND LGPL-2.1-or-later AND PSF-2.0 | API and worker image base | yes | Aggregated OS packages: Debian packages with GPL and LGPL licences, plus Python PSF-2.0 | approved with conditions | | Pin the image digest; keep package source pointers; checked in MVP-10 | https://hub.docker.com/_/python https://docs.python.org/3/license.html |
| Base image node:22.23.3-bookworm-slim | node:22.23.3-bookworm-slim (Debian 12) | MIT AND GPL-2.0-or-later AND LGPL-2.1-or-later | Build stage of the admin and widget images (compiles the apps; nothing from it is shipped) | no | Aggregated OS packages: Debian packages with GPL and LGPL licences, used while building only | dev only | | | https://hub.docker.com/_/node https://github.com/nodejs/node/blob/main/LICENSE |
| Image nginxinc/nginx-unprivileged:1.30.5-alpine3.24 | nginx 1.30.5 on Alpine 3.24 (image nginxinc/nginx-unprivileged:1.30.5-alpine3.24) | BSD-2-Clause AND GPL-2.0-only AND MIT | Serves the compiled admin UI and widget as static files (non-root, port 8080) | yes | Aggregated OS packages: Alpine packages include GPL licensed tools | approved with conditions | | Pin the image digest; keep package source pointers; checked in MVP-10 | https://hub.docker.com/r/nginxinc/nginx-unprivileged https://nginx.org/LICENSE |
| Base image postgres:16 on Debian bookworm | postgres:16-bookworm (under pgvector/pgvector:0.8.7-pg16) | GPL-2.0-or-later AND LGPL-2.1-or-later AND PostgreSQL | Database image base | yes | Aggregated OS packages: Debian packages with GPL and LGPL licences | approved with conditions | | Pin the image digest; keep package source pointers; checked in MVP-10 | https://github.com/pgvector/pgvector/blob/v0.8.7/Dockerfile |
| Base image alpine | alpine:3.24 (under valkey/valkey:8.1.10-alpine) | GPL-2.0-only AND MIT | Valkey image base | yes | Aggregated OS packages: Alpine packages include GPL licensed tools | approved with conditions | | Pin the image digest; keep package source pointers; checked in MVP-10 | https://github.com/valkey-io/valkey-container/blob/mainline/8.1/alpine/Dockerfile |
| Base image ubuntu:24.04 | ubuntu:24.04 (under ghcr.io/ggml-org/llama.cpp:server-b11580) | GPL-2.0-or-later AND LGPL-2.1-or-later | llama.cpp image base | yes | Aggregated OS packages: Ubuntu packages with GPL and LGPL licences | approved with conditions | | Pin the image digest; keep package source pointers; checked in MVP-10 | https://github.com/ggml-org/llama.cpp/blob/b11580/.devops/cpu.Dockerfile |
| PyJWT | 2.15.1 | MIT | Channel tokens (HS256), F4, WGT-01 | yes | Low: permissive | approved | | | https://pypi.org/project/PyJWT/2.15.1/ |
| argon2-cffi | 25.1.0 | MIT | Admin password hashing, FND-05 | yes | Low: permissive | approved | | | https://pypi.org/project/argon2-cffi/25.1.0/ |
| AnyIO | 4.15.1 | MIT | Worker threads and the capacity limiter for password hashing, FND-05 (already a FastAPI dependency, pinned since imported directly) | yes | Low: permissive | approved | | | https://pypi.org/project/anyio/4.15.1/ |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | Envelope encryption, F2, FND-03 | yes | Low: permissive | approved | | | https://pypi.org/project/cryptography/50.0.2/ |
| Smokescreen | 0.1.0 | MIT | Egress proxy, F14, FND-10 | yes | Low: permissive | approved | | | https://github.com/stripe/smokescreen/blob/master/LICENSE.txt |
| Squid | 7.7 | GPL-2.0-only | Egress proxy option | no | Strong copyleft: GPL program, large surface | not approved | Smokescreen | | https://github.com/squid-cache/squid/blob/master/COPYING |
| DOMPurify | 3.4.17 | MPL-2.0 OR Apache-2.0 | Widget output sanitising, F6, WGT-05 | yes | Low: permissive choice of licence | approved | | Use under Apache-2.0 | https://registry.npmjs.org/dompurify/3.4.17 |
| structlog | 26.1.0 | MIT OR Apache-2.0 | Masked logging, F13, FND-08 | yes | Low: permissive | approved | | | https://pypi.org/project/structlog/26.1.0/ |
| OpenTelemetry Python SDK | 1.45.1 | Apache-2.0 | Spans, F10 | yes | Low: permissive | approved | | | https://pypi.org/project/opentelemetry-sdk/1.45.1/ |
| underthesea | 9.5.0 | Apache-2.0 | Vietnamese word segmentation candidate, F9, KB-04, D60 | dev only | Restricted model terms: bundled CRF models trained on VLSP 2013 data whose terms are unstated (a secondary source says research or educational use); the code is Apache-2.0 | dev only | own normalisation without word segmentation (D60) | Releases up to 9.2.x are GPL-3.0, so pin 9.3.0 or newer only; the wheel bundles CRF models trained on VLSP 2013 data (path `ws_crf_vlsp2013_20230727`) whose terms the package does not state and a secondary source calls research or educational; measure in KB-04 and EVL, ship only after MVP-10 confirms the data terms or the model is retrained. No Vietnamese word segmenter is approved for shipping yet: KB-04 and EVL decide between confirmed data terms, retraining or no segmentation, and MVP-10 signs off | https://pypi.org/project/underthesea/9.5.0/ https://pypi.org/project/underthesea/8.0.0/ https://arxiv.org/pdf/2006.07804 |
| pyvi | 0.1.1 | MIT | Vietnamese word segmentation candidate, F9, KB-04, D60 | dev only | Restricted model terms: bundled CRF models trained on a dataset the package does not name, terms unknown; the code is MIT | dev only | own normalisation without word segmentation (D60) | The wheel bundles CRF models (`pyvi.pkl`) trained on a dataset the package does not name; same rule as underthesea; models are pickle files, load only the ones inside the pinned wheel; no Vietnamese word segmenter is approved for shipping yet (see underthesea) | https://pypi.org/project/pyvi/0.1.1/ |
| Unidecode | 1.4.0 | GPL-2.0-or-later | Accent stripping, F9, FND-11 | no | Strong copyleft: GPL code would be imported into our process | do not use | anyascii | Or our own accent-stripping table (D60) | https://pypi.org/project/Unidecode/1.4.0/ |
| anyascii | 0.3.3 | ISC | Accent stripping option, F9, FND-11 | no | Low: permissive | approved | | Optional; D60 prefers our own Vietnamese table | https://pypi.org/project/anyascii/0.3.3/ |
| Python unicodedata (standard library) | Python 3.12 | PSF-2.0 | NFC normalisation and our own accent-stripping table, F9, FND-11 | yes | Low: permissive | approved | | | https://docs.python.org/3/license.html |
| React | 19.3.0 | MIT | Admin app, DSN-01 | yes | Low: permissive | approved | | | https://registry.npmjs.org/react/19.3.0 |
| Preact | 11.0.1 | MIT | Widget, DSN-01, WGT-02 | yes | Low: permissive | approved | | | https://registry.npmjs.org/preact/11.0.1 |
| Vite | 8.3.4 | MIT | Frontend build | yes | Low: permissive | approved | | | https://registry.npmjs.org/vite/8.3.4 |
| Radix UI primitives (@radix-ui/react-dialog) | 1.3.1 | MIT | Admin accessible components, DSN-01 | yes | Low: permissive | approved | | One package per primitive; same MIT licence | https://registry.npmjs.org/@radix-ui%2Freact-dialog/1.3.1 |
| TanStack Query | 5.104.2 | MIT | Admin data fetching | yes | Low: permissive | approved | | | https://registry.npmjs.org/@tanstack%2Freact-query/5.104.2 |
| i18next | 26.4.4 | MIT | i18n core, VI and EN | yes | Low: permissive | approved | | | https://registry.npmjs.org/i18next/26.4.4 |
| react-i18next | 17.0.16 | MIT | Admin i18n, VI and EN | yes | Low: permissive | approved | | | https://registry.npmjs.org/react-i18next/17.0.16 |
| IBM Plex Sans (@fontsource/ibm-plex-sans) | 5.3.0 | OFL-1.1 | Admin and widget font, DSN-01 | yes | Low: permissive font licence | approved with conditions | | Ship the OFL text and copyright line with the font files; do not sell the fonts on their own; Reserved Font Name "Plex" applies to modified versions | https://registry.npmjs.org/@fontsource%2Fibm-plex-sans/5.3.0 https://github.com/IBM/plex/blob/master/LICENSE.txt |
| IBM Plex Mono (@fontsource/ibm-plex-mono) | 5.3.0 | OFL-1.1 | Admin and widget code font, DSN-01 | yes | Low: permissive font licence | approved with conditions | | Same conditions as IBM Plex Sans | https://registry.npmjs.org/@fontsource%2Fibm-plex-mono/5.3.0 https://github.com/IBM/plex/blob/master/LICENSE.txt |
| TypeScript | 5.9.3 | Apache-2.0 | Frontend type checking | dev only | Low: permissive | dev only | | Compiler output is not covered by the licence | https://registry.npmjs.org/typescript/5.9.3 |
| Vitest | 5.0.4 | MIT | Frontend unit tests | dev only | Low: permissive | dev only | | | https://registry.npmjs.org/vitest/5.0.4 |
| Playwright (@playwright/test) | 1.64.0 | Apache-2.0 | End-to-end tests | dev only | Low: permissive | dev only | | | https://registry.npmjs.org/@playwright%2Ftest/1.64.0 |
| pytest | 9.1.1 | MIT | Backend tests | dev only | Low: permissive | dev only | | | https://pypi.org/project/pytest/9.1.1/ |
| pytest-cov | 7.1.0 | MIT | Backend test coverage (70 % gate in CI) | dev only | Low: permissive | dev only | | | https://pypi.org/project/pytest-cov/7.1.0/ |
| pytest-asyncio | 1.4.0 | Apache-2.0 | Async backend tests | dev only | Low: permissive | dev only | | | https://pypi.org/project/pytest-asyncio/1.4.0/ |
| ruff | 0.17.0 | MIT | Lint and format | dev only | Low: permissive | dev only | | | https://pypi.org/project/ruff/0.17.0/ |
| mypy | 2.4.0 | MIT | Type check | dev only | Low: permissive | dev only | | | https://pypi.org/project/mypy/2.4.0/ |
| Docker Engine | 29.9.0 (docker/cli v29.9.0, moby/moby tag docker-v29.9.0) | Apache-2.0 | Container runtime on dev machines and servers | dev only | Low: permissive | dev only | | We ship images and compose files, not the engine | https://github.com/moby/moby/blob/master/LICENSE https://github.com/docker/cli/blob/master/LICENSE |
| Docker Compose | 5.6.0 | Apache-2.0 | Local environment and self-hosted install files, SET-03 | no | Low: permissive | approved | | We ship compose files, not the Compose binary | https://github.com/docker/compose/blob/main/LICENSE |
| Docker Desktop | current (2026-10-13) | LicenseRef-Docker-Desktop | Developer machine on Windows | dev only | Commercial terms: paid subscription for companies with 250 or more employees or US$10M or more revenue, and for government entities | dev only | Docker Engine | Never part of a shipped image; the owner checks the company size against the terms | https://www.docker.com/pricing/faq/ |
| Dify | 1.17.1 | LicenseRef-Dify | Platform comparison only | no | Custom terms: modified Apache-2.0; no multi-tenant service without a licence, no removal of logo or copyright in the frontend | do not use | | Concepts only (section 5); we are multi-tenant by design | https://github.com/langgenius/dify/blob/main/LICENSE |
| MaxKB | 2.10.6 | GPL-3.0-only | Platform comparison only | no | Strong copyleft: GPL-3.0 application | do not use | | Concepts only (section 5) | https://github.com/1Panel-dev/MaxKB/blob/v2/LICENSE |
| AnythingLLM | 1.17.0 | MIT | Platform comparison only | no | Low: permissive | ideas only | | Ideas only by D64 (own core); no code copied | https://github.com/Mintplex-Labs/anything-llm/blob/master/LICENSE |

## 3. Model weights

| Model | Role | Revision | Licence (SPDX) | Commercial use | Self-hosted use | Conditions | Verdict | Source |
|---|---|---|---|---|---|---|---|---|
| Qwen3-4B-Instruct-2507 | LLM ~4B | cdbee75f17c01a7cc42f958dc650907174af0554 | Apache-2.0 | yes | yes | Keep the licence file with the weights | approved | https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507 |
| Qwen3-4B-Instruct-2507-GGUF (unsloth) | LLM ~4B | a06e946bb6b655725eafa393f4a9745d460374c9 | Apache-2.0 | yes | yes | Local dev model; file `Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, sha256 `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597`, verified at every model start (FND-07); third-party conversion inherits the base licence | dev only | https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF |
| Qwen3-8B | LLM larger | b968826d9c46dd6066d109eabc6255188de91218 | Apache-2.0 | yes | yes | Keep the licence file with the weights | approved | https://huggingface.co/Qwen/Qwen3-8B |
| Qwen3-14B | LLM larger | 40c069824f4251a91eefaf281ebe4c544efd3e18 | Apache-2.0 | yes | yes | Keep the licence file with the weights | approved | https://huggingface.co/Qwen/Qwen3-14B |
| Phi-4-mini-instruct | LLM ~4B | cfbefacb99257ffa30c83adab238a50856ac3083 | MIT | yes | yes | Vietnamese quality unmeasured (EVL-04) | approved | https://huggingface.co/microsoft/Phi-4-mini-instruct |
| Gemma 3 4B (google/gemma-3-4b-it) | LLM ~4B | 093f9f388b31de276ce2de164bdc2081324b9767 | LicenseRef-Gemma | restricted | restricted | Gemma Terms of Use (last modified 2026-04-01): Prohibited Use Policy must be written into any agreement covering the model or derivatives, recipients get a copy of the terms, Google may restrict use remotely, gated download | not approved | https://ai.google.dev/gemma/terms |
| Llama 3.2 3B (meta-llama/Llama-3.2-3B-Instruct) | LLM ~4B | 0cb88a4f764b7a12671c53f0838cd831a0843b95 | LicenseRef-Llama-3.2 | restricted | restricted | Copy of the agreement and "Built with Llama" with every distribution, derived model names start with "Llama", licence request above 700M monthly users, acceptable use policy applies, gated download | not approved | https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/LICENSE |
| bge-m3 | Embedding | 5617a9f61b028005a4858fdac845db406aefb181 | MIT | yes | yes | Base model of the GGUF row below | approved | https://huggingface.co/BAAI/bge-m3 |
| bge-m3-Q8_0-GGUF (ggml-org) | Embedding | 9eba04c5d75ba5a1595e45de734d36bef4e5cb98 | MIT | yes | yes | FND-07 pin: file `bge-m3-q8_0.gguf`, 634,553,760 bytes, sha256 `aa473d51f451a22f0fcf39ba3330c14bed38a385712b1113440f69df4047a173` (Hugging Face LFS metadata); conversion by the llama.cpp maintainers inherits the base licence; served from KB-04 | approved | https://huggingface.co/ggml-org/bge-m3-Q8_0-GGUF |
| bge-reranker-v2-m3 | Reranker | 953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e | Apache-2.0 | yes | yes | Base model of the GGUF row below | approved | https://huggingface.co/BAAI/bge-reranker-v2-m3 |
| bge-reranker-v2-m3-GGUF (gpustack) | Reranker | 3093af03b1a635e67b084b1d8c03c5f5e020fd05 | Apache-2.0 | yes | yes | FND-07 pin: file `bge-reranker-v2-m3-Q8_0.gguf`, 635,676,416 bytes, sha256 `a43c7c9b11a4c1517e5bf95151960e1621d1b72f7a493364b01e386cf1aaa1d3` (Hugging Face LFS metadata); neither BAAI nor ggml-org publishes a GGUF, gpustack is the most used conversion; it inherits the base licence; served from KB-04 | approved | https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF |
| Qwen3-Embedding-0.6B | Embedding | 97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3 | Apache-2.0 | yes | yes | Alternative to bge-m3 | approved | https://huggingface.co/Qwen/Qwen3-Embedding-0.6B |
| Qwen3-Reranker-0.6B | Reranker | e61197ed45024b0ed8a2d74b80b4d909f1255473 | Apache-2.0 | yes | yes | Alternative to bge-reranker-v2-m3 | approved | https://huggingface.co/Qwen/Qwen3-Reranker-0.6B |

Weights are pinned by revision and by file sha256 in the model catalog (FND-07); the licence is re-checked whenever a revision changes. The Hugging Face licence tag is the model publisher's statement; where a third party converts weights (GGUF), the base model's licence applies and FND-07 records both repositories.

## 4. Red flags

- PyMuPDF: AGPL-3.0 or paid Artifex licence. AGPL would reach our code in both editions. Decision: do not use; pypdf is the PDF parser.
- MinIO: AGPL-3.0. Decision: do not use; filesystem storage behind an interface (SeaweedFS is the Apache-2.0 fallback).
- ParadeDB pg_search: AGPL-3.0 extension. Decision: do not use; PostgreSQL full-text search and pg_trgm, OpenSearch as fallback.
- Elasticsearch: AGPL-3.0, SSPL or Elastic License 2.0. Decision: do not use; OpenSearch (Apache-2.0).
- Redis 7.4 and newer: RSALv2 or SSPLv1, AGPLv3 added in 8.0 (7.2 and older are BSD-3-Clause). Decision: do not use; Valkey 8 (BSD-3-Clause). The redis-py client stays (MIT).
- HashiCorp Vault 1.15 and newer: Business Source License with a competing-offering restriction. Decision: do not use; OpenBao (MPL-2.0) or a cloud KMS later.
- Unidecode: GPL-2.0 or later, imported into our process. Decision: do not use; our own accent-stripping table or anyascii (ISC).
- Squid: GPL-2.0 proxy. Decision: not approved; Smokescreen (MIT).
- MySQL Community Server and MariaDB Server: GPL-2.0 servers without native row-level security. Decision: not approved; PostgreSQL.
- Gemma 3: Gemma Terms of Use flow down a use policy to every recipient and let Google restrict use remotely. Decision: not approved; Qwen3-4B-Instruct-2507. Any later use needs MVP-10 review.
- Llama 3.2: attribution, Llama-prefixed derivative names, 700M monthly-user clause. Decision: not approved; Qwen3-4B-Instruct-2507. Any later use needs MVP-10 review.
- Dify: modified Apache-2.0 that forbids operating a multi-tenant service without a licence and removing the logo. Decision: do not use code.
- MaxKB: GPL-3.0. Decision: do not use code.
- Docker Desktop: paid subscription above 250 employees or US$10M revenue. Decision: dev only, never in an image; Docker Engine is the alternative.
- psycopg 3: LGPL-3.0-only (weak copyleft). Decision: approved with conditions, see section 2 (Conditions column) and section 6; asyncpg is the alternative driver.
- lxml wheel: bundles libiconv (LGPL-2.1). Decision: approved with conditions, same notices rule as psycopg.
- underthesea and pyvi: code licences are permissive, but the bundled models come from training data whose terms are not stated (VLSP 2013 for underthesea). Decision: dev only until confirmed; neither is an approved shipping alternative to the other, and no Vietnamese word segmenter is approved for shipping yet (KB-04 and EVL decide, MVP-10 signs off).

## 5. Ideas from existing platforms

Rule: concepts only, no code copied (D64, P2). Dify and MaxKB must not be used as code sources at all.

- Dify (modified Apache-2.0, multi-tenant and logo conditions): separation of workspace and app, an embed snippet per app, a model-provider abstraction, run logs with step traces.
- MaxKB (GPL-3.0): knowledge-base document status list with re-index action, citation display under an answer, a question-and-answer pair store that is matched before the model (compare our Answer Scripts).
- AnythingLLM (MIT): workspace-scoped document pinning, a simple embeddable chat widget, per-workspace model selection. MIT would allow code reuse, but D64 says our own core, so the verdict is `ideas only`.

## 6. Obligations when shipping

Handed to SET-03 (tooling) and MVP-10 (legal sign-off):

- Generate a third-party notices file in CI (one licence scanner per ecosystem; the tool is SET-03's choice) and ship it with every image and with the admin app.
- Include Apache-2.0 NOTICE files where a package has one.
- psycopg and the lxml wheel: ship the LGPL-3.0 and LGPL-2.1 texts and a source pointer (exact PyPI sdist), and keep both installed as unmodified packages.
- pypdfium2: ship the PDFium, FreeType (credit line) and other bundled-library licence files from the wheel.
- Fonts: ship the OFL-1.1 text and the IBM copyright line next to the font files.
- Base images: pin image digests, keep a pointer to the distro source packages, list the OS packages in the notices (MVP-10 checks the GPL and LGPL obligations of the images).
- Models: ship or link the model licence file; if Llama or Gemma were ever approved, add their attribution and use-policy flow-down.
- Before any new dependency is used, add a row to section 2 with its licence and a Source; a licence change upstream (as for Redis, Elasticsearch and Vault) triggers a re-check.

## 7. Approved list for M0–M5

Components with verdict `approved` or `approved with conditions` (conditions in section 2):

- File parsing: pypdf, pdfplumber (with pdfminer.six and pypdfium2), python-docx (with lxml), openpyxl, markdown-it-py, charset-normalizer.
- Chunking helpers (optional, the chunker is our own): langchain-text-splitters, semchunk, tokenizers.
- Models: Qwen3-4B-Instruct-2507, Qwen3-8B, Qwen3-14B, Phi-4-mini-instruct, bge-m3, bge-reranker-v2-m3, Qwen3-Embedding-0.6B, Qwen3-Reranker-0.6B.
- Data: PostgreSQL 16, pgvector, PostgreSQL full-text search and pg_trgm, psycopg 3 (conditions), SQLAlchemy, Alembic, Procrastinate, Valkey with redis-py. Fallbacks: Qdrant, OpenSearch, SeaweedFS, asyncpg.
- Model serving: llama.cpp, vLLM (GPU image to be checked), openai SDK; Ollama is licence-clean but not chosen.
- Backend: FastAPI, Pydantic, uvicorn, httpx, PyJWT, argon2-cffi, cryptography, structlog, OpenTelemetry, Python unicodedata; OpenBao and anyascii if needed.
- Egress: Smokescreen.
- Frontend: React, Preact, Vite, Radix UI primitives, TanStack Query, i18next, react-i18next, DOMPurify, IBM Plex Sans and Mono.
- Dev and CI only: TypeScript, Vitest, Playwright, pytest, pytest-cov, pytest-asyncio, ruff, mypy, Docker Engine, Docker Desktop (licence terms apply), underthesea and pyvi (evaluation only); Docker Compose files are shipped, the Compose binary is not.
- Base images: python:3.12.15-slim-bookworm, nginxinc/nginx-unprivileged on Alpine (serves the admin UI and widget), postgres on Debian bookworm, alpine, ubuntu:24.04 (aggregation conditions); node:22.23.3-bookworm-slim is used in build stages only and is not shipped.

## 8. Open items and hand-offs

- MVP-10 (EA-84): formal legal sign-off; psycopg and lxml LGPL conditions (separate package, notices, source pointer); base image source obligations; Gemma or Llama only if ever wanted.
- psycopg decision (assumption, the owner may overrule): keep psycopg with the conditions in section 2; the alternative is asyncpg plus replacing Procrastinate.
- FND-07 (EA-24): done. Embedding `ggml-org/bge-m3-Q8_0-GGUF` and reranker `gpustack/bge-reranker-v2-m3-GGUF` are pinned by revision and file sha256 in section 3 and in the platform model manifest (`backend/src/ei_ai/model_gateway/data/local-models.json`); both conversions keep the base licence (MIT, Apache-2.0). The openai SDK 3.29 brings httpx2, httpcore2, truststore, jiter and sniffio (section 2).
- KB-04 and EVL: no Vietnamese word segmenter is approved for shipping yet. Measure underthesea against pyvi and against our own rules (D60); before either ships, confirm the terms of the training data of its bundled model (VLSP 2013 for underthesea) or retrain. Only underthesea 9.3.0 and newer are Apache-2.0.
- SET-03 (EA-13): notices file and licence scan in CI; re-check licences when it pins a major version that differs from section 2.
- SET-04: GPU image contents (CUDA, PyTorch) for vLLM are not reviewed here.
- Revisit triggers: a licence change upstream, a new major version of a reviewed component, a new dependency.

## 9. Sources

All checked on 2026-10-13.

- PyPI project pages and JSON API (licence expression, classifiers, wheel `dist-info` files for psycopg-binary, pypdfium2, lxml, underthesea, pyvi, Unidecode): https://pypi.org/ (one URL per row in section 2).
- npm registry (licence field): https://registry.npmjs.org/<package>/<version> (URL per row).
- GitHub licence files (URL per row): Redis https://github.com/redis/redis/blob/unstable/LICENSE.txt, Vault https://github.com/hashicorp/vault/blob/main/LICENSE, Elasticsearch https://github.com/elastic/elasticsearch/blob/main/LICENSE.txt, Dify https://github.com/langgenius/dify/blob/main/LICENSE, MySQL https://github.com/mysql/mysql-server/blob/trunk/LICENSE.
- Hugging Face model API and cards (commit sha and licence tag): https://huggingface.co/api/models/<id>.
- Licence texts: Redis https://redis.io/legal/licenses/, Gemma https://ai.google.dev/gemma/terms, Llama 3.2 https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/LICENSE, Docker Desktop https://www.docker.com/pricing/faq/, PostgreSQL https://www.postgresql.org/about/licence/, Python https://docs.python.org/3/license.html, OFL https://github.com/IBM/plex/blob/master/LICENSE.txt.
- Image bases: https://hub.docker.com/_/python, https://github.com/pgvector/pgvector/blob/v0.8.7/Dockerfile, https://github.com/valkey-io/valkey-container/blob/mainline/8.1/alpine/Dockerfile, https://github.com/ggml-org/llama.cpp/blob/b11580/.devops/cpu.Dockerfile.
- VLSP 2013 corpus terms (secondary statement only): https://arxiv.org/pdf/2006.07804.
