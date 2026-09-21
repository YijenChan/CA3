"""Reusable, evidence-preserving Detector feature store for complexity-bounded PGs."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import pyarrow as pa

from ca3.collector import PGInterval
from ca3.graph_schema import UUID_TYPE

ENTITY_TYPES = (
    "SUBJECT_PROCESS",
    "FILE_OBJECT_FILE",
    "FILE_OBJECT_DIR",
    "FILE_OBJECT_UNIX_SOCKET",
    "NET_FLOW",
    "SRC_SINK",
    "UNNAMED_PIPE",
    "PRINCIPAL",
    "HOST",
    "UNKNOWN",
)

NODE_TYPE_SCHEMA = pa.schema(
    [
        ("node_uuid", UUID_TYPE),
        ("record_type", pa.string()),
        ("subtype", pa.string()),
        ("entity_type", pa.string()),
        ("entity_type_id", pa.int8()),
        ("definition_count", pa.int32()),
        ("first_raw_shard", pa.int16()),
        ("first_raw_line", pa.int64()),
        ("first_raw_offset", pa.int64()),
    ]
)

PG_SCHEMA = pa.schema(
    [
        ("pg_id", pa.string()),
        ("logical_day", pa.int8()),
        ("phase", pa.string()),
        ("start_ns", pa.int64()),
        ("end_ns", pa.int64()),
        ("candidate_start_ns", pa.int64()),
        ("candidate_end_ns", pa.int64()),
        ("split_depth", pa.int8()),
        ("left_split_boundary", pa.bool_()),
        ("right_split_boundary", pa.bool_()),
        ("event_count", pa.int64()),
        ("node_count", pa.int32()),
        ("compressed_edge_count", pa.int64()),
        ("unknown_type_count", pa.int32()),
    ]
)


def node_feature_schema(action_count: int) -> pa.Schema:
    return pa.schema(
        [
            ("pg_id", pa.string()),
            ("logical_day", pa.int8()),
            ("phase", pa.string()),
            ("start_ns", pa.int64()),
            ("end_ns", pa.int64()),
            ("node_uuid", UUID_TYPE),
            ("entity_type", pa.string()),
            ("entity_type_id", pa.int8()),
            ("event_count", pa.int32()),
            ("subject_count", pa.int32()),
            ("predicate_count", pa.int32()),
            ("predicate2_count", pa.int32()),
            ("action_counts", pa.list_(pa.int32(), action_count)),
            ("action_distribution", pa.list_(pa.float32(), action_count)),
            ("activity_span_ns", pa.int64()),
            ("mean_gap_ns", pa.float64()),
            ("max_gap_ns", pa.int64()),
            ("span_ratio", pa.float32()),
            ("mean_gap_ratio", pa.float32()),
            ("max_gap_ratio", pa.float32()),
            ("in_degree", pa.int32()),
            ("out_degree", pa.int32()),
            ("unique_neighbor_count", pa.int32()),
        ]
    )


EDGE_FEATURE_SCHEMA = pa.schema(
    [
        ("pg_id", pa.string()),
        ("logical_day", pa.int8()),
        ("phase", pa.string()),
        ("src_uuid", UUID_TYPE),
        ("dst_uuid", UUID_TYPE),
        ("event_type", pa.string()),
        ("predicate_index", pa.int8()),
        ("event_count", pa.int32()),
        ("first_timestamp_ns", pa.int64()),
        ("last_timestamp_ns", pa.int64()),
        ("first_event_uuid", UUID_TYPE),
        ("first_raw_shard", pa.int16()),
        ("first_raw_line", pa.int64()),
        ("first_raw_offset", pa.int64()),
    ]
)


@dataclass
class _NodeAccumulator:
    roles: list[int]
    actions: list[int]
    timestamps: list[int]


@dataclass
class _EdgeAccumulator:
    count: int
    first_timestamp_ns: int
    last_timestamp_ns: int
    first_event_uuid: bytes | None
    first_raw_shard: int | None
    first_raw_line: int | None
    first_raw_offset: int | None


def canonical_entity_type(record_type: str | None, subtype: str | None) -> str:
    if subtype in ENTITY_TYPES:
        return subtype
    mapping = {
        "Subject": "SUBJECT_PROCESS",
        "NetFlowObject": "NET_FLOW",
        "SrcSinkObject": "SRC_SINK",
        "UnnamedPipeObject": "UNNAMED_PIPE",
        "Principal": "PRINCIPAL",
        "Host": "HOST",
    }
    return mapping.get(record_type, "UNKNOWN")


def build_node_type_rows(definitions: pa.Table) -> list[dict[str, Any]]:
    """Collapse repeated immutable definitions without using UUID as a model feature."""
    grouped: dict[bytes, dict[str, Any]] = {}
    ordered = sorted(
        definitions.to_pylist(),
        key=lambda row: (row["raw_shard"], row["raw_line"], row["raw_offset"]),
    )
    for row in ordered:
        node_uuid = row["node_uuid"]
        if node_uuid is None:
            continue
        current = grouped.get(node_uuid)
        if current is None:
            entity_type = canonical_entity_type(row["record_type"], row["subtype"])
            grouped[node_uuid] = {
                "node_uuid": node_uuid,
                "record_type": row["record_type"],
                "subtype": row["subtype"],
                "entity_type": entity_type,
                "entity_type_id": ENTITY_TYPES.index(entity_type),
                "definition_count": 1,
                "first_raw_shard": row["raw_shard"],
                "first_raw_line": row["raw_line"],
                "first_raw_offset": row["raw_offset"],
            }
            continue
        if current["record_type"] != row["record_type"]:
            raise ValueError(f"conflicting record types for UUID {node_uuid.hex()}")
        if current["subtype"] is None and row["subtype"] is not None:
            current["subtype"] = row["subtype"]
            entity_type = canonical_entity_type(current["record_type"], row["subtype"])
            current["entity_type"] = entity_type
            current["entity_type_id"] = ENTITY_TYPES.index(entity_type)
        current["definition_count"] += 1
    return list(grouped.values())


def node_type_lookup(rows: Sequence[Mapping[str, Any]]) -> dict[bytes, tuple[str, int]]:
    return {
        row["node_uuid"]: (row["entity_type"], row["entity_type_id"])
        for row in rows
        if row["node_uuid"] is not None
    }


def _directed_endpoints(row: Mapping[str, Any], predicate_key: str) -> tuple[bytes, bytes] | None:
    subject = row["subject_uuid"]
    predicate = row[predicate_key]
    if not isinstance(subject, bytes) or not isinstance(predicate, bytes) or subject == predicate:
        return None
    if row["flow_direction"] == "object_to_subject":
        return predicate, subject
    return subject, predicate


def materialize_pg_features(
    events: pa.Table,
    *,
    interval: PGInterval,
    candidate_interval: PGInterval,
    logical_day: int,
    phase: str,
    event_types: Sequence[str],
    types: Mapping[bytes, tuple[str, int]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Create model-neutral node features and compressed causal edges for one PG."""
    event_index = {name: index for index, name in enumerate(event_types)}
    nodes: dict[bytes, _NodeAccumulator] = {}
    edges: dict[tuple[bytes, bytes, str, int], _EdgeAccumulator] = {}
    in_neighbors: dict[bytes, set[bytes]] = defaultdict(set)
    out_neighbors: dict[bytes, set[bytes]] = defaultdict(set)

    for row in events.to_pylist():
        timestamp = row["timestamp_ns"]
        action = event_index.get(row["event_type"])
        endpoints = (
            (row["subject_uuid"], 0),
            (row["predicate_uuid"], 1),
            (row["predicate2_uuid"], 2),
        )
        for node_uuid, role in endpoints:
            if not isinstance(node_uuid, bytes):
                continue
            accumulator = nodes.setdefault(
                node_uuid,
                _NodeAccumulator([0, 0, 0], [0] * len(event_types), []),
            )
            accumulator.roles[role] += 1
            if action is not None:
                accumulator.actions[action] += 1
            if isinstance(timestamp, int):
                accumulator.timestamps.append(timestamp)

        for predicate_index, predicate_key in enumerate(
            ("predicate_uuid", "predicate2_uuid"), start=1
        ):
            directed = _directed_endpoints(row, predicate_key)
            if directed is None:
                continue
            source, target = directed
            key = (source, target, row["event_type"], predicate_index)
            edge = edges.get(key)
            if edge is None:
                edges[key] = _EdgeAccumulator(
                    count=1,
                    first_timestamp_ns=timestamp,
                    last_timestamp_ns=timestamp,
                    first_event_uuid=row["event_uuid"],
                    first_raw_shard=row["raw_shard"],
                    first_raw_line=row["raw_line"],
                    first_raw_offset=row["raw_offset"],
                )
            else:
                edge.count += 1
                if timestamp < edge.first_timestamp_ns:
                    edge.first_timestamp_ns = timestamp
                    edge.first_event_uuid = row["event_uuid"]
                    edge.first_raw_shard = row["raw_shard"]
                    edge.first_raw_line = row["raw_line"]
                    edge.first_raw_offset = row["raw_offset"]
                edge.last_timestamp_ns = max(edge.last_timestamp_ns, timestamp)
            out_neighbors[source].add(target)
            in_neighbors[target].add(source)

    pg_duration = max(interval.duration_ns, 1)
    node_rows = []
    unknown = 0
    for node_uuid, accumulator in nodes.items():
        ordered_times = sorted(accumulator.timestamps)
        if len(ordered_times) > 1:
            gaps = [right - left for left, right in pairwise(ordered_times)]
            span = ordered_times[-1] - ordered_times[0]
            mean_gap = sum(gaps) / len(gaps)
            max_gap = max(gaps)
        else:
            span = max_gap = 0
            mean_gap = 0.0
        entity_type, entity_type_id = types.get(
            node_uuid, ("UNKNOWN", ENTITY_TYPES.index("UNKNOWN"))
        )
        unknown += entity_type == "UNKNOWN"
        total = sum(accumulator.actions)
        denominator = max(total, 1)
        incoming = in_neighbors.get(node_uuid, set())
        outgoing = out_neighbors.get(node_uuid, set())
        node_rows.append(
            {
                "pg_id": interval.pg_id,
                "logical_day": logical_day,
                "phase": phase,
                "start_ns": interval.start_ns,
                "end_ns": interval.end_ns,
                "node_uuid": node_uuid,
                "entity_type": entity_type,
                "entity_type_id": entity_type_id,
                "event_count": total,
                "subject_count": accumulator.roles[0],
                "predicate_count": accumulator.roles[1],
                "predicate2_count": accumulator.roles[2],
                "action_counts": accumulator.actions,
                "action_distribution": [value / denominator for value in accumulator.actions],
                "activity_span_ns": span,
                "mean_gap_ns": mean_gap,
                "max_gap_ns": max_gap,
                "span_ratio": span / pg_duration,
                "mean_gap_ratio": mean_gap / pg_duration,
                "max_gap_ratio": max_gap / pg_duration,
                "in_degree": len(incoming),
                "out_degree": len(outgoing),
                "unique_neighbor_count": len(incoming | outgoing),
            }
        )

    edge_rows = [
        {
            "pg_id": interval.pg_id,
            "logical_day": logical_day,
            "phase": phase,
            "src_uuid": key[0],
            "dst_uuid": key[1],
            "event_type": key[2],
            "predicate_index": key[3],
            "event_count": edge.count,
            "first_timestamp_ns": edge.first_timestamp_ns,
            "last_timestamp_ns": edge.last_timestamp_ns,
            "first_event_uuid": edge.first_event_uuid,
            "first_raw_shard": edge.first_raw_shard,
            "first_raw_line": edge.first_raw_line,
            "first_raw_offset": edge.first_raw_offset,
        }
        for key, edge in edges.items()
    ]
    pg_row = {
        "pg_id": interval.pg_id,
        "logical_day": logical_day,
        "phase": phase,
        "start_ns": interval.start_ns,
        "end_ns": interval.end_ns,
        "candidate_start_ns": candidate_interval.start_ns,
        "candidate_end_ns": candidate_interval.end_ns,
        "split_depth": interval.depth,
        "left_split_boundary": interval.start_ns != candidate_interval.start_ns,
        "right_split_boundary": interval.end_ns != candidate_interval.end_ns,
        "event_count": events.num_rows,
        "node_count": len(node_rows),
        "compressed_edge_count": len(edge_rows),
        "unknown_type_count": unknown,
    }
    return pg_row, node_rows, edge_rows


def event_type_fingerprint(event_types: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(event_types).encode()).hexdigest()
