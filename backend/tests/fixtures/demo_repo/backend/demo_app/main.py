import os

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from demo_app.db import make_session_factory
from demo_app.routes.auth import router as auth_router
from demo_app.routes.items import router as items_router


def create_app(
    session_factory: sessionmaker[Session] | None = None,
    jwt_secret: str | None = None,
) -> FastAPI:
    app = FastAPI(title="Prism demo repository")
    app.state.session_factory = session_factory or make_session_factory()
    app.state.jwt_secret = jwt_secret or os.environ["JWT_SECRET"]
    app.include_router(auth_router)
    app.include_router(items_router)
    return app


app = create_app() if os.getenv("DATABASE_URL") and os.getenv("JWT_SECRET") else FastAPI(title="Prism demo repository")
