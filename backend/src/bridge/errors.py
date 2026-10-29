"""Error bodies (docs/spec/08 Tenancy error semantics): 404 for non-members and non-parties, 403 for members or
parties lacking a role or precondition, 402 for plan limits. Every error has a stable machine ``code``.

One shape for every error the API answers (REQ-FND-01, P16-E1): ``{"detail": {"code", "message", ...}}``
(``ApiErrorBody``). FastAPI's request-validation 422 (``{"detail": [{"loc", "msg", "type"}, ...]}``) is the one
documented exception. ``install`` makes the framework's own refusals (an unknown path, a method a path does not take,
a body it cannot parse) and an unexpected failure (500) answer in the same shape: an unknown path's 404 is then the
same body as a hidden resource's, so nothing tells the two apart. The 422 never quotes the value it refused (a
password, a code, free text; REQ-SEC-03).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from http import HTTPStatus
from typing import Any, Final

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message, **extra})


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError(404, "not_found", message)


def forbidden(code: str = "forbidden", message: str = "You do not have access to this action.") -> ApiError:
    return ApiError(403, code, message)


class ApiErrorDetail(BaseModel):
    """``code`` is stable and machine-readable; ``message`` is plain English for people. Extra keys per code (for
    example the 402 ``upgrade`` path)."""

    model_config = ConfigDict(extra="allow")

    code: str
    message: str


class ApiErrorBody(BaseModel):
    detail: ApiErrorDetail | list[dict[str, Any]]  # a list only for request-validation errors (FastAPI's 422)


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ApiErrorBody} for status in (400, 401, 402, 403, 404, 409, 422, 429)
}


# FastAPI documents a response model under the route's own media type, so a route whose success is not JSON (an HTML
# page) lists its errors with this schema instead: the error body is JSON whatever the route returns.
ERROR_BODY_SCHEMA: Final[dict[str, str]] = {"$ref": "#/components/schemas/ApiErrorBody"}


def json_errors(*statuses: int | str) -> dict[int | str, dict[str, Any]]:
    return {status: {"content": {"application/json": {"schema": dict(ERROR_BODY_SCHEMA)}}} for status in statuses}


# The framework's refusals, in the API's words (the web app maps codes to its own text; these are for API clients).
FRAMEWORK_MESSAGES: Final[Mapping[int, str]] = {
    404: "Not found.",
    405: "This method is not allowed here.",
}
INTERNAL_ERROR: Final = {
    "code": "internal_error",
    "message": "Something went wrong on our side. Try again in a few minutes.",  # [[COPY-REVIEW]]
}


def error_detail(status_code: int, detail: Any) -> dict[str, Any]:
    """``detail`` as the API's error detail: an ``ApiError``'s as it is; anything else (the framework's string, such
    as Starlette's "Not Found") gets a stable code from the status and a sentence. Never the request's own text."""
    if isinstance(detail, Mapping) and isinstance(detail.get("code"), str) and isinstance(detail.get("message"), str):
        return dict(detail)
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = "Error"
    code = re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_") or "error"
    message = FRAMEWORK_MESSAGES.get(status_code)
    if message is None:
        text = detail.strip() if isinstance(detail, str) else ""
        message = f"{text.rstrip('.')}." if text else f"{phrase}."
    return {"code": code, "message": message}


async def http_error(request: Request, exc: Exception) -> Response:
    """FastAPI's handler for ``HTTPException`` (``ApiError`` included), with the detail in the API's shape."""
    if not isinstance(exc, StarletteHTTPException):  # registered for HTTPException only
        raise exc
    headers = getattr(exc, "headers", None)
    if exc.status_code < 200 or exc.status_code in (204, 205, 304):  # no body allowed
        return Response(status_code=exc.status_code, headers=headers)
    return JSONResponse({"detail": error_detail(exc.status_code, exc.detail)}, exc.status_code, headers=headers)


# What a request-validation error keeps: where, what and why. Pydantic's ``input`` echoes the value sent (a password,
# a code, free text) and ``ctx``/``url`` add nothing a client uses (REQ-SEC-03, P16-E1).
VALIDATION_KEYS: Final = ("loc", "msg", "type")


async def validation_error(request: Request, exc: Exception) -> Response:
    """FastAPI's 422 (``{"detail": [{"loc", "msg", "type"}, ...]}``) without the value each error echoes."""
    if not isinstance(exc, RequestValidationError):  # registered for RequestValidationError only
        raise exc
    errors = [{key: error[key] for key in VALIDATION_KEYS if key in error} for error in exc.errors()]
    return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)


def install(
    app: FastAPI,
    *,
    headers: Mapping[str, str],
    per_request: Callable[[Request], Mapping[str, str]] | None = None,
) -> None:
    """Every error in one shape: the framework's HTTP errors, and an unexpected exception as a 500 with a fixed body
    (never the exception's text; Starlette still raises it after answering, so it is logged). ``headers``, and
    ``per_request``'s for the request that failed, go on the 500, which the app's middlewares never see."""

    async def server_error(request: Request, exc: Exception) -> Response:
        extra = per_request(request) if per_request is not None else {}
        return JSONResponse({"detail": INTERNAL_ERROR}, status_code=500, headers={**headers, **extra})

    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, server_error)
