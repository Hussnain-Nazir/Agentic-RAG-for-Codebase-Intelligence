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

### 2026-09-18 - Phase 9 embeddings and indexing

**Prompt:**

> Read PRISM_SPEC.md section 13 (Embeddings & Indexing) in full before
> starting. Inspect backend/app/chunking/ and backend/app/models/code_chunk.py
> from Phase 8.
>
> This is Phase 9 of Prism. Implement:
>
> 1. backend/app/embeddings/base.py: the EmbeddingProvider protocol
>    (dimensions, embed_batch) from PRISM_SPEC.md section 13.
>
> 2. backend/app/embeddings/local_provider.py: LocalEmbeddingProvider loading
>    BAAI/bge-small-en-v1.5 via sentence-transformers, batching in groups of
>    32 as specified, configurable via EMBEDDING_MODEL_NAME.
>
> 3. backend/app/ingestion/embedding_stage.py: embed_repository_chunks(...)
>    that, for each chunk needing an embedding, first checks whether a chunk
>    with the same content_hash and current embedding_model_version already
>    has an embedding (reuse it, do not recompute), and otherwise batches
>    remaining chunks through LocalEmbeddingProvider and persists the vector.
>    Track embedding_model_version (a simple settings-derived string) so a
>    future model change is detected rather than silently mixing embedding
>    spaces.
>
> 4. Alembic migration adding the ivfflat index on code_chunks.embedding
>    using vector_cosine_ops with lists=100, and a composite btree index on
>    (repository_id, repository_index_id).
>
> 5. backend/app/retrieval/vector_search.py: semantic_search(repository_id,
>    repository_index_id, query_embedding, top_k) -> ranked CodeChunk rows
>    using cosine distance, always filtering by repository_id and
>    repository_index_id before the ANN search.
>
> 6. Tests in backend/tests/test_embeddings.py: embedding two chunks with
>    identical content produces the same stored vector without a second
>    model call (assert the embedding call count, using a fast fake
>    embedding model in tests rather than downloading the real model in CI if
>    that is more practical - document whichever choice you make and why);
>    semantic_search on a small fixture repository returns the expected
>    most-similar chunk for a known query; semantic_search never returns
>    chunks from a different repository_id even when content is similar.
>
> Out of scope: lexical search, symbol search, hybrid merging, the
> ContextBuilder - this phase only makes vector search work in isolation.
>
> Acceptance conditions:
>
> - All previous tests still pass.
> - Re-running embedding generation on an unchanged repository performs zero
>   new embedding computations.
> - semantic_search enforces repository isolation in every test case.
>
> Append a prompts.md entry, noting explicitly whether real or fake embedding
> models were used in the automated test suite and why. Update README.md
> status to "Status: Phase 9 complete" only after tests pass.

**AI tool:** Codex

**Summary of generated output:** Added the provider-agnostic embedding protocol, the local sentence-transformers provider with 32-item batching and 384-dimensional validation, settings-derived embedding model version tracking, content-hash reuse across chunks, and isolated cosine vector search. Added the Phase 9 PostgreSQL indexes and a lookup index for content hash plus embedding model version.

**Modified/rejected:** Automated tests use fake embedding models and never download `BAAI/bge-small-en-v1.5`. This keeps the suite deterministic, fast, and independent of network access while directly testing 32-item batching, vector persistence, content-hash reuse, reruns with zero computations, cosine ranking, and repository isolation. The production provider still loads the configured sentence-transformers model. The composite and ivfflat indexes had been created prematurely in revision 0007; their definitions were moved to revision 0008, which conditionally removes the earlier indexes before recreating them so both existing and fresh databases upgrade safely.

**Resulting module/commit:** `backend/app/embeddings/`, `backend/app/ingestion/embedding_stage.py`, `backend/app/retrieval/vector_search.py`, `backend/app/models/code_chunk.py`, `backend/alembic/versions/0008_add_embedding_indexes.py`, `backend/requirements.txt`, and `backend/tests/test_embeddings.py`.

**Test result:** All 58 backend tests passed in Docker. The frontend Vitest suite and production build passed. Alembic upgraded the existing PostgreSQL database from revision 0007 to 0008, and a separate empty verification database successfully applied the full migration chain through 0008. PostgreSQL confirmed the nullable embedding model version column, the composite repository/version B-tree index, and the ivfflat cosine index with `lists=100`.

### 2026-09-19 - Phase 10 lexical and symbol retrieval

**Prompt:**

> Read PRISM_SPEC.md sections 14 (Hybrid RAG Architecture) and 6.1 (lexical
> retrieval decision: PostgreSQL full-text search) before starting. Inspect
> backend/app/retrieval/vector_search.py from Phase 9 to match its return
> shape.
>
> This is Phase 10 of Prism. Implement:
>
> 1. Alembic migration adding a generated tsvector column (or a functional
>    GIN index directly on to_tsvector('english', content)) on code_chunks,
>    plus a GIN trigram index on code_symbols.name (enable pg_trgm extension
>    if not already enabled).
> 2. backend/app/retrieval/lexical_search.py using ts_rank_cd, scoped by
>    repository_id and repository_index_id.
> 3. backend/app/retrieval/symbol_search.py returning exact and top-10
>    trigram matches mapped to owning chunks.
> 4. A shared RankedChunk data class used by semantic, lexical, and symbol
>    retrieval.
> 5. Tests for lexical ranking, exact and fuzzy symbol matching, and
>    repository isolation.
>
> Merging signals, structural expansion, and ContextBuilder are out of scope.
> Append a prompts.md entry and update README.md to Phase 10 only after all
> tests pass.

**AI tool:** Codex

**Summary of generated output:** Added a shared `RankedChunk` result type, updated semantic retrieval to use it, added PostgreSQL full-text lexical retrieval, added exact and trigram symbol retrieval mapped to owning chunks, and added the required generated search vector and GIN indexes.

**Modified/rejected:** Kept hybrid merging, cross-signal normalization, exact-symbol boosting, structural expansion, and context construction out of scope. SQLite uses deterministic local scoring only for isolated automated tests; PostgreSQL production paths use `ts_rank_cd`, the generated `tsvector`, and `pg_trgm` candidate ranking.

**Resulting module/commit:** `backend/app/retrieval/`, `backend/app/models/code_symbol.py`, `backend/alembic/versions/0009_add_lexical_and_symbol_indexes.py`, `backend/tests/test_embeddings.py`, and `backend/tests/test_lexical_symbol_retrieval.py`.

**Test result:** All 63 backend tests passed, including five new lexical/symbol retrieval tests and the updated semantic retrieval tests. The frontend Vitest suite passed one test. Alembic upgraded PostgreSQL to revision 0009; PostgreSQL confirmed the generated `search_vector` column, `pg_trgm`, and both required GIN indexes.

### 2026-09-19 - Phase 11 hybrid retrieval and structural expansion

**Prompt:**

> Read PRISM_SPEC.md section 14 (Hybrid RAG Architecture) in full, especially
> the frozen parameters table in 14.1, before starting. Inspect
> backend/app/retrieval/vector_search.py, lexical_search.py, and
> symbol_search.py from Phases 9-10, and
> backend/app/models/code_relationship.py from Phase 7.
>
> This is Phase 11 of Prism. Implement:
>
> 1. backend/app/retrieval/ranking.py: per-signal min-max normalization,
>    merging with the exact 0.5/0.3/0.2 weights and +0.5 exact-symbol boost,
>    duplicate and greater-than-50-percent overlap collapse, and merging
>    same-file chunks within five lines.
> 2. backend/app/retrieval/expansion.py: bounded structural expansion through
>    CodeRelationship rows for the top eight chunks, with at most two chunks
>    per seed and 15 expansion chunks total.
> 3. backend/app/retrieval/hybrid.py: a HybridRetriever that invokes all three
>    signals with the frozen candidate counts, merges, deduplicates, ranks,
>    expands, and returns RankedChunk results without applying the future
>    ContextBuilder evidence cap.
> 4. Tests proving exact-symbol boosting, overlap collapse, adjacent merging,
>    bounded relationship expansion, and deterministic full-pipeline order.
>
> ContextBuilder token enforcement and Evidence construction are out of
> scope. No LLM call may occur. Append a prompts.md entry and update README.md
> to Phase 11 only after all tests pass.

**AI tool:** Codex

**Summary of generated output:** Added deterministic per-signal normalization, frozen weighted merging, exact-symbol boosting, chunk and overlap deduplication, adjacent evidence-unit merging, bounded CodeRelationship expansion, and the end-to-end HybridRetriever pipeline.

**Modified/rejected:** Kept ContextBuilder token limits, final top-12 evidence selection, Evidence object construction, model calls, and agent integration out of scope. Adjacent transient evidence units preserve deterministic IDs and their original source chunk IDs. Structural expansion adds at most 15 related chunks in addition to the ranked seeds, matching section 14.1's expansion bound.

**Resulting module/commit:** `backend/app/retrieval/ranking.py`, `backend/app/retrieval/expansion.py`, `backend/app/retrieval/hybrid.py`, `backend/app/retrieval/models.py`, `backend/app/retrieval/__init__.py`, and `backend/tests/test_hybrid_retrieval.py`.

**Test result:** All 70 backend tests passed, including seven Phase 11 tests for frozen weights, exact-symbol boosting, duplicate and overlap collapse, adjacent merging, bounded structural expansion, and deterministic pipeline ordering. The frontend Vitest suite passed one test. No LLM module is imported or invoked by the Phase 11 retrieval path.

### 2026-09-19 - Phase 12 evidence and context building

**Prompt:**

> Read PRISM_SPEC.md sections 15 (Retrieval & Context Building) and 22.1
> (Evidence schema) in full before starting. Inspect
> backend/app/retrieval/hybrid.py from Phase 11,
> backend/app/evidence/models.py from Phase 4, and
> backend/app/memory/base.py from Phase 4.
>
> Implement real Evidence construction from RankedChunk fields, a
> provider-independent EvidenceContext and ContextBuilder, repository-memory
> keyword filtering, repository/structural/web evidence merging, Phase 11
> deduplication and neighboring-chunk handling, relationship provenance,
> whole-chunk trimming to the approximate 6,000-token limit, and evidence
> quality classification as STRONG, INCOMPLETE, CONFLICTING, or NONE.
> Add tests for strong, empty, conflicting, and oversized contexts. Web
> provider integration, the agent controller, and structured response schemas
> remain out of scope. Append the development log and update README to Phase
> 12 only after all tests pass.

**AI tool:** Codex

**Summary of generated output:** Added deterministic Evidence construction, provider-independent EvidenceContext models, ContextBuilder merging and memory filtering, whole-item context-budget enforcement, optional web-evidence conversion, relationship metadata preservation, and evidence-quality classification.

**Modified/rejected:** Kept web provider calls, agent orchestration, model-provider references, weak-evidence routing decisions, and structured response generation out of scope. Context trimming keeps complete excerpts and drops lower-ranked items rather than truncating a retained item.

**Resulting module/commit:** `backend/app/evidence/`, `backend/app/retrieval/models.py`, `backend/app/retrieval/ranking.py`, `backend/app/retrieval/expansion.py`, `backend/app/retrieval/symbol_search.py`, and `backend/tests/test_context_builder.py`.

**Test result:** All 85 backend tests passed, including five Phase 12 context-builder tests. The frontend Vitest suite passed one test. EvidenceContext contains no model/provider-specific fields or imports.

### 2026-09-19 - Phase 13 memory architecture

**Prompt:**

> Read PRISM_SPEC.md section 19 (Memory Architecture) in full before
> starting. Inspect backend/app/memory/base.py from Phase 4 and
> backend/app/evidence/context_builder.py from Phase 12.
>
> Implement the repository_memories and findings models and migration, then
> replace the Phase 4 memory scaffold with session-memory retrieval,
> repository-memory retrieval and persistence, changed-file staleness
> invalidation, evidence-required finding persistence, and the bounded
> automatic-write rules from section 19.2. Add deterministic tests for stale
> filtering, targeted invalidation, finding validation, and automatic-write
> eligibility. Real incremental-sync integration remains out of scope until
> Phase 20. Append the development log and update README to Phase 13 only
> after all tests pass.

**AI tool:** Codex

**Summary of generated output:** Added repository memory, finding, and conversation-message persistence; implemented bounded session summaries, repository-memory search, evidence-grounded writes, changed-file invalidation, finding validation, and the automatic-write eligibility function used by the future controller call site.

**Modified/rejected:** Kept incremental-sync wiring out of scope. The Phase 4 `memory_items` scaffold table remains in the migration history for safety but is no longer used by MemoryService. Added the specification's `messages` table because session-memory retrieval cannot be implemented without persisted conversation turns.

**Resulting module/commit:** `backend/app/models/repository_memory.py`, `backend/app/models/finding.py`, `backend/app/models/message.py`, `backend/app/memory/`, `backend/alembic/versions/0010_add_memory_and_findings.py`, and `backend/tests/test_memory.py`.

**Test result:** All 90 backend tests passed, including five Phase 13 memory tests. The frontend Vitest suite passed one test. Alembic upgraded PostgreSQL through revisions 0010 and 0011; PostgreSQL confirmed UUID-array evidence columns, and smoke tests verified memory/finding writes, ORM round trips, default retrieval, changed-file invalidation, and cascade cleanup.

### 2026-09-19 - Phase 14 file-reading and web-search plugins

**Prompt:**

> Read PRISM_SPEC.md section 18 (File Reading Plugin, Web Search Plugin) in
> full before starting. Inspect backend/app/tools/base.py and
> backend/app/tools/registry.py from Phase 4, and the CodeChunk and
> RepositoryFile models.
>
> Implement real authenticated `read_file` and `read_file_range` tools over
> stored current-index content with the specified validation order and line
> bounds. Implement a SerpAPI provider using its documented `/search`
> contract, an independently callable `search_web` tool with an eight-second
> timeout and 24-hour query-hash cache, safe empty error results, the
> `web_sources` persistence model, and plugin registration. Add deterministic
> file and mocked-web tests. Conditional agent invocation remains out of
> scope until Phase 17. Append the development log, update README to Phase
> 14, and document SerpAPI setup only after all tests pass.

**AI tool:** Codex

**Summary of generated output:** Added stored-index file and line-range tools, ordered authorization and safety validation, SerpAPI organic-result mapping, bounded and cached web search, safe provider failure handling, the web-source cache model and migration, and built-in plugin registration.

**Modified/rejected:** Kept task-classification wiring out of scope. The tool exposes the Phase 17 trigger helper but always executes when explicitly called. Cache rows store only normalized-query hashes and public result metadata; API keys and raw provider errors are never persisted or returned.

**Resulting module/commit:** `backend/app/plugins/`, `backend/app/tools/`, `backend/app/models/web_source.py`, `backend/alembic/versions/0012_add_web_sources.py`, `backend/app/config.py`, `.env.example`, `backend/tests/test_file_plugin.py`, and `backend/tests/test_web_plugin.py`.

**Test result:** All 104 backend tests passed, including nine file-plugin and five web-plugin tests. The frontend Vitest suite passed one test. Alembic upgraded PostgreSQL to revision 0012 and the web-source cache schema was confirmed. Every SerpAPI test used `httpx.MockTransport` or a fake provider; no test made a real SerpAPI request.

### 2026-09-19 - Phase 15 complete tool registry

**Prompt:**

> Read PRISM_SPEC.md section 17 (Skills/Tool Registry, including the full
> contract table in 17.1) in full before starting. Inspect the hybrid
> retriever, evidence layer, memory service, and Phase 4 ToolRegistry.
>
> Implement real Tool classes for search_codebase, find_symbol,
> find_references, get_related_files, inspect_repository, retrieve_memory,
> save_memory, and get_review_history, using the exact repository-scoped
> contracts. Register them with the existing read_file, read_file_range, and
> search_web plugins so ToolRegistry lists exactly eleven tools. Centralize
> typed errors and add deterministic happy-path, authorization, current-index,
> validation, and registry tests. Agent decision logic remains out of scope
> until Phase 17. Append the development log and update README to Phase 15
> only after all tests pass.

**AI tool:** Codex

**Summary of generated output:** Added provider-independent tool schemas, eight real repository/memory tools, shared authorization and current-index helpers, centralized typed tool errors, deterministic architecture inspection, symbol/reference mappings, structural evidence expansion, and exact eleven-tool registry assembly.

**Modified/rejected:** Kept tool-selection and routing logic out of scope. SearchCodebase lazily constructs the local embedding provider when one is not injected, keeping registry construction lightweight and tests deterministic. Optional review history only queries saved REVIEW findings and does not implement the review feature.

**Resulting module/commit:** `backend/app/tools/errors.py`, `backend/app/tools/repository_context.py`, `backend/app/tools/schemas.py`, `backend/app/tools/repository_tools.py`, `backend/app/tools/registry.py`, plugin error integration, and `backend/tests/test_tool_registry.py`.

**Test result:** All 111 backend tests passed, including seven Phase 15 registry/tool integration tests. The frontend Vitest suite passed one test. ToolRegistry returned exactly the eleven specification names in the frozen order.

### 2026-09-20 - Phase 16 structured outputs and grounding validation

**Prompt:**

> Read PRISM_SPEC.md section 22 (Structured Outputs, Evidence & Grounding) in
> full before starting. Inspect the Phase 12 Evidence and ContextBuilder
> implementations.
>
> Implement RepositoryAnswer, FlowTraceResponse/FlowStep,
> ChangeImpactResponse/ImpactItem, ArchitectureResponse, and
> ModelComparisonResponse/ModelResult exactly as specified. Add reusable
> schema parsing errors, citation validation in the specified order with
> downgrade-and-remove behavior, and exactly one bounded repair call. Test
> every response schema, successful and failed repair, nonexistent evidence,
> line drift, and stale index versions. Agent routing and feature prompt
> integration remain out of scope. Append the development log and update
> README to Phase 16 only after all tests pass.

**AI tool:** Codex

**Summary of generated output:** Added all required response schemas, generic Pydantic schema validation with repair-ready error details, canonical EvidenceContext citation validation, typed downgrade results, and a single-call structured-output repair helper.

**Modified/rejected:** Kept controller integration and feature-specific prompts out of scope. EvidenceContext gained provider-independent repository/index IDs and file line counts so citation validation can check current provenance and real bounds without a database or provider dependency. Ingestion now stores file line counts in chunk metadata for future contexts while retaining a fallback for older indexes.

**Resulting module/commit:** `backend/app/schemas/responses.py`, `backend/app/validation/`, `backend/app/agent/repair.py`, Phase 12 evidence-context metadata, ingestion chunk metadata, and `backend/tests/test_structured_output_validation.py`.

**Test result:** All 117 backend tests passed, including six Phase 16 structured-output and citation-validation tests. The frontend Vitest suite passed one test. Both successful and failed repair tests proved exactly one additional provider call.

### 2026-09-20 - Phase 17 bounded agent controller

**Prompt:**

> Read PRISM_SPEC.md section 16 (Agent Architecture & Execution Loop) in full
> before starting. Inspect the Phase 4 controller and hooks plus the Phase
> 12-16 tools, context, memory, and validation layers.
>
> Replace the scaffold with deterministic task classification and the single
> bounded AgentController lifecycle: authorization, memory, hook-wrapped tool
> execution, rule-based evidence gathering, bounded structural and web
> expansion, EvidenceContext construction, exactly one selected model slot,
> schema and citation validation, eligible memory persistence, and complete
> run/tool/model traces. Enforce every Section 16.4 bound and keep direct
> file, symbol, and reference routes model-free. Feature-specific flow and
> impact investigation prompts remain out of scope. Append the development
> log and update README to Phase 17 only after all tests pass.

**AI tool:** Codex

**Summary of generated output:** Added deterministic task classification, a single authorization-scoped AgentController, hook-wrapped registry execution, provider-independent evidence-context assembly from tool outputs, selected-slot structured generation, bounded repair and citation validation, automatic eligible memory writes, partial-result bound termination, and persisted run/tool/model traces.

**Modified/rejected:** Kept feature-specific flow-trace and impact prompts and investigation strategies out of scope. Added an injectable deterministic ExecutionPlan for later strategies and bound-forcing tests; the controller remains the only orchestrator. Provider errors are traced and surfaced without invoking the other model slot.

**Resulting module/commit:** `backend/app/agent/classification.py`, `backend/app/agent/controller.py`, `backend/app/evidence/context_builder.py`, `backend/app/evidence/builder.py`, and `backend/tests/test_agent_orchestration.py`.

**Test result:** All 139 backend tests passed, including 22 Phase 17 classification, orchestration, trace, failure, direct-route, conditional-web, repair, and hard-bound tests. The frontend Vitest suite passed one test. Bound tests separately verified eight tool iterations, three structural rounds, 15 structural chunks, two web searches, one normal model call, and one repair attempt.

### 2026-09-20 - Phase 18 Codebase Q&A

**Prompt:**

> Read PRISM_SPEC.md sections 23.A (Codebase Q&A), 30.0 (Flagship Feature
> Success Criteria - Codebase Q&A row), and 32.1 (runtime prompt requirements)
> before starting. Inspect backend/app/agent/controller.py from Phase 17 and
> backend/app/schemas/responses.py from Phase 16.
>
> This is Phase 18 of Prism. Implement:
>
> 1. backend/app/agent/prompts/v1/repository_qa.md: the Codebase Q&A prompt
>    template, structured per PRISM_SPEC.md section 29's untrusted-content
>    framing (system instructions / user task / trusted metadata / untrusted
>    evidence, clearly delimited), instructing the model to answer only from
>    supplied evidence, cite it, and state insufficient evidence rather than
>    fabricate.
> 2. Wire task_type=REPOSITORY_QA through AgentController.run to use this
>    template and produce a RepositoryAnswer.
> 3. backend/app/api/routes/analysis.py: POST /repositories/{id}/ask
>    accepting {question, model_slot}, requiring authentication and
>    repository ownership, returning {agent_run_id, answer: RepositoryAnswer}.
>    Return 422 with a clear message when evidence quality is NONE without
>    invoking the model.
> 4. Add deterministic tests for grounded fixture evidence, the model-free
>    insufficient-evidence path, rejection of fabricated citations, and
>    persisted AgentRun, ToolCall, and ModelExecution traces.
>
> Flow tracing, change impact, the frontend, and the full benchmark harness
> remain out of scope. Append the development log and update README to Phase
> 18 only after all tests pass.

**AI tool:** Codex

**Summary of generated output:** Added the versioned Repository Q&A runtime prompt, controller prompt selection, authenticated Q&A API route, selected-slot provider and tool-registry dependencies, explicit no-evidence handling, rejection of answers whose citations are all invalid, and end-to-end fixture tests with persisted trace verification.

**Modified/rejected:** Preserved the Phase 16 downgrade-and-remove citation behavior, then marked a Q&A run `INVALID_OUTPUT` only when citation validation removed every cited evidence item. The API maps that case to 422 so a fully ungrounded claim is not returned as a successful answer. The route creates a repository-scoped session because the specified request contract contains only `question` and `model_slot`. Flow tracing, change impact, frontend work, and benchmark evaluation were not implemented.

**Resulting module/commit:** `backend/app/agent/prompts/v1/repository_qa.md`, `backend/app/agent/controller.py`, `backend/app/api/routes/analysis.py`, `backend/app/main.py`, `backend/tests/test_codebase_qa.py`, `README.md`, and `prompts.md`.

**Test result:** All 142 backend tests passed, including three Phase 18 tests. The existing frontend Vitest test passed after restoring dependencies from the committed lockfile. Python bytecode compilation for `backend/app` passed.

### 2026-09-20 - Phase 19 multi-file flow tracing

**Prompt:**

> Read PRISM_SPEC.md sections 16.3, 23.B, the Flow Tracing row in section
> 30.0, and the FlowTraceResponse and FlowStep schemas in section 22.2.
> Implement a versioned flow-tracing prompt, bounded feature-specific
> investigation logic using find_symbol, find_references, and
> get_related_files, controller integration producing FlowTraceResponse, and
> POST /repositories/{id}/flow-trace with the Phase 18 authorization pattern.
> Add deterministic tests for a known cross-file flow, an unresolved external
> call, and bound exhaustion returning a valid partial trace. Keep change
> impact and frontend work out of scope. Update the log and README only after
> all tests pass.

**AI tool:** Codex

**Summary of generated output:** Added the versioned flow-trace prompt, a deterministic investigation state that follows exact symbol definitions through references and related evidence, controller-owned bound enforcement, flow observations in trusted prompt metadata, schema-valid partial traces, and the authenticated flow-trace API endpoint.

**Modified/rejected:** Kept orchestration inside the existing single AgentController. The investigation module receives a hook-wrapped controller callback and does not define independent bounds. Fuzzy symbol matches are not accepted as definitions. When structural evidence reaches the shared cap, further expansion stops without exceeding it. Change-impact behavior and frontend work remain unimplemented.

**Resulting module/commit:** `backend/app/agent/prompts/v1/flow_trace.md`, `backend/app/agent/investigations/`, `backend/app/agent/controller.py`, `backend/app/api/routes/analysis.py`, `backend/tests/test_flow_trace.py`, `backend/tests/test_agent_orchestration.py`, `README.md`, and `prompts.md`.

**Test result:** All 157 backend tests passed. Phase 19 tests verified an ordered observed call across fixture files, an undefined external call marked unresolved without a fabricated transition, and tool-bound exhaustion returning a valid partial FlowTraceResponse.

### 2026-09-22 - Phase 20 change impact and incremental sync

**Prompt:**

> Read PRISM_SPEC.md sections 23.C, 30.0's Change Impact row, and 9.3. Implement a versioned change-impact prompt and bounded investigation using find_symbol, find_references, get_related_files, and search_codebase; wire ChangeImpactResponse through the controller and POST /repositories/{id}/change-impact. Implement GitHub SHA-diff synchronization into a new RepositoryIndex version with unchanged-content reuse, changed/new file processing, deleted-file removal from the new version, and changed/deleted memory invalidation. Add POST /repositories/{id}/sync with a 409 response for an active sync. Add MockProvider-backed impact tests and mocked-GitHub sync tests. Keep the frontend, narrated architecture explanation, and model comparison out of scope. Update this log and README only after all prior and new tests pass.

**AI tool:** Codex

**Summary of generated output:** Added a versioned change-impact prompt, an evidence-backed investigation and deterministic affected-item guard, the authenticated change-impact endpoint, GitHub SHA-based synchronization, current-version relationship remapping, unchanged memory provenance remapping, and a sync endpoint with ownership and in-progress checks.

**Modified/rejected:** Kept the agent bounds and hybrid retrieval parameters unchanged. Sync reuses unchanged rows in a new index version and only parses or embeds them if the configured embedding model version changes. The endpoint performs the sync synchronously; the DB state records each indexing stage. No frontend, model comparison, or architecture-narration behavior was added.

**Resulting module/commit:** `backend/app/agent/prompts/v1/change_impact.md`, `backend/app/agent/investigations/change_impact.py`, `backend/app/agent/controller.py`, `backend/app/api/routes/analysis.py`, `backend/app/ingestion/sync.py`, `backend/app/api/routes/repositories.py`, `backend/app/sources/github.py`, `backend/tests/test_change_impact.py`, and `backend/tests/test_incremental_sync.py`. Changes were left uncommitted.

**Test result:** All 189 backend tests and the existing frontend Vitest test passed. The frontend test required `npm ci --offline` because the tracked `node_modules` contents did not match the lockfile; tracked dependency files were restored after testing to leave unrelated files unchanged. The new tests verify direct versus indirect impact with citations, rejection of fabricated affected items, no-model insufficient-evidence behavior, zero parse/blob/embedding work for an unchanged sync, content-hash embedding reuse, changed/new/deleted index contents, memory staleness and unchanged-memory provenance, sync 409, and ownership enforcement. Docker rebuilt the backend, and `/health` returned HTTP 200.

### 2026-09-24 - Phase 21 architecture explanation

**Prompt:** Implement a versioned architecture prompt using `inspect_repository` metadata; route `ARCHITECTURE_EXPLANATION` directly to inspection and the selected model; add the authenticated `GET /repositories/{id}/architecture` endpoint and MockProvider tests. Keep comparison, other endpoints, and frontend out of scope.

**AI tool:** Codex

**Summary of generated output:** Added the architecture prompt, direct inspected-metadata controller path, selected-model invocation, deterministic response-field projection, the authenticated endpoint, and fixture-based tests. The inspection tool now recognizes FastAPI imports in stored Python source as well as dependency manifests.

**Modified/rejected:** The existing `ArchitectureSummary` does not contain database-layer or frontend/backend boundary details for the small fixture. Those response fields remain unset unless the tool reports a corresponding top-level folder. Model-provided factual fields are replaced by values derived from the inspected summary so unsupported claims cannot enter the response.

**Resulting module/commit:** `backend/app/agent/prompts/v1/architecture.md`, `backend/app/agent/controller.py`, `backend/app/api/routes/analysis.py`, `backend/app/tools/repository_tools.py`, and `backend/tests/test_architecture.py`. Changes were left uncommitted.

**Test result:** The full backend suite passed with 260 passed and 2 skipped. The skipped tests are opt-in PostgreSQL/pgvector integration tests requiring `PRISM_TEST_POSTGRES_URL`. The existing frontend Vitest test passed after `npm ci --offline` restored local dependencies. No tracked frontend files changed. `docker compose up -d --build backend` rebuilt the image and started the backend container with PostgreSQL healthy.

### 2026-09-25 - Phase 22 model comparison

**Prompt:** Implement explicit Compare Models using one repository Q&A EvidenceContext and identical prompts for Model A and Model B, validate each response independently, persist both executions under one AgentRun, and expose authenticated `POST /repositories/{id}/compare-models`. Return both errors on total failure and preserve a successful peer when the other fails. Add MockProvider tests; keep the frontend and normal single-model paths unchanged.

**AI tool:** Codex

**Summary of generated output:** Added comparison orchestration through the existing memory, hybrid search, optional symbol expansion, ContextBuilder, Q&A prompt, response validation, citation validation, and trace hooks. The API returns peer results in slot order without ranking or a winner. A failed slot reports a sanitized error while the other slot continues.

**Modified/rejected:** Kept the normal single-model controller paths unchanged. The comparison path builds one context and one prompt, then invokes each configured slot in sequence so both receive identical inputs and database trace writes remain ordered.

**Resulting module/commit:** `backend/app/agent/compare.py`, `backend/app/api/routes/analysis.py`, and `backend/tests/test_model_comparison.py`. Changes were left uncommitted.

**Test result:** The full backend suite passed with 270 passed and 2 skipped. The skipped tests are opt-in PostgreSQL/pgvector integration tests requiring `PRISM_TEST_POSTGRES_URL`. The existing frontend Vitest test passed. `docker compose up -d --build backend` rebuilt and started the backend with PostgreSQL healthy.

### 2026-09-25 - Phase 23 REST API completion

**Prompt:** Complete the missing repository list, detail, index status, file tree/content, symbol, memory, finding, and agent-run/trace endpoints from PRISM_SPEC.md section 26. Add repository deletion that cascades through all existing dependent tables, and test happy paths, ownership boundaries, documented errors, and direct post-delete database counts. Keep optional code review and frontend work out of scope.

**AI tool:** Codex

**Summary of generated output:** Added authenticated repository data routes, the agent-run detail and trace routes, and a repository DELETE route using database cascades. Added response schemas for repository/index/file/memory/finding/trace data and tests for current index progress, browsing, file-reading errors, finding validation, agent trace ordering, ownership, and deletion counts.

**Modified/rejected:** The optional code-review endpoint remains for later by user direction. Supplementary-document tables are not yet present in the database schema, so the deletion test verifies their absence and directly verifies zero remaining rows in every existing dependent table from section 28.3. No supplementary-document ingestion or schema was added.

**Resulting module/commit:** `backend/app/api/routes/repository_data.py`, `backend/app/api/routes/agent_runs.py`, `backend/app/main.py`, `backend/tests/test_api_completion.py`, `README.md`, and `prompts.md`. Changes were left uncommitted.

**Test result:** The full backend suite passed with 276 passed and 2 skipped. The skipped tests are opt-in PostgreSQL/pgvector integration tests requiring `PRISM_TEST_POSTGRES_URL`. The existing frontend Vitest test passed. `docker compose up -d --build backend` rebuilt and started the backend with PostgreSQL healthy.

### 2026-09-25 - Phase 24 frontend screens A through E

**Prompt:** Implement typed frontend API hooks, protected routes, authentication, dashboard, GitHub and ZIP repository import, GitHub repository and branch selection, and indexing status from PRISM_SPEC.md section 27. Test authentication forms, dashboard states, and ZIP size rejection. Keep later workspace screens out of scope.

**AI tool:** Codex

**Summary of generated output:** Added a typed fetch client, TanStack Query hooks, React Router protected routes, React Hook Form and Zod authentication forms, a repository dashboard, ZIP upload with progress and client-side size validation, an authorized GitHub repository picker with branch selection, and a polling indexing status screen. Added the narrow GitHub branch-list route needed by the picker and configured the Vite development proxy for the real backend.

**Modified/rejected:** The backend does not yet expose an import retry endpoint, so the FAILED screen states that retry is unavailable. The workspace and other later frontend screens were not added. The two PostgreSQL/pgvector tests remain opt-in and skipped without PRISM_TEST_POSTGRES_URL.

**Resulting module/commit:** `frontend/src/api/`, `frontend/src/app/`, `frontend/src/pages/`, `frontend/src/components/common/`, frontend build configuration and dependencies, `backend/app/api/routes/github.py`, `backend/tests/test_github_integration.py`, `docker-compose.yml`, `README.md`, and `prompts.md`. Changes are uncommitted.

**Test result:** Frontend Vitest passed 5 tests and `npm run build` completed without type errors. The full backend suite passed with 277 passed and 2 skipped. The Phase 24 GitHub/API subset passed 39 tests, including branch-route authorization. `docker compose up -d --build backend` rebuilt and started the backend, and `/health` returned `{"status":"ok"}`. A local Vite dev server proxied `/api/health` to the backend and returned the same result.

### 2026-09-25 - Phase 25 repository workspace and connected screens

**Prompt:** Build PRISM_SPEC.md section 27 Screens F, G, H, and K using the existing backend API: a three-pane repository workspace with file and symbol browsing, four analysis tabs, evidence file viewing, Model A/B selection, explicit Compare Models, Agent Trace details, Repository Memory, saved Findings, and GitHub connection settings. Give each workspace panel its own loading, empty, and error behavior. Add frontend tests for each analysis result, evidence navigation, comparison, and trace ordering; keep backend changes out of scope.

**AI tool:** Codex

**Summary of generated output:** Extended the typed API client and TanStack Query hooks; added protected workspace, memory, findings, and settings routes; built repository tree, analysis, evidence, and trace panels; rendered the four structured analysis responses and side-by-side peer comparison; added Save Finding for flow and impact results; resolved current-index evidence links for memory and findings while marking stale IDs without current details. Cleared cached repository data on login and sign-out so it cannot carry across accounts.

**Modified/rejected:** No backend endpoint or schema was changed. The workspace uses the agent-run IDs, tool timestamps, and evidence resolver supplied by the preceding branch patches. The optional code-review UI and later evaluation work remain out of scope. A live authenticated browser walkthrough was not performed in this phase.

**Resulting module/commit:** `frontend/src/api/`, `frontend/src/app/routes.tsx`, `frontend/src/components/`, `frontend/src/pages/`, `frontend/src/styles.css`, `README.md`, and `prompts.md`. Changes are uncommitted.

**Test result:** Frontend Vitest passed 20 tests, including all previous tests and Phase 25 analysis, evidence, trace, memory, findings, and cache-isolation cases. `npm run build` passed without type errors. The unchanged full backend suite passed with 278 passed and 2 skipped; the skipped tests require `PRISM_TEST_POSTGRES_URL`. `docker compose up -d --build backend` applied the preceding backend patches to the local service, and `/health` returned `{"status":"ok"}` after startup.

### 2026-09-25 - Phase 26 deterministic evaluation and demo repository, pending full-suite verification

**Prompt:** Consolidate a full-stack demo repository, record 20-30 ground-truth questions, run deterministic ingestion/retrieval/grounding evaluation with thresholds, measure core-logic coverage, and update the development log and README only with observed results. No new product feature is in scope.

**AI tool:** Codex

**Summary of generated output:** Added a coherent FastAPI, SQLAlchemy, PostgreSQL-ready, JWT-protected CRUD backend and React frontend under `backend/tests/fixtures/demo_repo/`, with its own API/authorization tests. Added 25 recorded questions, an offline evaluation runner using Prism's real ingestion, retrieval, and bounded controller with deterministic hash embeddings and `MockProvider`, a JSON report, and adversarial threshold tests. Corrected two grounding defects exposed by the benchmark: incompatible citations in deterministic flow fallback and false `NONE` evidence quality when a queried exact symbol is present inside a merged chunk.

**Modified/rejected:** The original smaller fixtures remain for their established regression tests. No new product capability or LLM judge was added. The benchmark uses deterministic local hash embeddings, so its retrieval metrics are not a measurement of the production `BAAI/bge-small-en-v1.5` model. The full backend suite and frontend Vitest could not be rerun with normal temporary-directory/process permissions after automatic approval review reported a usage limit. README remains at Phase 25 status pending that verification.

**Resulting module/commit:** `backend/tests/fixtures/demo_repo/`, `backend/tests/eval/`, `backend/app/agent/investigations/flow_trace.py`, `backend/app/evidence/quality.py`, `backend/tests/test_context_builder.py`, `README.md`, and `prompts.md`. Changes are uncommitted.

**Test result:** The 25-question evaluation completed with an index in `READY`, 29 indexed files, 73 symbols, and 277 relationships. Hit@12, retrieval file/symbol recall, response file/symbol recall, citation validity, grounded-response rate, direct-impact recall/precision, indirect-impact recall, and architecture metadata checks each measured 100%; ordered flow-step recall was 93.33%, step-order correctness 100%, indirect-impact precision 90%, and invalid-reference rate 0%. The evaluation threshold and demo API tests passed (6 tests), as did 248 backend tests with 2 opt-in PostgreSQL skips in the core coverage run. Core coverage was 92.07% (2,902 statements, 230 missed). Two non-temp tests from the excluded flow/ZIP files also passed. The demo frontend TypeScript check passed; a pre-proxy Vite build passed, but the final Vite build and the existing frontend Vitest run were blocked by `esbuild` process `EPERM` in the sandbox. Full-suite temporary-directory tests remain unverified in this turn.

### 2026-09-26 - Phase 26 verification completion and Phase 27 security review

**Prompt:** Review every section 28.1 threat and section 28.3 privacy guarantee, add or reference automated mitigation tests, fix discovered security gaps, verify bounded evidence and deletion/isolation, write SECURITY_REVIEW.md, and run all prior tests. No new product feature is in scope.

**AI tool:** Codex

**Summary of generated output:** Added 17 security cases covering all registered tools and repository routes, comment injection through real Q&A prompts, synthetic secret/binary exclusion from every stored table and model message, both model slots' bounded payloads, similarly named repository isolation, nested Zip Slip and symlink paths, highly compressed archive size rejection, credential-key redaction, persisted-table inventory, and an AST check for SQL interpolation. Added escaped-content frontend XSS coverage and extended DELETE counts to messages and legacy memory_items. Documented the threat-to-test mapping and actual privacy-policy table inventory.

**Modified/rejected:** Fixed web-tool execution to enforce repository ownership and file reading to reject secret filenames even in artificially seeded rows. Kept the existing ZIP hard limits; no new compression-ratio policy, product feature, or migration was introduced. The blocked Phase 26 verification is now complete: all temporary-directory tests, evaluation thresholds, demo API tests, and both frontend builds pass. The sandbox-created Phase 26 temporary directory was removed. Supplementary-document tables and installation disconnect remain unimplemented and are explicitly identified in SECURITY_REVIEW.md.

**Resulting module/commit:** `backend/app/plugins/web_search/tool.py`, `backend/app/plugins/file_reading/tool.py`, `backend/tests/test_security_review.py`, `backend/tests/test_web_plugin.py`, `backend/tests/test_api_completion.py`, frontend XSS test, `backend/SECURITY_REVIEW.md`, evaluation coverage reports, `README.md`, and `prompts.md`. Changes are uncommitted.

**Test result:** The complete backend suite passed with 301 passed and 2 skipped. The skips are opt-in PostgreSQL/pgvector tests requiring PRISM_TEST_POSTGRES_URL. All 17 Phase 27 security cases, bounded-payload checks for both slots, cross-repository isolation, and the expanded real DELETE cascade test passed. Frontend Vitest passed 21 tests; main and demo frontend production builds passed. Full core-module coverage measured 92.52% (2,902 statements, 217 missed), superseding Phase 26's limited-subset coverage report. The backend container was rebuilt and `/health` returned `{"status":"ok"}` after startup.
