from fastapi import APIRouter

from auth.security import get_current_user
from db import create_session

router = APIRouter(prefix="/items")


@router.get("")
def list_items(token: str) -> list[dict[str, str]]:
    current_user = get_current_user(token)
    create_session()
    return [{"name": "sample", "owner": current_user["email"]}]


@router.post("")
def create_item(name: str, token: str) -> dict[str, str]:
    current_user = get_current_user(token)
    return {"name": name, "owner": current_user["email"]}
