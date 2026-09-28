# Repository Guidelines

## Project Structure & Module Organization

Prism is a FastAPI and React application. Backend code lives in `backend/app/`, organized by domain: `api/routes/`, `models/`, `sources/`, `ingestion/`, `github/`, `llm/`, `agent/`, `memory/`, `tools/`, and `tracing/`. Alembic migrations are in `backend/alembic/versions/`; backend tests and ZIP fixtures are in `backend/tests/`. The Vite frontend is under `frontend/`, with application code in `frontend/src/`. Treat `PRISM_SPEC.md` as the architecture and product source of truth, and record phase work in `prompts.md`.

## Build, Test, and Development Commands

- `docker compose up --build`: build and run PostgreSQL with pgvector, the backend, and the frontend.
- `docker compose config --quiet`: validate Compose configuration.
- `cd backend && pytest -p no:cacheprovider`: run all backend tests.
- `cd backend && alembic upgrade head`: apply database migrations using `DATABASE_URL`.
- `cd backend && uvicorn app.main:app --reload`: run the backend directly.
- `cd frontend && npm install && npm run dev`: install dependencies and start Vite.
- `cd frontend && npm test`: run Vitest once.
- `cd frontend && npm run build`: type-check and create the production bundle.

## Coding Style & Naming Conventions

Use four spaces in Python and two spaces in TypeScript/TSX. Follow existing type-hinting and SQLAlchemy 2.x `Mapped` patterns. Use `snake_case` for Python modules and functions, `PascalCase` for classes and Pydantic models, and `camelCase` for frontend variables. Keep routes thin and domain logic in dedicated modules. No formatter is currently enforced, so match nearby code. Do not use emojis, em dashes, or marketing language.

## Testing Guidelines

Use pytest files named `test_*.py` and Vitest files named `*.test.tsx`. Tests must be deterministic and isolated. Use SQLite or mocked transports where established; never require live GitHub, model, or web-search credentials. Add regression coverage for security boundaries, database relationships, API status codes, and source-independent ingestion behavior. Keep all prior tests passing.

## Commit & Pull Request Guidelines

History follows Conventional Commit style with scopes, for example `feat(ingestion): implement ZIP upload ingestion`. Keep commits phase-focused and use concise imperative subjects. Pull requests should summarize behavior, identify the relevant specification section, list verification commands and results, mention migrations or configuration changes, and include screenshots for user-visible frontend changes.

## Security & Architecture Constraints

Copy `.env.example` to `.env`; never commit secrets, PEM files, tokens, or credentials. Preserve the single bounded controller, PostgreSQL/pgvector storage, shared `RepositorySource` ingestion pipeline, local embeddings, hybrid retrieval, and equal Model A/Model B architecture. Do not implement later-phase or stretch-goal behavior early.
