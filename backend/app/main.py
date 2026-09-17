from fastapi import FastAPI

from app.api.routes.auth import router as auth_router


def create_app() -> FastAPI:
    """Create and configure the Prism FastAPI application."""
    app = FastAPI(title="Prism")
    app.include_router(auth_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
