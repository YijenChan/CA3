from __future__ import annotations

import pyarrow as pa

from ca3.graph_query import materialize_edges
from ca3.graph_schema import EVENT_SCHEMA, uuid_bytes

SUBJECT = "269A60A2-39BE-11E8-B8CE-15D78AC88FB6"
OBJECT = "7D88BD7B-39C4-11E8-B8CE-15D78AC88FB6"


def event(direction: str) -> dict:
    return {
        "event_uuid": uuid_bytes(SUBJECT),
        "timestamp_ns": 1,
        "sequence": 1,
        "event_type": "EVENT_READ",
        "flow_direction": direction,
        "host_uuid": None,
        "subject_uuid": uuid_bytes(SUBJECT),
        "predicate_uuid": uuid_bytes(OBJECT),
        "predicate2_uuid": None,
        "predicate_path": "/tmp/a",
        "predicate2_path": None,
        "thread_id": None,
        "size": None,
        "name": None,
        "exec_name": None,
        "parent_pid": None,
        "file_descriptor": None,
        "return_value": None,
        "logical_day": 2,
        "phase": "fit",
        "raw_shard": 0,
        "raw_line": 1,
        "raw_offset": 0,
    }


def test_read_flows_from_object_to_subject() -> None:
    edges = materialize_edges(pa.Table.from_pylist([event("object_to_subject")], EVENT_SCHEMA))
    row = edges.to_pylist()[0]
    assert row["src_uuid"] == uuid_bytes(OBJECT)
    assert row["dst_uuid"] == uuid_bytes(SUBJECT)


def test_write_flows_from_subject_to_object() -> None:
    edges = materialize_edges(pa.Table.from_pylist([event("subject_to_object")], EVENT_SCHEMA))
    row = edges.to_pylist()[0]
    assert row["src_uuid"] == uuid_bytes(SUBJECT)
    assert row["dst_uuid"] == uuid_bytes(OBJECT)
