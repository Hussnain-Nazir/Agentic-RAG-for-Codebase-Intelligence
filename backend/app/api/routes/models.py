from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.models.user import User

router = APIRouter(prefix="/models", tags=["models"])


class ModelNameResponse(BaseModel):
    name: str | None


class ModelsConfigResponse(BaseModel):
    model_a: ModelNameResponse
    model_b: ModelNameResponse


@router.get("/config", response_model=ModelsConfigResponse)
async def models_config(
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ModelsConfigResponse:
    del current_user
    return ModelsConfigResponse(
        model_a=ModelNameResponse(name=settings.model_a_name),
        model_b=ModelNameResponse(name=settings.model_b_name),
    )
