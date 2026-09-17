import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.github.client import GitHubClient
from app.github.errors import GitHubApiError, GitHubInstallationRevoked
from app.models.github_installation import (
    GitHubInstallation,
    GitHubInstallationStatus,
)
from app.models.repository import Repository, RepositoryAccessStatus
from app.models.user import User

router = APIRouter(prefix="/github", tags=["github"])
_CLIENTS: dict[tuple[str | None, str], GitHubClient] = {}


def get_github_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> GitHubClient:
    cache_key = (settings.github_app_id, settings.github_app_private_key_path)
    if cache_key not in _CLIENTS:
        _CLIENTS[cache_key] = GitHubClient(settings)
    return _CLIENTS[cache_key]


class InstallUrlResponse(BaseModel):
    url: str


class InstallationResponse(BaseModel):
    id: uuid.UUID
    installation_id: int
    account_login: str
    status: GitHubInstallationStatus


@router.get("/install-url", response_model=InstallUrlResponse)
async def install_url(
    current_user: Annotated[User, Depends(get_current_user)],
    client: Annotated[GitHubClient, Depends(get_github_client)],
) -> InstallUrlResponse:
    del current_user
    app_metadata = await client.get_app()
    html_url = app_metadata.get("html_url")
    if not isinstance(html_url, str) or not html_url.startswith("https://github.com/apps/"):
        raise HTTPException(status_code=502, detail="GitHub App metadata was invalid")
    return InstallUrlResponse(url=f"{html_url.rstrip('/')}/installations/new")


@router.get("/callback", response_class=RedirectResponse)
async def installation_callback(
    installation_id: Annotated[int, Query(gt=0)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    client: Annotated[GitHubClient, Depends(get_github_client)],
    setup_action: str | None = None,
) -> RedirectResponse:
    del setup_action
    try:
        await client.get_installation_token(installation_id)
        metadata = await client.get_installation(installation_id)
    except GitHubInstallationRevoked as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except GitHubApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    account = metadata.get("account") or {}
    account_login = account.get("login")
    if not isinstance(account_login, str) or not account_login:
        raise HTTPException(status_code=502, detail="GitHub installation metadata was invalid")

    installation = await db.scalar(
        select(GitHubInstallation).where(
            GitHubInstallation.installation_id == installation_id
        )
    )
    if installation is not None and installation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="GitHub installation belongs to another user")
    if installation is None:
        installation = GitHubInstallation(
            user_id=current_user.id,
            installation_id=installation_id,
            account_login=account_login,
            status=GitHubInstallationStatus.ACTIVE,
        )
        db.add(installation)
    else:
        installation.account_login = account_login
        installation.status = GitHubInstallationStatus.ACTIVE
    await db.commit()
    return RedirectResponse(url="/?github=connected", status_code=302)


@router.get("/installations", response_model=list[InstallationResponse])
async def list_installations(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[InstallationResponse]:
    rows = await db.scalars(
        select(GitHubInstallation)
        .where(GitHubInstallation.user_id == current_user.id)
        .order_by(GitHubInstallation.created_at)
    )
    return [InstallationResponse.model_validate(row, from_attributes=True) for row in rows]


@router.get("/installations/{installation_id}/repositories")
async def list_installation_repositories(
    installation_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    client: Annotated[GitHubClient, Depends(get_github_client)],
) -> list[dict[str, Any]]:
    installation = await db.get(GitHubInstallation, installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="GitHub installation not found")
    if installation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="GitHub installation access denied")
    try:
        repositories = await client.list_repositories(installation.installation_id)
    except GitHubInstallationRevoked as exc:
        installation.status = GitHubInstallationStatus.REVOKED
        await db.execute(
            update(Repository)
            .where(Repository.github_installation_id == installation.id)
            .values(access_status=RepositoryAccessStatus.ACCESS_LOST)
        )
        await db.commit()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except GitHubApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    fields = ("id", "name", "full_name", "default_branch", "private")
    return [{field: repository.get(field) for field in fields} for repository in repositories]
