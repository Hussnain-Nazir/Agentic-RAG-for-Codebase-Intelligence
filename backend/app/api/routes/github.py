import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.github.client import GitHubClient
from app.github.errors import GitHubAccessLost, GitHubApiError, GitHubInstallationRevoked, GitHubRateLimited
from app.models.github_installation import (
    GitHubInstallation,
    GitHubInstallationStatus,
)
from app.models.github_installation_attempt import GitHubInstallationAttempt
from app.models.repository import Repository, RepositoryAccessStatus
from app.models.user import User

router = APIRouter(prefix="/github", tags=["github"])
_CLIENTS: dict[tuple[str | None, str, str | None], GitHubClient] = {}
INSTALLATION_STATE_TTL = timedelta(minutes=10)


def get_github_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> GitHubClient:
    cache_key = (
        settings.github_app_id,
        settings.github_app_private_key_path,
        settings.github_client_id,
    )
    if cache_key not in _CLIENTS:
        _CLIENTS[cache_key] = GitHubClient(settings)
    return _CLIENTS[cache_key]


async def close_github_clients() -> None:
    for client in _CLIENTS.values():
        await client.aclose()
    _CLIENTS.clear()


class InstallUrlResponse(BaseModel):
    url: str


class InstallationResponse(BaseModel):
    id: uuid.UUID
    installation_id: int
    account_login: str
    status: GitHubInstallationStatus


class BranchResponse(BaseModel):
    name: str


@router.get("/install-url", response_model=InstallUrlResponse)
async def install_url(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    client: Annotated[GitHubClient, Depends(get_github_client)],
) -> InstallUrlResponse:
    if not client.user_authorization_configured:
        raise HTTPException(
            status_code=503,
            detail="GitHub user authorization is not configured",
        )
    try:
        app_metadata = await client.get_app()
    except GitHubApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    html_url = app_metadata.get("html_url")
    if not isinstance(html_url, str) or not html_url.startswith("https://github.com/apps/"):
        raise HTTPException(status_code=502, detail="GitHub App metadata was invalid")
    state = secrets.token_urlsafe(32)
    db.add(
        GitHubInstallationAttempt(
            user_id=current_user.id,
            state_hash=hashlib.sha256(state.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(UTC) + INSTALLATION_STATE_TTL,
        )
    )
    await db.commit()
    return InstallUrlResponse(
        url=(
            f"{html_url.rstrip('/')}/installations/new?"
            f"{urlencode({'state': state})}"
        )
    )


@router.get("/callback", response_class=RedirectResponse)
async def installation_callback(
    installation_id: Annotated[int, Query(gt=0)],
    db: Annotated[AsyncSession, Depends(get_db)],
    client: Annotated[GitHubClient, Depends(get_github_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    code: str | None = None,
    state: str | None = None,
    setup_action: str | None = None,
) -> RedirectResponse:
    del setup_action
    if not code or not state:
        raise HTTPException(
            status_code=400,
            detail="GitHub callback is missing code or state",
        )

    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    attempt = await db.scalar(
        select(GitHubInstallationAttempt)
        .where(GitHubInstallationAttempt.state_hash == state_hash)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if attempt is None or attempt.consumed_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or reused GitHub state")
    expires_at = attempt.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        raise HTTPException(status_code=400, detail="GitHub state has expired")

    try:
        user_access_token = await client.exchange_user_code(code)
        user_installations = await client.list_user_installations(user_access_token)
        metadata = next(
            (
                item
                for item in user_installations
                if item.get("id") == installation_id
            ),
            None,
        )
        if metadata is None:
            raise HTTPException(
                status_code=403,
                detail="GitHub installation is not accessible to the authorized user",
            )
        await client.get_installation_token(installation_id)
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
    if installation is not None and installation.user_id != attempt.user_id:
        raise HTTPException(status_code=403, detail="GitHub installation belongs to another user")
    if installation is None:
        installation = GitHubInstallation(
            user_id=attempt.user_id,
            installation_id=installation_id,
            account_login=account_login,
            status=GitHubInstallationStatus.ACTIVE,
        )
        db.add(installation)
    else:
        installation.account_login = account_login
        installation.status = GitHubInstallationStatus.ACTIVE
    attempt.consumed_at = now
    await db.commit()
    return RedirectResponse(url=settings.github_callback_success_url, status_code=302)


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


@router.get(
    "/installations/{installation_id}/repositories/{repository_id}/branches",
    response_model=list[BranchResponse],
)
async def list_installation_repository_branches(
    installation_id: uuid.UUID,
    repository_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    client: Annotated[GitHubClient, Depends(get_github_client)],
) -> list[BranchResponse]:
    installation = await db.get(GitHubInstallation, installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="GitHub installation not found")
    if installation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="GitHub installation access denied")
    try:
        repositories = await client.list_repositories(installation.installation_id)
        if not any(item.get("id") == repository_id for item in repositories):
            raise HTTPException(status_code=404, detail="GitHub repository not found")
        branches = await client.list_branches(installation.installation_id, repository_id)
    except GitHubInstallationRevoked as exc:
        installation.status = GitHubInstallationStatus.REVOKED
        await db.execute(
            update(Repository)
            .where(Repository.github_installation_id == installation.id)
            .values(access_status=RepositoryAccessStatus.ACCESS_LOST)
        )
        await db.commit()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except GitHubAccessLost as exc:
        await db.execute(
            update(Repository)
            .where(
                Repository.github_installation_id == installation.id,
                Repository.github_repo_id == repository_id,
            )
            .values(access_status=RepositoryAccessStatus.ACCESS_LOST)
        )
        await db.commit()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except GitHubRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except GitHubApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [BranchResponse(name=item["name"]) for item in branches if isinstance(item.get("name"), str)]
