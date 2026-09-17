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
