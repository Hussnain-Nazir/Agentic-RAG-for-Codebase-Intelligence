# Prism - Agentic RAG for Codebase Intelligence

Prism is an agentic RAG platform for understanding, navigating, tracing, and analyzing software repositories. It combines deterministic repository structure, hybrid retrieval, bounded tool execution, persistent memory, and evidence-grounded model reasoning to answer repository-level questions without sending an entire repository to a model.

Phase 4 completes the Week 5 scaffold milestone from `PRISM_SPEC.md`: the runnable foundation now includes model, evidence, tool-registry, memory, tracing, and minimal controller interfaces with a mocked end-to-end path. Real retrieval, concrete tools, task routing, bounded iteration, and full memory behavior remain assigned to later phases.

## Local setup

Prerequisites: Python 3.11 or newer, Node.js 20 or newer, and Docker with Docker Compose.

1. Copy `.env.example` to `.env` and keep all credentials local.
2. Start all three services with `docker compose up --build`.
3. Open the frontend at `http://localhost:5173`.
4. Check the backend at `http://localhost:8000/health`.

For direct development, install `backend/requirements.txt` and run `uvicorn app.main:app --reload` from `backend/`. Run `npm install` followed by `npm run dev` from `frontend/`.

Status: Phase 5 complete
