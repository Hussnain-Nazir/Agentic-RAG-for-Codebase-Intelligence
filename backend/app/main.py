from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create and configure the Prism FastAPI application."""
    app = FastAPI(title="Prism")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
