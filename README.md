# Prism - Agentic RAG for Codebase Intelligence

Prism is an agentic RAG platform for understanding, navigating, tracing, and analyzing software repositories. It combines deterministic repository structure, hybrid retrieval, bounded tool execution, persistent memory, and evidence-grounded model reasoning to answer repository-level questions without sending an entire repository to a model.

## Local setup

Prerequisites: Python 3.11 or newer, Node.js 20 or newer, and Docker with Docker Compose.

1. Copy `.env.example` to `.env` and keep all credentials local.
2. Start all three services with `docker compose up --build`.
3. Open the frontend at `http://localhost:5173`.
4. Check the backend at `http://localhost:8000/health`.

For direct development, install `backend/requirements.txt` and run `uvicorn app.main:app --reload` from `backend/`. Run `npm install` followed by `npm run dev` from `frontend/`.

Status: Phase 2 complete
