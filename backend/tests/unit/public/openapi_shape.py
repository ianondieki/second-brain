"""A minimal check that a JSON body has exactly the shape an OpenAPI 3.1 schema (as FastAPI writes it) gives: the
public reads' contract tests (REQ-UX-03, P24-B), unit and integration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID


def conforms(value: Any, schema: dict[str, Any], components: dict[str, Any], where: str = "$") -> None:
    """``value`` has exactly the shape ``schema`` (OpenAPI 3.1, as FastAPI writes it) gives: every property and no
    other, of the stated types."""
    if "$ref" in schema:
        conforms(value, components[schema["$ref"].rsplit("/", 1)[-1]], components, where)
        return
    if "anyOf" in schema:
        failures = []
        for option in schema["anyOf"]:
            try:
                conforms(value, option, components, where)
                return
            except AssertionError as error:
                failures.append(str(error))
        raise AssertionError(f"{where}: matches no option ({failures})")
    if "enum" in schema:
        assert value in schema["enum"], where
    kind = schema.get("type")
    checks: dict[str, Callable[[Any], bool]] = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }
    assert kind in checks, f"{where}: unhandled schema {schema}"
    assert checks[kind](value), f"{where}: {value!r} is not {kind}"
    if kind == "object":
        properties = schema["properties"]
        assert set(value) == set(properties), f"{where}: {sorted(value)} != {sorted(properties)}"
        assert set(schema.get("required", ())) == set(properties), f"{where}: every property is required"
        for name, item in value.items():
            conforms(item, properties[name], components, f"{where}.{name}")
    if kind == "array":
        for index, item in enumerate(value):
            conforms(item, schema["items"], components, f"{where}[{index}]")
    if schema.get("format") == "date-time":
        datetime.fromisoformat(value)
    if schema.get("format") == "uuid":
        UUID(value)
