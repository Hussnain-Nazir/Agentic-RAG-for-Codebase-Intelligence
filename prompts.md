# AI Development Log

### 2026-09-17 - Phase 0 scaffold

**Prompt:**

> Read PRISM_SPEC.md sections 6 (Technology Stack), 24 (Backend Architecture),
> 27 (Frontend Architecture & UX), and 31 (Deployment & Local Development)
> before starting.
>
> This is Phase 0 of Prism. The repository is currently empty except for
> .gitignore. Implement the following and nothing more:
>
> 1. Backend scaffold at backend/:
>
>    - FastAPI app factory in backend/app/main.py.
>    - backend/app/config.py using pydantic-settings, loading every
>      environment variable listed in PRISM_SPEC.md section 31.2, with no
>      hard-coded default provider names, base URLs, or API keys.
>    - A GET /health endpoint returning {"status": "ok"}.
>    - backend/requirements.txt (or pyproject.toml, your choice, but be
>      consistent) including fastapi, uvicorn, pydantic, pydantic-settings,
>      sqlalchemy, alembic, pytest, httpx (for test client).
>    - backend/tests/test_health.py verifying GET /health returns 200.
>
> 2. Frontend scaffold at frontend/:
>
>    - Vite + React + TypeScript project.
>    - A single placeholder page rendering "Prism" and a short description.
>    - Vitest configured with one trivial passing test.
>
> 3. docker-compose.yml at the repository root with three services:
>    postgres (use the official pgvector/pgvector image), backend, frontend.
>    Postgres has a named volume for data persistence. Backend depends on
>    postgres. Do not add Redis, Celery, Kafka, or any other infrastructure.
>
> 4. .env.example at the repository root containing every variable from
>    PRISM_SPEC.md section 31.2, with placeholder values only (no real
>    secrets, no real URLs to third-party services).
>
> 5. Root README.md: project name and one-paragraph description matching
>    PRISM_SPEC.md section 1, local setup instructions (this will be extended
>    in later phases), and a final line reading exactly:
>    Status: Phase 0 complete
>
> 6. prompts.md at the repository root, created with the entry format from
>    PRISM_SPEC.md section 32.2, and one entry for this phase recording the
>    phase, the task, and the prompt used (this exact prompt). Do not invent
>    any "accepted/rejected" commentary - just record what was produced and
>    the test result you observed.
>
> Out of scope for this phase - do not implement any of the following yet:
> database models, authentication, GitHub integration, ZIP upload, parsing,
> retrieval, the agent, memory, tools, or any UI beyond the placeholder page.
>
> Acceptance conditions:
>
> - `docker compose config` validates without error.
> - Backend test suite passes.
> - Frontend test suite passes.
> - README.md ends with "Status: Phase 0 complete".
> - prompts.md contains exactly one new entry for this phase.
>
> Report the exact commands you used to verify each acceptance condition.

**AI tool:** Codex

**Summary of generated output:** Created the Phase 0 FastAPI, React, Vite, TypeScript, Docker Compose, environment example, README, and test scaffolds.

**Resulting module/commit:** `backend/`, `frontend/`, `docker-compose.yml`, `.env.example`, `README.md`, and `prompts.md`.

**Test result:** Backend pytest passed 1 test. Frontend Vitest passed 1 test. The frontend production build passed. After Docker became available, `docker compose config` passed and the backend, frontend, and PostgreSQL services started successfully. The backend health endpoint and frontend returned HTTP 200.

### 2026-09-17 - Phase 1 authentication foundation

**Prompt:**

> Read PRISM_SPEC.md sections 25 (Database Design, users table) and 26 (REST
> API, AUTH endpoints) before starting. Inspect backend/app/config.py and
> backend/app/main.py from Phase 0.
>
> This is Phase 1 of Prism. Implement:
>
> 1. Alembic setup in backend/alembic/, configured to read DATABASE_URL from
>    the existing settings object. Create the baseline migration containing
>    only the users table as specified in PRISM_SPEC.md section 25:
>    id (UUID PK), email (unique), hashed_password, created_at.
>
> 2. backend/app/models/user.py - SQLAlchemy ORM model matching the table.
>
> 3. backend/app/auth/ - password hashing (use passlib or bcrypt directly),
>    JWT creation/verification using JWT_SECRET from settings, and a FastAPI
>    dependency get_current_user that extracts and validates the bearer token,
>    raising 401 on missing/invalid/expired tokens.
>
> 4. backend/app/schemas/auth.py - Pydantic request/response schemas for
>    register and login.
>
> 5. backend/app/api/routes/auth.py:
>
>    - POST /auth/register -> {user_id}, 409 if email already exists.
>    - POST /auth/login -> {access_token}, 401 on invalid credentials.
>      Wire this router into the app in main.py.
>
> 6. Tests in backend/tests/test_auth.py covering: successful registration,
>    duplicate email rejection, successful login, invalid password rejection,
>    and that a protected test route using get_current_user rejects requests
>    with no token and accepts requests with a valid token.
>
> 7. Update backend startup (entrypoint or docker-compose command) so
>    migrations run automatically before the app starts in the Docker Compose
>    environment (wait for postgres to be ready, then `alembic upgrade head`,
>    then start uvicorn).
>
> 8. Append a prompts.md entry for this phase. Update README.md status line to
>    "Status: Phase 1 complete" only after all tests pass.
>
> Out of scope: repository models, GitHub integration, any endpoint other than
> register/login, any frontend auth UI (that comes in a later frontend phase).
>
> Acceptance conditions:
>
> - `alembic upgrade head` runs cleanly against a fresh database.
> - All Phase 0 tests still pass.
> - All new auth tests pass.
> - No plaintext passwords are ever logged or stored.

**AI tool:** Codex

**Summary of generated output:** Added the users ORM model and baseline migration, async database session setup, bcrypt password hashing, JWT authentication, register and login routes, bearer-token dependency, Docker migration startup, and authentication tests.

**Resulting module/commit:** `backend/alembic/`, `backend/app/db/`, `backend/app/models/user.py`, `backend/app/auth/`, `backend/app/schemas/auth.py`, `backend/app/api/routes/auth.py`, `backend/tests/test_auth.py`, and backend startup configuration.

**Test result:** Backend pytest passed all 7 tests, including the Phase 0 health test and 6 Phase 1 authentication tests. The baseline Alembic migration upgraded a fresh PostgreSQL container to revision 0001 successfully, and the live `users` table matched the required schema.

### 2026-09-17 - Phase 2 repository source foundation

**Prompt:**

> Read PRISM_SPEC.md sections 8 (Repository Sources & ZIP Upload, especially
> the RepositorySource interface), 9 (Ingestion & Synchronization, especially
> the indexing states), and 25 (Database Design tables: repositories,
> repository_indexes, repository_files, github_installations) before starting.
> Inspect backend/app/models/user.py and backend/app/auth/ from Phase 1.
>
> This is Phase 2 of Prism. Implement:
>
> 1. SQLAlchemy models in backend/app/models/: Repository, RepositoryIndex,
>    RepositoryFile, GitHubInstallation, matching PRISM_SPEC.md section 25
>    exactly (fields, keys, indexes, cascade behavior). RepositoryIndex.state
>    must use the enum from section 9.2 (PENDING, DISCOVERING, PARSING,
>    EMBEDDING, INDEXING, READY, FAILED, PARTIAL).
>
> 2. backend/app/sources/base.py defining the RepositorySource protocol from
>    PRISM_SPEC.md section 8.1 (list_files, get_file_content, get_revision),
>    plus a SourceFileRef data class.
>
> 3. backend/app/sources/github.py and backend/app/sources/upload.py with
>    GitHubRepositorySource and UploadedRepositorySource classes implementing
>    the protocol's method signatures but raising NotImplementedError in each
>    body - these are intentionally unimplemented stubs for this phase.
>
> 4. backend/app/api/deps.py: a get_repository_or_404 dependency that loads a
>    Repository by id and raises 404 if not found or 403 if
>    repository.owner_id != current_user.id. This will be reused by every
>    future repository-scoped route.
>
> 5. Alembic migration adding the four new tables with correct foreign keys
>    and indexes as specified.
>
> 6. Tests: model creation and relationships, RepositoryIndex.state enum
>    values, and get_repository_or_404 correctly returning 404/403/200 for
>    not-found, wrong-owner, and correct-owner cases respectively (use a
>    temporary test route to exercise the dependency).
>
> Out of scope: any real GitHub API call, any real ZIP handling, any parsing,
> any indexing logic - this phase only creates schema and interface shape.
>
> Acceptance conditions:
>
> - Migration applies cleanly on top of Phase 1's migration.
> - All previous tests still pass.
> - New tests pass.
> - Calling either stub source's methods raises NotImplementedError with a
>   clear message (proves the interface is enforced, not silently mocked).
>
> Append a prompts.md entry. Update README.md status to
> "Status: Phase 2 complete" only after tests pass.

**AI tool:** Codex

**Summary of generated output:** Added the four repository source ORM models and enums, Alembic revision 0002, the RepositorySource protocol and intentional GitHub/upload stubs, the shared repository ownership dependency, and Phase 2 model, authorization, enum, and stub tests.

**Resulting module/commit:** `backend/app/models/`, `backend/app/sources/`, `backend/app/api/deps.py`, `backend/alembic/versions/0002_add_repository_source_tables.py`, and `backend/tests/test_repositories.py`.

**Test result:** All 14 backend tests passed. Alembic upgraded the live PostgreSQL database from revision 0001 to 0002, and direct schema inspection confirmed the required tables, enums, indexes, uniqueness constraints, and foreign-key deletion behavior.

### 2026-09-17 - Phase 3 LLM provider abstraction

**Prompt:**

> Read PRISM_SPEC.md section 21 (LLM Architecture) in full before starting.
> Inspect backend/app/config.py from Phase 0 to see how settings are currently
> loaded.
>
> This is Phase 3 of Prism. Implement:
>
> 1. backend/app/llm/base.py: the LLMProvider protocol from PRISM_SPEC.md
>    section 21 (complete(messages, schema, timeout_s) -> LLMResult), plus
>    Message and LLMResult data classes (LLMResult includes: content,
>    input_tokens, output_tokens, latency_ms, raw_response).
>
> 2. backend/app/llm/openai_compatible.py: OpenAICompatibleProvider(name,
>    base_url, api_key, timeout_s) calling an OpenAI-compatible
>    /chat/completions style endpoint over HTTP (use httpx). Do not hard-code
>    any specific provider's base URL, model name, or API key anywhere - all
>    three must come from the caller's configuration.
>
> 3. backend/app/llm/mock.py: MockProvider returning deterministic, canned
>    responses. It must support returning either plain text or content that
>    parses against a given Pydantic schema, configurable per test via a
>    simple canned-response list or callback, so tests can assert exact
>    agent/tool behavior against known model output.
>
> 4. backend/app/llm/factory.py: get_model_a() and get_model_b() functions
>    constructing OpenAICompatibleProvider instances from settings
>    (MODEL_A_NAME, MODEL_A_BASE_URL, MODEL_A_API_KEY, MODEL_A_TIMEOUT and the
>    Model B equivalents). Both are equal peers - do not name one "primary" or
>    "default" anywhere in code, comments, or variable names.
>
> 5. backend/app/api/routes/models.py: GET /models/config returning
>    {"model_a": {"name": ...}, "model_b": {"name": ...}} - never api keys or
>    base urls. Requires authentication.
>
> 6. Tests in backend/tests/test_llm.py: MockProvider returns configured
>    responses deterministically; OpenAICompatibleProvider is tested with a
>    mocked HTTP transport (httpx MockTransport or respx), not a real network
>    call; GET /models/config returns names only and never leaks keys, using
>    test-only placeholder model configuration.
>
> 7. A standalone manual script at backend/scripts/smoke_test_model.py that
>    accepts a slot (a or b) as an argument, loads real settings, and prints
>    the raw response from a real call - this script is never invoked by the
>    automated test suite and is documented as manual-only in a comment at
>    its top.
>
> Out of scope: the agent controller, tools, retrieval - this phase only
> builds and tests the model abstraction in isolation.
>
> Acceptance conditions:
>
> - All previous tests still pass.
> - New tests pass with zero real network calls.
> - GET /models/config never includes model_a.api_key or similar fields.
> - Compare Models logic is NOT implemented yet - this phase provides only the
>   per-slot provider abstraction.
>
> Append a prompts.md entry. Update README.md status to
> "Status: Phase 3 complete" only after tests pass.

**AI tool:** Codex

**Summary of generated output:** Added the provider protocol and result types, configurable OpenAI-compatible HTTP provider, deterministic MockProvider, equal Model A and Model B factories, authenticated model-name configuration endpoint, manual-only smoke script, and isolated Phase 3 tests.

**Resulting module/commit:** `backend/app/llm/`, `backend/app/api/routes/models.py`, `backend/scripts/smoke_test_model.py`, `backend/app/main.py`, and `backend/tests/test_llm.py`.

**Test result:** All 20 backend tests passed with the provider HTTP test using `httpx.MockTransport` and no real model calls. The existing frontend test passed. Docker Compose configuration validated, the backend image rebuilt successfully, and the rebuilt service returned `{"status":"ok"}` from `/health`.

### 2026-09-17 - Phase 4 Week 5 agent scaffold

**Prompt:**

> Read PRISM_SPEC.md sections 15 (Retrieval & Context Building, Evidence
> Context concept), 16 (Agent Architecture & Execution Loop), 17 (Skills/Tool
> Registry), 19 (Memory Architecture), 20 (Hooks, Tracing & Observability),
> and 22 (Structured Outputs, Evidence & Grounding) before starting. Inspect
> backend/app/llm/ from Phase 3.
>
> This is Phase 4 of Prism. Implement:
>
> 1. backend/app/evidence/models.py: the Evidence Pydantic model exactly as
>    defined in PRISM_SPEC.md section 22.1 (evidence_id, repository_id,
>    repository_index_id, source_type, file_path, symbol, start_line,
>    end_line, content_excerpt, relationship_metadata, retrieval_metadata,
>    external_source_metadata).
>
> 2. backend/app/tools/base.py: the Tool protocol from PRISM_SPEC.md section
>    17 (name, description, input_schema, output_schema, requires_auth,
>    execute). backend/app/tools/registry.py: ToolRegistry with register/get/
>    list. Do not register any concrete tools yet - leave the registry empty
>    except for tests that register a trivial fake tool to prove the
>    mechanism works.
>
> 3. backend/app/memory/base.py: MemoryService interface with methods
>    matching PRISM_SPEC.md section 19 (retrieve, save, invalidate_stale) as
>    method signatures with a minimal working implementation backed by a
>    simple table sufficient to pass this phase's tests (the full three-
>    category schema from section 19.1 will be completed in a later
>    dedicated memory phase - for now this only needs to exist and be
>    callable, not be feature-complete).
>
> 4. Tables and models for AgentRun, ToolCall, ModelExecution matching
>    PRISM_SPEC.md sections 20 and 25 (fields: as specified). Alembic
>    migration adding them.
>
> 5. backend/app/tracing/hooks.py: HookManager with pre_tool, post_tool, and
>    model_execution methods that persist to the tables above, sanitizing any
>    argument that looks like a credential before storage.
>
> 6. backend/app/agent/controller.py: a minimal AgentController.run(task)
>    that: creates an AgentRun row, calls MockProvider via the LLMProvider
>    abstraction from Phase 3 wrapped with a model_execution hook call,
>    returns a trivially schema-validated result. This is intentionally not
>    yet doing task classification, tool selection, or bounded iteration -
>    that is built in a later dedicated agent phase. Its only job right now
>    is to prove: task in -> model call -> hook recorded -> AgentRun
>    persisted -> validated result out.
>
> 7. backend/tests/test_agent_skeleton.py: an end-to-end test that calls
>    AgentController.run() with MockProvider configured to return a known
>    response, then asserts an AgentRun row exists with a linked
>    ModelExecution row showing the mock model's name and a successful
>    validation status.
>
> Out of scope: real retrieval, real tools, real task classification, real
> bounded iteration, real memory categories, real flow tracing or Q&A. This
> phase is scaffolding only, per PRISM_SPEC.md's Week 5 scope.
>
> Acceptance conditions:
>
> - All previous tests still pass.
> - The new end-to-end test passes using only MockProvider.
> - No part of this phase makes a real network call.
>
> Append a prompts.md entry. Update README.md status to
> "Status: Phase 4 complete" only after tests pass. Note in README that this
> completes the Week 5 scaffold milestone from PRISM_SPEC.md.

**AI tool:** Codex

**Summary of generated output:** Added the Evidence schema, empty ToolRegistry and Tool protocol, minimal persisted MemoryService, agent trace ORM models and hooks with recursive credential redaction, and a minimal schema-validating AgentController path through MockProvider. Added the Section 25 Session table as the required foreign-key target for AgentRun without implementing conversation behavior.

**Resulting module/commit:** `backend/app/evidence/`, `backend/app/tools/`, `backend/app/memory/`, `backend/app/tracing/`, `backend/app/agent/`, agent trace models in `backend/app/models/`, `backend/alembic/versions/0003_add_agent_scaffold_tables.py`, and `backend/tests/test_agent_skeleton.py`.

**Test result:** All 25 backend tests and the existing frontend test passed, including the mocked end-to-end agent path and tests for tool registration, credential sanitization, minimal memory persistence, and the Evidence schema. Alembic revision 0003 applied to PostgreSQL, all five scaffold tables were confirmed present, Docker Compose validated, and the migrated backend returned `{"status":"ok"}` from `/health`. No test made a real model or other network call.

### 2026-09-17 - Phase 5 ZIP ingestion

**Prompt:**

> Read PRISM_SPEC.md sections 8 (Repository Sources & ZIP Upload), 10
> (File Filtering & Security), and 2.6 (MVP Scope Limits) in full before
> starting. Inspect backend/app/sources/upload.py and backend/app/sources/base.py
> from Phase 2, and backend/app/api/deps.py.
>
> This is Phase 5 of Prism. Implement:
>
> 1. backend/app/ingestion/security.py: safe_extract(zip_path, dest_dir)
>    that validates every archive entry's resolved path stays under dest_dir
>    (reject any entry containing ".." or resolving outside the root, reject
>    absolute paths, reject symlink entries), enforces MAX_ZIP_SIZE_MB and a
>    maximum extracted file count/size from settings, and raises a specific
>    ZipSafetyError with a clear reason on violation.
>
> 2. backend/app/ingestion/filtering.py: source-independent functions
>    is_ignored_path(path) (default excluded directories from PRISM_SPEC.md
>    section 10, plus best-effort .gitignore pattern matching if a
>    .gitignore is present in the uploaded content), is_secret_file(path)
>    (denylist from section 10), is_binary(content_bytes) (null-byte
>    heuristic), and classify_file(path, content_bytes) returning a status
>    from RepositoryFile.status (OK, OVERSIZED, BINARY, PARSE_FAILED is not
>    used here - only OK/OVERSIZED/BINARY at this phase).
>
> 3. Complete UploadedRepositorySource in backend/app/sources/upload.py:
>    list_files enumerates the extracted directory applying filtering;
>    get_file_content reads a file's bytes; get_revision returns a
>    content-hash of the full file listing (sorted path -> content_hash
>    pairs, hashed together) since there is no external revision identifier
>    for an upload.
>
> 4. backend/app/ingestion/pipeline.py: discover_and_normalize(source:
>    RepositorySource, revision: str) -> list[NormalizedFile] that calls
>    list_files, applies filtering/classification, and returns normalized
>    file records. This function must not know or care whether it was called
>    with a GitHubRepositorySource or UploadedRepositorySource - write it
>    generically against the RepositorySource protocol from Phase 2. After
>    normalization, if the count of indexable (non-ignored, non-binary,
>    non-oversized) files exceeds the ~2,000-file MVP target from PRISM_SPEC.md
>    section 2.6, set RepositoryIndex.size_warning = true (add this boolean
>    column via migration) rather than rejecting the repository - indexing
>    still proceeds. This is separate from, and does not replace, the hard
>    MAX_ZIP_SIZE_MB / file-size / raw-file-count bounds from section 29.2,
>    which are still enforced as hard rejections.
>
> 5. backend/app/api/routes/repositories.py: POST /repositories accepting a
>    multipart ZIP upload, creating a Repository (source_type=upload) and a
>    RepositoryIndex (state starts PENDING, moves to DISCOVERING then READY
>    once discover_and_normalize completes synchronously for this phase -
>    full async job handling is a later phase), persisting RepositoryFile
>    rows from the normalized result. Enforce MAX_ZIP_SIZE_MB with a 413
>    response before extraction is attempted.
>
> 6. Tests in backend/tests/test_zip_ingestion.py using small fixture ZIPs
>    under backend/tests/fixtures/: a Zip Slip attempt is rejected before any
>    file is written outside the extraction root; an oversized ZIP is
>    rejected with 413; a ZIP containing node_modules/, .env, and a binary
>    file correctly excludes/classifies each; a clean small fixture repo
>    normalizes into the expected RepositoryFile rows; a fixture with more
>    than the ~2,000-indexable-file threshold sets size_warning=true on the
>    resulting RepositoryIndex while still completing indexing (a synthetic
>    fixture with many trivially small files is sufficient - do not require a
>    real 2,000-file repository).
>
> Out of scope: GitHub integration, Tree-sitter parsing, chunking, embeddings,
> asynchronous job execution (keep this phase synchronous for simplicity -
> async execution is formalized once GitHub sync also needs it).
>
> Acceptance conditions:
>
> - All previous tests still pass.
> - Zip Slip and oversized-ZIP tests fail safely with no partial extraction
>   outside the sandboxed directory.
> - Secret and binary files never appear in a "content read for indexing"
>   code path, even though they may still appear in the raw file listing
>   with the correct status.
> - A repository under the ~2,000-indexable-file target never sets
>   size_warning; a repository over it does, and still reaches READY rather
>   than being rejected.
>
> Append a prompts.md entry. Update README.md status to
> "Status: Phase 5 complete" only after tests pass.

**AI tool:** Codex

**Summary of generated output:** Added preflight-safe ZIP extraction with path, symlink, archive-size, extracted-size, and raw-file-count enforcement; source-independent filtering and classification; the completed uploaded repository source; generic normalization; synchronous authenticated ZIP ingestion; and the non-blocking repository size warning migration. Added configurable extracted-size and file-count hard bounds without changing the 2,000-file warning into a rejection.

**Resulting module/commit:** `backend/app/ingestion/`, `backend/app/sources/upload.py`, `backend/app/api/routes/repositories.py`, `backend/alembic/versions/0004_add_repository_index_size_warning.py`, configuration files, checked-in fixtures under `backend/tests/fixtures/`, and `backend/tests/test_zip_ingestion.py`.

**Test result:** All 29 backend tests and the existing frontend test passed. The ZIP suite verified pre-write Zip Slip rejection, a 413 response before extraction for oversized uploads, exclusion of `node_modules/` and `.env`, binary classification, expected persistence for a clean fixture, and `READY` plus `size_warning=true` for 2,001 indexable files. Alembic revision 0004 applied to PostgreSQL, the non-null boolean column and false default were confirmed, Docker Compose validated, and the backend health check returned `{"status":"ok"}`.

### 2026-09-17 - Phase 6 GitHub App integration

**Prompt:**

> Read PRISM_SPEC.md section 7 (GitHub App Integration) in full before
> starting. Inspect backend/app/sources/github.py (currently a stub from
> Phase 2), backend/app/ingestion/pipeline.py and backend/app/ingestion/
> filtering.py from Phase 5, and backend/app/models/ for GitHubInstallation
> and Repository.
>
> This is Phase 6 of Prism. Implement:
>
> 1. backend/app/github/client.py: GitHubClient wrapping: app-level JWT
>    signing using GITHUB_APP_PRIVATE_KEY_PATH and GITHUB_APP_ID, installation
>    access token retrieval and caching with expiry-aware refresh, list
>    installations, list repositories for an installation (paginated via Link
>    headers), get default branch, get branch list, get repository tree
>    (recursive), get file/blob content. Implement retry with exponential
>    backoff on 5xx and rate-limit-aware backoff using response headers, up to
>    3 attempts, per PRISM_SPEC.md section 7.3.
>
> 2. backend/app/github/errors.py: typed exceptions - GitHubInstallationRevoked,
>    GitHubAccessLost, GitHubRepositoryDeleted, GitHubBranchMissing,
>    GitHubRateLimited, GitHubApiError - raised by the client based on
>    response status codes per PRISM_SPEC.md section 7.4's table.
>
> 3. backend/app/api/routes/github.py: GET /github/install-url, GET
>    /github/callback (persists a GitHubInstallation), GET
>    /github/installations, GET /github/installations/{id}/repositories.
>
> 4. Complete GitHubRepositorySource in backend/app/sources/github.py:
>    list_files uses the tree API and yields SourceFileRef entries;
>    get_file_content fetches blob content; get_revision returns the branch's
>    current commit SHA. It must satisfy the exact same RepositorySource
>    protocol Phase 5's UploadedRepositorySource satisfies.
>
> 5. Extend POST /repositories to accept {source_type: "github",
>    github_repo_id, branch} and run the same discover_and_normalize function
>    from Phase 5 against a GitHubRepositorySource instance - do not write a
>    second normalization path. Persist github_sha per RepositoryFile (this
>    field exists on the model from Phase 2; populate it here for the first
>    time).
>
> 6. Tests in backend/tests/test_github_integration.py mocking the GitHub API
>    (respx or httpx MockTransport) covering: successful installation token
>    retrieval and caching, pagination across multiple pages, each typed error
>    condition from PRISM_SPEC.md section 7.4, and a full import producing the
>    same shape of RepositoryFile rows as the Phase 5 ZIP test does for an
>    equivalent small fixture tree.
>
> Out of scope: incremental synchronization logic beyond initial import
> (diffing against a previous index is Phase 20's job), Tree-sitter parsing,
> chunking, embeddings.
>
> Acceptance conditions:
>
> - All previous tests still pass.
> - No test makes a real call to api.github.com.
> - GitHubRepositorySource and UploadedRepositorySource both satisfy
>   discover_and_normalize with no branching logic inside that function based
>   on source type.
> - GitHub App private key and tokens never appear in logs or test output.
>
> Append a prompts.md entry. Update README.md status to
> "Status: Phase 6 complete" only after tests pass, and add a short setup note
> in README pointing to the [MANUAL] GitHub App creation steps below.

**AI tool:** Codex

**Summary of generated output:** Added the GitHub App REST client with RS256 app JWT signing, expiry-aware installation-token caching, pagination, repository metadata/tree/blob methods, bounded retry behavior, and typed lifecycle errors. Added authenticated GitHub installation routes, completed GitHubRepositorySource, and extended the existing repository import endpoint so GitHub and ZIP sources share the same normalization and persistence path.

**Resulting module/commit:** `backend/app/github/`, `backend/app/api/routes/github.py`, `backend/app/sources/github.py`, the shared `backend/app/api/routes/repositories.py` import route, `backend/tests/test_github_integration.py`, dependency updates, Docker entrypoint normalization, and README manual setup instructions.

**Test result:** All 39 backend tests and the existing frontend test passed. Eleven GitHub tests used only `httpx.MockTransport` or an in-process fake client and covered token caching, Link pagination, typed revoked/access/deleted/branch/rate-limit/API failures, newline-wrapped blob decoding, all four routes, and a full GitHub import with persisted blob SHAs. Docker Compose validated, the rebuilt backend returned `{"status":"ok"}`, and Alembic remained at revision 0004 head. No test contacted `api.github.com`, and no private key or installation token was emitted in test output.

### 2026-09-18 - Phase 6 GitHub callback security correction

**Prompt:** Analyze the live GitHub App installation failure, distinguish setup problems from code problems, then correct callback authentication, secure Prism-user association, installation ownership verification, redirect behavior, and related setup documentation.

**AI tool:** Codex

**Summary of generated output:** Replaced bearer authentication on the browser callback with a short-lived, one-time, database-backed state created by the authenticated install-url endpoint. Added GitHub user-code exchange and installation-access verification before associating an installation with the state-bound Prism user, plus a configurable success redirect and corrected manual setup instructions.

**Modified/rejected:** Rejected removing callback authentication without replacement and rejected trusting the callback's numeric installation ID alone. The callback now requires both validated state and GitHub user authorization.

**Resulting module/commit:** `backend/app/api/routes/github.py`, `backend/app/github/client.py`, `backend/app/models/github_installation_attempt.py`, Alembic revision `0005`, GitHub integration tests, environment configuration, and `README.md`.

**Test result:** All 41 backend tests passed, including 13 GitHub integration tests with no live network calls. The frontend Vitest suite passed in Docker, Docker Compose configuration validated, Alembic upgraded PostgreSQL to revision 0005, and the rebuilt backend returned `{"status":"ok"}`.

### 2026-09-18 - Phase 7 code parsing and structural analysis

**Prompt:**

> Read PRISM_SPEC.md section 11 (Code Parsing & Structural Analysis) in full
> before starting. Inspect backend/app/models/ for RepositoryFile, and
> backend/app/ingestion/pipeline.py from Phase 5.
>
> This is Phase 7 of Prism. Implement:
>
> 1. backend/app/parsing/base.py: the TreeSitterParser protocol and
>    ParsedFile/ExtractedSymbol/ImportRef data classes exactly as defined in
>    PRISM_SPEC.md section 11.
>
> 2. backend/app/parsing/python_parser.py,
>    backend/app/parsing/javascript_parser.py,
>    backend/app/parsing/typescript_parser.py (the latter handles both .ts
>    and .tsx, and javascript_parser.py handles both .js and .jsx) - each
>    using the tree-sitter grammars for its language to extract: functions,
>    methods, classes, components (JS/TS: exported function/const returning
>    JSX, by structural heuristic), hooks (JS/TS: names matching ^use[A-Z]),
>    interfaces, types, imports, exports, and symbol definitions. Where
>    practical, also detect API routes (FastAPI-style decorators for Python;
>    Express-style route registration for JS/TS) and test files (naming
>    convention), tagging them in ParsedFile metadata.
>
> 3. backend/app/parsing/relationships.py: extract CodeRelationship records
>    (kind: CALLS, IMPORTS, REFERENCES, API_CALL, EXTENDS) with confidence
>    high for direct AST-resolvable references and low for heuristic/name-
>    based matches, per PRISM_SPEC.md section 11.
>
> 4. backend/app/parsing/fallback.py: on any parser exception or unparseable
>    content, produce a single fallback ParsedFile preserving file path,
>    best-effort language guess, and the full line range, with parse_ok=False
>    and fallback_used=True. This must never raise - it always returns a
>    usable ParsedFile.
>
> 5. backend/app/models/code_symbol.py and
>    backend/app/models/code_relationship.py matching PRISM_SPEC.md section
>    25's code_symbols/code_relationships tables. Alembic migration adding
>    them.
>
> 6. backend/app/ingestion/parsing_stage.py: parse_repository_files(files:
>    list[RepositoryFile]) -> iterates supported files, calls the right
>    parser by extension, persists CodeSymbol/CodeRelationship rows, and
>    records per-file parse failures without stopping the loop for other
>    files.
>
> 7. Tests in backend/tests/test_parsing.py with small fixture files per
>    language (a Python module with a class and functions, a JS file with a
>    component and a hook, a TS file with an interface and a type) verifying
>    expected symbols/relationships are extracted, plus one deliberately
>    malformed file per language proving fallback behavior triggers and does
>    not raise.
>
> Out of scope: chunking, embeddings, indexing - this phase only produces
> symbols and relationships, not CodeChunk rows.
>
> Acceptance conditions:
>
> - All previous tests still pass.
> - A repository-wide parse run over a fixture with one malformed file still
>   reaches a state where all other files are correctly parsed (proves
>   per-file isolation of failures).
> - No relationship is recorded with confidence "high" unless it is backed by
>   an actual AST-resolvable reference, not a name-string heuristic.
>
> Append a prompts.md entry. Update README.md status to
> "Status: Phase 7 complete" only after tests pass.

**AI tool:** Codex

**Summary of generated output:** Added Tree-sitter parser adapters for all five supported source extensions, structural symbol and import extraction, route and test-file metadata, relationship extraction with constrained confidence, non-raising fallback parsing, persisted code symbol and relationship models, and repository-wide parsing integrated into the shared ingestion path. Added persisted source content only for supported, safe source files so parsing remains available after temporary ZIP extraction ends.

**Modified/rejected:** Kept chunking, embeddings, retrieval, and later indexing behavior out of scope. Relationships receive high confidence only when a parsed AST reference resolves to a definition in the same file; name-only and external matches remain low confidence.

**Resulting module/commit:** `backend/app/parsing/`, `backend/app/ingestion/parsing_stage.py`, `backend/app/models/code_symbol.py`, `backend/app/models/code_relationship.py`, `backend/alembic/versions/0006_add_code_structure.py`, parser fixtures, and `backend/tests/test_parsing.py`.

**Test result:** All 48 backend tests passed. The frontend Vitest suite passed. Alembic upgraded PostgreSQL from revision 0005 to 0006 successfully, and Docker Compose configuration remained valid.

### 2026-09-18 - Phase 8 code-aware chunking

**Prompt:**

> Read PRISM_SPEC.md section 12 (Code-Aware Chunking) in full before starting.
> Inspect backend/app/parsing/ from Phase 7 and the CodeSymbol model.
>
> This is Phase 8 of Prism. Implement:
>
> 1. backend/app/chunking/base.py: Chunker protocol producing a list of
>    ChunkDraft objects (pre-persistence) with all CodeChunk fields except id/
>    embedding/timestamps.
>
> 2. backend/app/chunking/python_chunker.py and
>    backend/app/chunking/js_ts_chunker.py implementing structural chunking
>    per PRISM_SPEC.md section 12 for each language family, operating on the
>    ParsedFile/symbols from Phase 7.
>
> 3. backend/app/chunking/fallback_chunker.py: one fallback chunk per file
>    when parse_ok is False, matching section 12.2's fallback behavior.
>
> 4. backend/app/chunking/document_chunker.py: paragraph/heading-based
>    chunking for Markdown/TXT, and text-extracted PDF, per section 12.2,
>    producing chunks tagged source_type=DOCUMENTATION.
>
> 5. Explicit handling of every edge case in PRISM_SPEC.md section 12.2:
>    very large function/class splitting with 200-char overlap and shared
>    parent_symbol metadata; tiny adjacent symbol merging up to the 1,500-char
>    cap; module-level code as one MODULE_SECTION chunk; comments/docstrings
>    kept attached to their owning symbol; config files as one chunk per file;
>    fallback chunks as specified.
>
> 6. backend/app/models/code_chunk.py matching PRISM_SPEC.md section 12.1
>    exactly, including a content_hash column (sha256 of the chunk content)
>    and an embedding vector(384) column (pgvector extension must be enabled
>    in this migration if not already). Alembic migration adding the table
>    and enabling the pgvector extension.
>
> 7. backend/app/ingestion/chunking_stage.py: chunk_repository_files(...)
>    iterating parsed files, calling the correct chunker, computing
>    content_hash per chunk, and persisting CodeChunk rows (embedding left
>    null at this phase).
>
> 8. Tests in backend/tests/test_chunking.py covering: a large function
>    splits into overlapping sub-chunks retaining the full symbol's line
>    range in metadata; several tiny exports merge into one MODULE_SECTION
>    chunk; a config file produces exactly one chunk; a Markdown supplementary
>    document chunks by heading/paragraph with source_type=DOCUMENTATION; a
>    fallback-parsed file produces exactly one FALLBACK chunk; identical
>    content in two different chunks produces the same content_hash.
>
> Out of scope: embeddings, pgvector similarity search, retrieval - this phase
> only produces chunk rows with hashes, no embedding values.
>
> Acceptance conditions:
>
> - All previous tests still pass.
> - pgvector extension is enabled via migration, not manually.
> - Every CodeChunk row has a non-null content_hash and correct start_line/
>   end_line even after splitting or merging.
>
> Append a prompts.md entry. Update README.md status to
> "Status: Phase 8 complete" only after tests pass.

**AI tool:** Codex

**Summary of generated output:** Added structural chunkers for the supported code languages, fallback and document chunkers, config-file handling, large-symbol overlap splitting, large-class method splitting, tiny-symbol merging, module-section extraction, comment attachment, and deterministic SHA-256 hashes. Added CodeChunk persistence with a nullable 384-dimensional pgvector column and integrated chunking into the shared ZIP and GitHub ingestion path.

**Modified/rejected:** Kept embedding generation and similarity retrieval out of scope. The SQLAlchemy attribute for the database `metadata` column is named `chunk_metadata` because `metadata` is reserved by SQLAlchemy's declarative base; the persisted column name remains exactly `metadata`.

**Resulting module/commit:** `backend/app/chunking/`, `backend/app/ingestion/chunking_stage.py`, `backend/app/models/code_chunk.py`, `backend/alembic/versions/0007_add_code_chunks.py`, and `backend/tests/test_chunking.py`.

**Test result:** All 54 backend tests passed. The frontend Vitest suite passed. Alembic upgraded PostgreSQL from revision 0006 to 0007, the `vector` extension was confirmed present, the `embedding` column was confirmed as nullable pgvector, and Docker Compose configuration validated.
