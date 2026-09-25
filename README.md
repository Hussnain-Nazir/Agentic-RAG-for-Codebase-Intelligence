# Prism - Agentic RAG for Codebase Intelligence

Prism is an agentic RAG platform for understanding, navigating, tracing, and analyzing software repositories. It combines deterministic repository structure, hybrid retrieval, bounded tool execution, persistent memory, and evidence-grounded model reasoning to answer repository-level questions without sending an entire repository to a model.

Phase 17 replaces the scaffold with Prism's single bounded AgentController. It performs deterministic task classification, zero-model direct routing, hook-wrapped tool execution, repository and session authorization, memory retrieval, evidence-context construction, conditional external search, selected-slot model invocation, one bounded repair, citation validation, eligible memory writes, and complete trace persistence.

Phase 18 completes the backend Codebase Q&A vertical slice. Repository questions use a versioned, injection-aware runtime prompt, the selected model slot, schema and citation validation, and the authenticated `POST /repositories/{id}/ask` endpoint. Requests with no repository evidence return 422 without a model call, and answers whose citations are all invalid are downgraded and rejected as ungrounded.

Phase 19 completes the backend multi-file flow-tracing slice. A bounded feature investigation follows exact symbols through stored references and related evidence, records every tool observation, preserves unresolved transitions rather than fabricating links, and serves validated results through `POST /repositories/{id}/flow-trace`.

Phase 20 adds backend change-impact analysis and GitHub incremental synchronization. Change-impact requests use bounded symbol, reference, related-file, and hybrid-search tools to separate evidenced definitions from likely downstream consumers at `POST /repositories/{id}/change-impact`. `POST /repositories/{id}/sync` creates a new index version, copies unchanged indexed rows without parsing or embedding them again, processes changed and new files through the shared ingestion stages, excludes deleted files from the new version, and invalidates memory tied to changed or deleted evidence.

## Local setup

Prerequisites: Python 3.11 or newer, Node.js 20 or newer, and Docker with Docker Compose.

1. Copy `.env.example` to `.env` and keep all credentials local.
2. Start all three services with `docker compose up --build`.
3. Open the frontend at `http://localhost:5173`.
4. Check the backend at `http://localhost:8000/health`.

For web-search development, set `SERPAPI_API_KEY` in `.env`. The key is server-side only and must never be placed in frontend configuration, logs, cached web-source rows, or model context. Prism calls SerpAPI only when the later agent-classification phase explicitly selects the external-document task path.

For direct development, install `backend/requirements.txt` and run `uvicorn app.main:app --reload` from `backend/`. Run `npm install` followed by `npm run dev` from `frontend/`.

## [MANUAL] GitHub App setup

1. Create a GitHub App with read-only Contents and Metadata permissions. Disable webhooks unless a later phase explicitly adds them.
2. Enable **Request user authorization (OAuth) during installation**. Set the callback URL to the public backend URL ending in `/github/callback`, for example `https://<tunnel-host>/github/callback`.
3. Generate a client secret and private key. Put the PEM file under `run/secrets/` and configure `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_CLIENT_ID`, and `GITHUB_CLIENT_SECRET` in `.env`.
4. Start Prism with `docker compose up -d --build`. For localhost.run, keep `ssh -R 80:localhost:8000 nokey@localhost.run` running and confirm `https://<tunnel-host>/health` returns `{"status":"ok"}`.
5. Log in to Prism, authorize Swagger with the Prism bearer token, call `GET /github/install-url`, and open the returned state-bearing URL in the browser. After installation, GitHub returns through the callback and Prism redirects to the frontend.
6. Call `GET /github/installations` with the Prism bearer token. Use the returned Prism installation UUID, not GitHub's numeric installation ID, in `GET /github/installations/{installation_id}/repositories`.

Installation state is short-lived, single-use, and bound to the authenticated Prism user who requested the install URL. The callback verifies through a GitHub user access token that the installation is accessible to the GitHub user before persisting it. User and installation tokens are not stored. Do not place the private key, client secret, installation tokens, or user tokens in the frontend, repository, logs, or model context.

Status: Phase 22 complete
