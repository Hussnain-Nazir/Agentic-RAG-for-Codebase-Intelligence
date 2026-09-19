# Prism - Agentic RAG for Codebase Intelligence

Prism is an agentic RAG platform for understanding, navigating, tracing, and analyzing software repositories. It combines deterministic repository structure, hybrid retrieval, bounded tool execution, persistent memory, and evidence-grounded model reasoning to answer repository-level questions without sending an entire repository to a model.

Phase 11 adds deterministic hybrid retrieval across semantic, PostgreSQL full-text lexical, and exact/fuzzy symbol signals. Scores are normalized per signal, merged with the frozen weights and exact-symbol boost, deduplicated by chunk and line overlap, merged across adjacent ranges, and expanded through bounded structural relationships. Context-budget enforcement, Evidence construction, and the full bounded controller remain assigned to later phases.

## Local setup

Prerequisites: Python 3.11 or newer, Node.js 20 or newer, and Docker with Docker Compose.

1. Copy `.env.example` to `.env` and keep all credentials local.
2. Start all three services with `docker compose up --build`.
3. Open the frontend at `http://localhost:5173`.
4. Check the backend at `http://localhost:8000/health`.

For direct development, install `backend/requirements.txt` and run `uvicorn app.main:app --reload` from `backend/`. Run `npm install` followed by `npm run dev` from `frontend/`.

## [MANUAL] GitHub App setup

1. Create a GitHub App with read-only Contents and Metadata permissions. Disable webhooks unless a later phase explicitly adds them.
2. Enable **Request user authorization (OAuth) during installation**. Set the callback URL to the public backend URL ending in `/github/callback`, for example `https://<tunnel-host>/github/callback`.
3. Generate a client secret and private key. Put the PEM file under `run/secrets/` and configure `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_CLIENT_ID`, and `GITHUB_CLIENT_SECRET` in `.env`.
4. Start Prism with `docker compose up -d --build`. For localhost.run, keep `ssh -R 80:localhost:8000 nokey@localhost.run` running and confirm `https://<tunnel-host>/health` returns `{"status":"ok"}`.
5. Log in to Prism, authorize Swagger with the Prism bearer token, call `GET /github/install-url`, and open the returned state-bearing URL in the browser. After installation, GitHub returns through the callback and Prism redirects to the frontend.
6. Call `GET /github/installations` with the Prism bearer token. Use the returned Prism installation UUID, not GitHub's numeric installation ID, in `GET /github/installations/{installation_id}/repositories`.

Installation state is short-lived, single-use, and bound to the authenticated Prism user who requested the install URL. The callback verifies through a GitHub user access token that the installation is accessible to the GitHub user before persisting it. User and installation tokens are not stored. Do not place the private key, client secret, installation tokens, or user tokens in the frontend, repository, logs, or model context.

Status: Phase 11 complete
