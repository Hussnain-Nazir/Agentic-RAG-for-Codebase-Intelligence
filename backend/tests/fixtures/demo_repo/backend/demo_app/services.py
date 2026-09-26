from fastapi import HTTPException
from sqlalchemy.orm import Session

from demo_app.models import Item, Organization, User
from demo_app.repositories import (
    insert_item, remove_item, get_item, get_user_by_email,
    select_items_for_user, save_item_changes,
)
from demo_app.security import hash_password, verify_password


def register_user(db: Session, email: str, password: str, organization_id: int) -> User:
    if get_user_by_email(db, email):
        raise HTTPException(status_code=409, detail="Email already registered")
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    user = User(email=email.lower(), hashed_password=hash_password(password), organization_id=organization_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user


def list_user_items(db: Session, current_user: User) -> list[Item]:
    return select_items_for_user(db, current_user.id)


def create_user_item(db: Session, current_user: User, title: str) -> Item:
    return insert_item(db, current_user.id, title)


def require_item_owner(db: Session, item_id: int, current_user: User) -> Item:
    item = get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Item access denied")
    return item


def update_user_item(db: Session, item_id: int, current_user: User, title: str) -> Item:
    item = require_item_owner(db, item_id, current_user)
    return save_item_changes(db, item, title)


def delete_user_item(db: Session, item_id: int, current_user: User) -> None:
    item = require_item_owner(db, item_id, current_user)
    remove_item(db, item)
