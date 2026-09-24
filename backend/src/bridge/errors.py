"""Error bodies (docs/spec/08 Tenancy error semantics): 404 for non-members and non-parties, 403 for members or
parties lacking a role or precondition, 402 for plan limits. Every error has a stable machine ``code``."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message, **extra})


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError(404, "not_found", message)


def forbidden(code: str = "forbidden", message: str = "You do not have access to this action.") -> ApiError:
    return ApiError(403, code, message)
