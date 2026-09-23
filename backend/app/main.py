from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.auth.security import require_jwt_secret
from app.config import get_settings


def create_app() -> FastAPI:
    """Create and configure the Prism FastAPI application."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings_dependency = app.dependency_overrides.get(get_settings, get_settings)
        require_jwt_secret(settings_dependency().jwt_secret)
        yield

    app = FastAPI(title="Prism", lifespan=lifespan)
    app.include_router(auth_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
