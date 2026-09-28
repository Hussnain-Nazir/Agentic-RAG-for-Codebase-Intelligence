from sqlalchemy import select
from sqlalchemy.orm import Session

from demo_app.models import Item, User


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def select_items_for_user(db: Session, user_id: int) -> list[Item]:
    return list(db.scalars(select(Item).where(Item.owner_id == user_id).order_by(Item.id)))


def get_item(db: Session, item_id: int) -> Item | None:
    return db.get(Item, item_id)


def insert_item(db: Session, user_id: int, title: str) -> Item:
    item = Item(owner_id=user_id, title=title)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def save_item_changes(db: Session, item: Item, title: str) -> Item:
    item.title = title
    db.commit()
    db.refresh(item)
    return item


def remove_item(db: Session, item: Item) -> None:
    db.delete(item)
    db.commit()
