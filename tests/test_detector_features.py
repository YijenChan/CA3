import pyarrow as pa

from ca3.collector import PGInterval
from ca3.detector_features import (
    ENTITY_TYPES,
    build_node_type_rows,
    canonical_entity_type,
    materialize_pg_features,
)
from ca3.graph_schema import EVENT_SCHEMA, NODE_SCHEMA


def _table(schema, rows):
    defaults = {field.name: None for field in schema}
    return pa.Table.from_pylist([defaults | row for row in rows], schema=schema)


def test_node_type_index_collapses_repeated_definitions():
    node_uuid = b"a" * 16
    definitions = _table(
        NODE_SCHEMA,
        [
            {
                "node_uuid": node_uuid,
                "record_type": "Subject",
                "raw_shard": 1,
                "raw_line": 2,
                "raw_offset": 3,
            },
            {
                "node_uuid": node_uuid,
                "record_type": "Subject",
                "subtype": "SUBJECT_PROCESS",
                "raw_shard": 1,
                "raw_line": 4,
                "raw_offset": 5,
            },
        ],
    )
    rows = build_node_type_rows(definitions)
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "SUBJECT_PROCESS"
    assert rows[0]["definition_count"] == 2


def test_entity_type_mapping_is_small_and_explicit():
    assert canonical_entity_type("NetFlowObject", None) == "NET_FLOW"
    assert canonical_entity_type("FileObject", "FILE_OBJECT_FILE") == "FILE_OBJECT_FILE"
    assert canonical_entity_type("Unknown", None) == "UNKNOWN"
    assert len(ENTITY_TYPES) == 10


def test_pg_features_preserve_types_actions_time_and_evidence():
    a, b = b"a" * 16, b"b" * 16
    events = _table(
        EVENT_SCHEMA,
        [
            {
                "event_uuid": b"1" * 16,
                "timestamp_ns": 20,
                "event_type": "READ",
                "flow_direction": "object_to_subject",
                "subject_uuid": a,
                "predicate_uuid": b,
                "raw_shard": 0,
                "raw_line": 1,
                "raw_offset": 2,
            },
            {
                "event_uuid": b"2" * 16,
                "timestamp_ns": 10,
                "event_type": "READ",
                "flow_direction": "object_to_subject",
                "subject_uuid": a,
                "predicate_uuid": b,
                "raw_shard": 0,
                "raw_line": 2,
                "raw_offset": 3,
            },
        ],
    )
    interval = PGInterval(0, 100)
    pg, nodes, edges = materialize_pg_features(
        events,
        interval=interval,
        candidate_interval=interval,
        logical_day=6,
        phase="development",
        event_types=["READ", "WRITE"],
        types={a: ("SUBJECT_PROCESS", 0), b: ("FILE_OBJECT_FILE", 1)},
    )
    by_uuid = {row["node_uuid"]: row for row in nodes}
    assert by_uuid[a]["action_counts"] == [2, 0]
    assert by_uuid[a]["activity_span_ns"] == 10
    assert by_uuid[b]["entity_type"] == "FILE_OBJECT_FILE"
    assert len(edges) == 1
    assert edges[0]["src_uuid"] == b and edges[0]["dst_uuid"] == a
    assert edges[0]["event_count"] == 2
    assert edges[0]["first_timestamp_ns"] == 10
    assert edges[0]["first_event_uuid"] == b"2" * 16
    assert edges[0]["first_raw_offset"] == 3
    assert pg["compressed_edge_count"] == 1
