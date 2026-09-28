# Demo Repository

This small application has a React frontend and a FastAPI backend. Users register,
log in for a JWT, and manage their own items. A user belongs to one organization;
changing that relationship is an impact-analysis exercise. The backend uses
SQLAlchemy and a PostgreSQL `DATABASE_URL`. Tests use isolated SQLite storage.

Run the backend with `DATABASE_URL` and `JWT_SECRET` set, install
`backend/requirements.txt`, run `python -m demo_app.seed` to create the tables
and an Example organization, then run `uvicorn demo_app.main:app` from `backend/`.
Run its tests with `pytest backend/tests` from this directory. Run the frontend
with `npm install && npm run dev` from `frontend/`. Vite proxies `/api` to the
backend at `http://localhost:8000`.

The files under `backend/` and `frontend/` are the indexed demo source for
Prism's deterministic evaluation and final demonstration.
