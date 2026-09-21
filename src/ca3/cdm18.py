"""Small, dependency-free helpers for DARPA TC CDM18 JSON records."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def datum_type(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    datum = record.get("datum")
    if not isinstance(datum, dict) or len(datum) != 1:
        raise ValueError("record must contain exactly one CDM datum")
    qualified_name, body = next(iter(datum.items()))
    if not isinstance(body, dict):
        raise TypeError("CDM datum body must be an object")
    return qualified_name.rsplit(".", 1)[-1], body


def unwrap_union(value: Any) -> Any:
    """Unwrap Avro JSON unions represented as a one-key mapping."""
    while isinstance(value, dict) and len(value) == 1:
        value = next(iter(value.values()))
    return value


def uuid_value(value: Any) -> str | None:
    value = unwrap_union(value)
    return value if isinstance(value, str) and value else None


def event_references(body: dict[str, Any]) -> Iterable[str]:
    for field in ("hostId", "subject", "predicateObject", "predicateObject2"):
        value = uuid_value(body.get(field))
        if value is not None:
            yield value
