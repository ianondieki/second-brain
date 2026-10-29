"""Column type helpers: Postgres enums named after the Python enum, citext and pgvector (reflected by Alembic)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT


def pg_enum(enum: type[StrEnum], name: str) -> Enum:
    """A native Postgres enum storing the member values (lower-case strings)."""
    return Enum(enum, name=name, values_callable=lambda e: [m.value for m in e], validate_strings=True)


def pg_enum_array(enum: type[StrEnum], name: str) -> ARRAY[Any]:
    return ARRAY(pg_enum(enum, name))


def CIText() -> CITEXT:
    """Postgres ``citext`` (case-insensitive text) for emails, slugs and handles."""
    return CITEXT()


__all__ = ["CIText", "Vector", "pg_enum", "pg_enum_array"]
