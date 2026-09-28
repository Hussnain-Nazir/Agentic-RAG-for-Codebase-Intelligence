# Prism - Agentic RAG for Codebase Intelligence

Prism is an agentic RAG platform for understanding, navigating, tracing, and analyzing software repositories. It combines deterministic repository structure, hybrid retrieval, bounded tool execution, persistent memory, and evidence-grounded model reasoning to answer repository-level questions without sending an entire repository to a model.

Phase 17 replaces the scaffold with Prism's single bounded AgentController. It performs deterministic task classification, zero-model direct routing, hook-wrapped tool execution, repository and session authorization, memory retrieval, evidence-context construction, conditional external search, selected-slot model invocation, one bounded repair, citation validation, eligible memory writes, and complete trace persistence.

Phase 18 completes the backend Codebase Q&A vertical slice. Repository questions use a versioned, injection-aware runtime prompt, the selected model slot, schema and citation validation, and the authenticated `POST /repositories/{id}/ask` endpoint. Requests with no repository evidence return 422 without a model call, and answers whose citations are all invalid are downgraded and rejected as ungrounded.

Phase 19 completes the backend multi-file flow-tracing slice. A bounded feature investigation follows exact symbols through stored references and related evidence, records every tool observation, preserves unresolved transitions rather than fabricating links, and serves validated results through `POST /repositories/{id}/flow-trace`.

Phase 20 adds backend change-impact analysis and GitHub incremental synchronization. Change-impact requests use bounded symbol, reference, related-file, and hybrid-search tools to separate evidenced definitions from likely downstream consumers at `POST /repositories/{id}/change-impact`. `POST /repositories/{id}/sync` creates a new index version, copies unchanged indexed rows without parsing or embedding them again, processes changed and new files through the shared ingestion stages, excludes deleted files from the new version, and invalidates memory tied to changed or deleted evidence.

Phase 24 adds the first five frontend screens: authentication, dashboard, repository import by GitHub or ZIP, GitHub repository and branch selection, and indexing status. The frontend uses typed API calls and polls active index states. A repository branch-list endpoint exposes the existing GitHub client capability to the picker.

Phase 25 adds the repository workspace with file and symbol browsing, Ask, Flow Trace, Change Impact, Architecture, peer Model Comparison, evidence file viewing, and an expandable Agent Trace. Repository Memory, saved Findings, and GitHub connection settings are available from the frontend. Memory and finding evidence links resolve against the current index; stale IDs remain visible without a current file link.

## Deployment and local development

Prism runs as three services: PostgreSQL with pgvector and a persistent named volume, a FastAPI backend, and a React frontend. Compose waits for PostgreSQL health before starting the backend. The backend entrypoint verifies a database query, applies Alembic migrations, then starts Uvicorn. The frontend starts after the backend health check passes. Each service has a health check and an `unless-stopped` restart policy. No hosting provider is required; the same three services can run on any host that supports Docker Compose or equivalent services.

Prerequisites: Python 3.11 or newer, Node.js 20 or newer, and Docker with Docker Compose. Copy `.env.example` to `.env`, replace the sample `JWT_SECRET`, and keep credentials local. The sample database credentials in Compose are for local use; set separate credentials and a matching `DATABASE_URL` before staging deployment.

Environment configuration is grouped as follows:

- Database and authentication: `DATABASE_URL`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `JWT_SECRET`. Match the PostgreSQL variables to `DATABASE_URL`. Changing these variables does not reset credentials in an existing PostgreSQL volume.
- GitHub App, when used: `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_CALLBACK_SUCCESS_URL`. The private key stays in the read-only `run/secrets/` mount.
- Model peers: `MODEL_A_NAME`, `MODEL_A_BASE_URL`, `MODEL_A_API_KEY`, `MODEL_A_TIMEOUT`, and the corresponding `MODEL_B_*` variables. Configure at least one complete slot for the stack smoke test.
- Indexing and web search: `EMBEDDING_MODEL_NAME`, `WEB_SEARCH_PROVIDER`, `WEB_SEARCH_API_KEY`, `SERPAPI_API_KEY`, `MAX_ZIP_SIZE_MB`, `MAX_FILE_SIZE_MB`, `MAX_EXTRACTED_SIZE_MB`, `MAX_EXTRACTED_FILES`, `MAX_CONCURRENT_INDEX_JOBS`.

For local development, run `docker compose up -d --build`. Open the Vite frontend at `http://localhost:5173` and check the backend at `http://localhost:8000/health`. To run the backend and frontend directly, start PostgreSQL with `docker compose up -d postgres`, run `alembic upgrade head` and `uvicorn app.main:app --reload` from `backend/`, then run `npm ci` and `npm run dev` from `frontend/`. The Vite server proxies `/api` to the backend; set `VITE_DEV_API_TARGET` if it is not at `http://localhost:8000`.

For a static frontend deployment, run `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. `frontend/Dockerfile.prod` builds the Vite bundle and serves it with Nginx on `http://localhost:5173`; Nginx proxies `/api` to the backend. The default Compose file remains the development server path. The static frontend can also be built without replacing the running development service with `docker compose -f docker-compose.yml -f docker-compose.prod.yml build frontend`.

Run `python backend/scripts/smoke_test_stack.py` to build and verify the development stack end to end, or add `--production` to verify the static frontend variant. The script creates a throwaway user and fixture repository, waits for `READY`, makes one Q&A request through a configured model slot, and checks its trace. It leaves those records in the database for inspection. It does not use GitHub or web search.

For web-search development, set `SERPAPI_API_KEY` in `.env`. The key is server-side only and must never be placed in frontend configuration, logs, cached web-source rows, or model context. Prism calls SerpAPI only when the controller explicitly selects the external-document task path.

## API overview

The authenticated API covers repository import, browsing, index status, code analysis, memory, findings, agent traces, and repository deletion. See [PRISM_SPEC.md section 26](PRISM_SPEC.md#26-rest-api-specification) for the endpoint contracts and error cases. Evidence-backed code review remains optional and is not exposed yet.

## Evaluation

Phase 26 evaluation work is recorded in [the evaluation report](backend/tests/eval/report.json) and [coverage report](backend/tests/eval/COVERAGE.md). The 25-question deterministic demo-repository run measured Hit@12 at 100%, citation validity at 100%, ordered flow-step recall at 93.33%, and indirect-impact precision at 90%. The complete backend suite now passes, including the previously blocked temporary-directory tests. Core coverage is 92.52%.

## Security review

[SECURITY_REVIEW.md](backend/SECURITY_REVIEW.md) maps every section 28.1 threat and section 28.3 privacy requirement to automated checks. Phase 27 adds exhaustive route/tool ownership checks, cross-repository isolation, prompt-injection and secret-exclusion tests, ZIP edge cases, bounded model-payload checks, escaped-content XSS coverage, and extended deletion verification. Web-tool execution now checks repository ownership, and file reading also rejects secret filenames in seeded rows.

## [MANUAL] GitHub App setup

1. Create a GitHub App with read-only Contents and Metadata permissions. Disable webhooks unless a later phase explicitly adds them.
2. Enable **Request user authorization (OAuth) during installation**. Set the callback URL to the public backend URL ending in `/github/callback`, for example `https://<tunnel-host>/github/callback`.
3. Generate a client secret and private key. Put the PEM file under `run/secrets/` and configure `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_CLIENT_ID`, and `GITHUB_CLIENT_SECRET` in `.env`.
4. Start Prism with `docker compose up -d --build`. For localhost.run, keep `ssh -R 80:localhost:8000 nokey@localhost.run` running and confirm `https://<tunnel-host>/health` returns `{"status":"ok"}`.
5. Log in to Prism, authorize Swagger with the Prism bearer token, call `GET /github/install-url`, and open the returned state-bearing URL in the browser. After installation, GitHub returns through the callback and Prism redirects to the frontend.
6. Call `GET /github/installations` with the Prism bearer token. Use the returned Prism installation UUID, not GitHub's numeric installation ID, in `GET /github/installations/{installation_id}/repositories`.

Installation state is short-lived, single-use, and bound to the authenticated Prism user who requested the install URL. The callback verifies through a GitHub user access token that the installation is accessible to the GitHub user before persisting it. User and installation tokens are not stored. Do not place the private key, client secret, installation tokens, or user tokens in the frontend, repository, logs, or model context.

Status: Phase 28 complete
