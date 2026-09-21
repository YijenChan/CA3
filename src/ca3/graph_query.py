"""Causal window queries and local edge materialization for the CA3 graph store."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import orjson
import pyarrow as pa
import pyarrow.dataset as ds

from ca3.cdm18 import datum_type, uuid_value
from ca3.graph_schema import UUID_TYPE
from ca3.paths import require_d_drive

EDGE_VIEW_SCHEMA = pa.schema(
    [
        ("event_uuid", UUID_TYPE),
        ("timestamp_ns", pa.int64()),
        ("event_type", pa.string()),
        ("flow_direction", pa.string()),
        ("src_uuid", UUID_TYPE),
        ("dst_uuid", UUID_TYPE),
        ("src_role", pa.string()),
        ("dst_role", pa.string()),
        ("predicate_index", pa.int8()),
        ("object_path", pa.string()),
        ("phase", pa.string()),
        ("raw_shard", pa.int16()),
        ("raw_line", pa.int64()),
        ("raw_offset", pa.int64()),
    ]
)


def materialize_edges(events: pa.Table) -> pa.Table:
    """Expand event facts into primary/secondary directed edges without dropping facts."""
    rows = []
    for event in events.to_pylist():
        subject = event["subject_uuid"]
        for index, (predicate_key, path_key) in enumerate(
            (("predicate_uuid", "predicate_path"), ("predicate2_uuid", "predicate2_path")),
            start=1,
        ):
            predicate = event[predicate_key]
            if subject is None or predicate is None:
                continue
            if event["flow_direction"] == "object_to_subject":
                src_uuid, dst_uuid = predicate, subject
                src_role, dst_role = f"predicate{index}", "subject"
            else:
                src_uuid, dst_uuid = subject, predicate
                src_role, dst_role = "subject", f"predicate{index}"
            rows.append(
                {
                    "event_uuid": event["event_uuid"],
                    "timestamp_ns": event["timestamp_ns"],
                    "event_type": event["event_type"],
                    "flow_direction": event["flow_direction"],
                    "src_uuid": src_uuid,
                    "dst_uuid": dst_uuid,
                    "src_role": src_role,
                    "dst_role": dst_role,
                    "predicate_index": index,
                    "object_path": event[path_key],
                    "phase": event["phase"],
                    "raw_shard": event["raw_shard"],
                    "raw_line": event["raw_line"],
                    "raw_offset": event["raw_offset"],
                }
            )
    return pa.Table.from_pylist(rows, schema=EDGE_VIEW_SCHEMA)


def scan_events(
    store_dir: Path,
    *,
    start_ns: int,
    end_ns: int,
    phase: str | None = None,
    columns: list[str] | None = None,
) -> pa.Table:
    store_dir = require_d_drive(store_dir)
    dataset = ds.dataset(store_dir / "events", format="parquet")
    predicate = (ds.field("timestamp_ns") >= start_ns) & (ds.field("timestamp_ns") < end_ns)
    if phase is not None:
        predicate &= ds.field("phase") == phase
    return dataset.to_table(filter=predicate, columns=columns)


def read_raw_evidence(
    raw_file: Path,
    *,
    byte_offset: int,
    expected_uuid: bytes | None = None,
) -> dict[str, Any]:
    raw_file = require_d_drive(raw_file)
    with raw_file.open("rb") as stream:
        stream.seek(byte_offset)
        line = stream.readline()
    record = orjson.loads(line)
    _, body = datum_type(record)
    if expected_uuid is not None:
        actual = uuid_value(body.get("uuid"))
        if actual is None or uuid.UUID(actual).bytes != expected_uuid:
            raise ValueError("raw evidence UUID does not match graph-store reference")
    return record
