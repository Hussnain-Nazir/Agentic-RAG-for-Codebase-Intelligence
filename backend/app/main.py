from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.analysis import router as analysis_router
from app.api.routes.auth import router as auth_router
from app.api.routes.github import close_github_clients, router as github_router
from app.api.routes.models import router as models_router
from app.api.routes.repositories import router as repositories_router
from app.auth.security import require_jwt_secret
from app.config import get_settings


def create_app() -> FastAPI:
    """Create and configure the Prism FastAPI application."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings_dependency = app.dependency_overrides.get(get_settings, get_settings)
        require_jwt_secret(settings_dependency().jwt_secret)
        try:
            yield
        finally:
            await close_github_clients()

    app = FastAPI(title="Prism", lifespan=lifespan)
    app.include_router(analysis_router)
    app.include_router(auth_router)
    app.include_router(github_router)
    app.include_router(models_router)
    app.include_router(repositories_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
