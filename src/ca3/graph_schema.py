"""Schemas and conservative semantics for the immutable CA3 graph store."""

from __future__ import annotations

import tomllib
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import orjson
import pyarrow as pa

from ca3.cdm18 import unwrap_union, uuid_value

UUID_TYPE = pa.binary(16)

EVENT_SCHEMA = pa.schema(
    [
        ("event_uuid", UUID_TYPE),
        ("timestamp_ns", pa.int64()),
        ("sequence", pa.int64()),
        ("event_type", pa.string()),
        ("flow_direction", pa.string()),
        ("host_uuid", UUID_TYPE),
        ("subject_uuid", UUID_TYPE),
        ("predicate_uuid", UUID_TYPE),
        ("predicate2_uuid", UUID_TYPE),
        ("predicate_path", pa.string()),
        ("predicate2_path", pa.string()),
        ("thread_id", pa.int64()),
        ("size", pa.int64()),
        ("name", pa.string()),
        ("exec_name", pa.string()),
        ("parent_pid", pa.string()),
        ("file_descriptor", pa.string()),
        ("return_value", pa.string()),
        ("logical_day", pa.int8()),
        ("phase", pa.string()),
        ("raw_shard", pa.int16()),
        ("raw_line", pa.int64()),
        ("raw_offset", pa.int64()),
    ]
)

NODE_SCHEMA = pa.schema(
    [
        ("node_uuid", UUID_TYPE),
        ("record_type", pa.string()),
        ("subtype", pa.string()),
        ("host_uuid", UUID_TYPE),
        ("parent_uuid", UUID_TYPE),
        ("principal_uuid", UUID_TYPE),
        ("start_timestamp_ns", pa.int64()),
        ("cid", pa.int64()),
        ("cmd_line", pa.string()),
        ("local_address", pa.string()),
        ("local_port", pa.int32()),
        ("remote_address", pa.string()),
        ("remote_port", pa.int32()),
        ("username", pa.string()),
        ("raw_shard", pa.int16()),
        ("raw_line", pa.int64()),
        ("raw_offset", pa.int64()),
    ]
)


def uuid_bytes(value: Any) -> bytes | None:
    text = uuid_value(value)
    if text is None:
        return None
    return uuid.UUID(text).bytes


def nullable_int(value: Any) -> int | None:
    value = unwrap_union(value)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def nullable_text(value: Any) -> str | None:
    value = unwrap_union(value)
    return value if isinstance(value, str) and value else None


def properties_map(body: Mapping[str, Any]) -> Mapping[str, Any]:
    properties = body.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    values = properties.get("map")
    return values if isinstance(values, Mapping) else {}


def load_directions(path: Path) -> tuple[dict[str, str], str]:
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    default = config["default_direction"]
    event_to_direction = {}
    for direction, event_types in config["directions"].items():
        for event_type in event_types:
            previous = event_to_direction.setdefault(event_type, direction)
            if previous != direction:
                raise ValueError(f"event type {event_type} has conflicting directions")
    return event_to_direction, default


def event_row(
    body: Mapping[str, Any],
    *,
    direction: str,
    logical_day: int | None,
    phase: str | None,
    raw_shard: int,
    raw_line: int,
    raw_offset: int,
) -> dict[str, Any]:
    properties = properties_map(body)
    return {
        "event_uuid": uuid_bytes(body.get("uuid")),
        "timestamp_ns": nullable_int(body.get("timestampNanos")),
        "sequence": nullable_int(body.get("sequence")),
        "event_type": nullable_text(body.get("type")),
        "flow_direction": direction,
        "host_uuid": uuid_bytes(body.get("hostId")),
        "subject_uuid": uuid_bytes(body.get("subject")),
        "predicate_uuid": uuid_bytes(body.get("predicateObject")),
        "predicate2_uuid": uuid_bytes(body.get("predicateObject2")),
        "predicate_path": nullable_text(body.get("predicateObjectPath")),
        "predicate2_path": nullable_text(body.get("predicateObject2Path")),
        "thread_id": nullable_int(body.get("threadId")),
        "size": nullable_int(body.get("size")),
        "name": nullable_text(body.get("name")),
        "exec_name": nullable_text(properties.get("exec")),
        "parent_pid": nullable_text(properties.get("ppid")),
        "file_descriptor": nullable_text(properties.get("fd")),
        "return_value": nullable_text(properties.get("return_value")),
        "logical_day": logical_day,
        "phase": phase,
        "raw_shard": raw_shard,
        "raw_line": raw_line,
        "raw_offset": raw_offset,
    }


def node_row(
    record_type: str,
    body: Mapping[str, Any],
    *,
    raw_shard: int,
    raw_line: int,
    raw_offset: int,
) -> dict[str, Any] | None:
    node_uuid = uuid_bytes(body.get("uuid"))
    if node_uuid is None:
        return None
    base_object = body.get("baseObject")
    base_object = base_object if isinstance(base_object, Mapping) else {}
    host_value = body.get("hostId", base_object.get("hostId"))
    principal_value = body.get("localPrincipal")
    return {
        "node_uuid": node_uuid,
        "record_type": record_type,
        "subtype": nullable_text(body.get("type")),
        "host_uuid": uuid_bytes(host_value),
        "parent_uuid": uuid_bytes(body.get("parentSubject")),
        "principal_uuid": uuid_bytes(principal_value),
        "start_timestamp_ns": nullable_int(body.get("startTimestampNanos")),
        "cid": nullable_int(body.get("cid")),
        "cmd_line": nullable_text(body.get("cmdLine")),
        "local_address": nullable_text(body.get("localAddress")),
        "local_port": nullable_int(body.get("localPort")),
        "remote_address": nullable_text(body.get("remoteAddress")),
        "remote_port": nullable_int(body.get("remotePort")),
        "username": nullable_text(body.get("username")),
        "raw_shard": raw_shard,
        "raw_line": raw_line,
        "raw_offset": raw_offset,
    }


def schema_fingerprint(schema: pa.Schema) -> str:
    import hashlib

    return hashlib.sha256(schema.serialize().to_pybytes()).hexdigest()


def json_bytes(value: Any) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
