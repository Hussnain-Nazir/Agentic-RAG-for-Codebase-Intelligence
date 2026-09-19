import uuid
from typing import Any

from sqlalchemy import JSON, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UUIDList(TypeDecorator[list[str]]):
    """PostgreSQL UUID array with a JSON representation for SQLite tests."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Uuid(as_uuid=True)))
        return dialect.type_descriptor(JSON())

    def process_bind_param(
        self,
        value: list[str] | None,
        dialect: Dialect,
    ) -> list[Any] | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return [uuid.UUID(str(item)) for item in value]
        return [str(item) for item in value]

    def process_result_value(
        self,
        value: list[Any] | None,
        dialect: Dialect,
    ) -> list[str] | None:
        del dialect
        if value is None:
            return None
        return [str(item) for item in value]
