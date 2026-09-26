from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from demo_app.db import get_db
from demo_app.models import User
from demo_app.schemas import ItemCreate, ItemResponse, ItemUpdate
from demo_app.security import bearer, get_current_user
from demo_app.services import create_user_item, delete_user_item, list_user_items, update_user_item

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[ItemResponse])
def list_items(request: Request, db: Session = Depends(get_db), credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> list[ItemResponse]:
    current_user: User = get_current_user(request, credentials, db)
    return [ItemResponse.model_validate(item) for item in list_user_items(db, current_user)]


@router.post("", response_model=ItemResponse, status_code=201)
def create_item(payload: ItemCreate, request: Request, db: Session = Depends(get_db), credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> ItemResponse:
    current_user: User = get_current_user(request, credentials, db)
    return ItemResponse.model_validate(create_user_item(db, current_user, payload.title))


@router.put("/{item_id}", response_model=ItemResponse)
def update_item(item_id: int, payload: ItemUpdate, request: Request, db: Session = Depends(get_db), credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> ItemResponse:
    current_user: User = get_current_user(request, credentials, db)
    return ItemResponse.model_validate(update_user_item(db, item_id, current_user, payload.title))


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, request: Request, db: Session = Depends(get_db), credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> None:
    current_user: User = get_current_user(request, credentials, db)
    delete_user_item(db, item_id, current_user)
