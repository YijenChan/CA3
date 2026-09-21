"""Deterministic, evidence-only Forensic Memory Graph primitives."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from itertools import pairwise
from typing import Any


def community_id(logical_day: int, pg_id: str, local_community: int) -> str:
    return f"d{logical_day:02d}:{pg_id}:c{local_community:05d}"


def edge_id(edge_type: str, src: str, dst: str) -> str:
    payload = f"{edge_type}\0{src}\0{dst}".encode()
    return f"fmg-{hashlib.sha256(payload).hexdigest()[:24]}"


def evidence_id(event_uuid: bytes, predicate_index: int) -> str:
    return f"event:{event_uuid.hex()}:p{predicate_index}"


def direct_relation_type(event_type: str, lineage_event_types: set[str]) -> str:
    if event_type in lineage_event_types:
        return "entity_lineage"
    return "provenance_reachability"


def continuation_relation_type(left: Mapping[str, Any], right: Mapping[str, Any]) -> str | None:
    if left["end_ns"] != right["start_ns"]:
        return None
    same_parent_interval = (
        left["candidate_start_ns"] == right["candidate_start_ns"]
        and left["candidate_end_ns"] == right["candidate_end_ns"]
    )
    if left["right_split_boundary"] and right["left_split_boundary"] and same_parent_interval:
        return "split_continuation"
    return "entity_continuation"


def witness_from_edge(
    row: Mapping[str, Any], *, entity_uuid: bytes | None = None
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id(row["first_event_uuid"], int(row["predicate_index"])),
        "pg_id": row["pg_id"],
        "entity_uuid": entity_uuid,
        "src_uuid": row["src_uuid"],
        "dst_uuid": row["dst_uuid"],
        "event_uuid": row["first_event_uuid"],
        "event_type": row["event_type"],
        "predicate_index": int(row["predicate_index"]),
        "timestamp_ns": int(row["first_timestamp_ns"]),
        "event_count": int(row["event_count"]),
        "raw_shard": int(row["first_raw_shard"]),
        "raw_line": int(row["first_raw_line"]),
        "raw_offset": int(row["first_raw_offset"]),
    }


def update_occurrence_witnesses(
    occurrence: dict[tuple[str, bytes], dict[str, dict[str, Any]]],
    row: Mapping[str, Any],
) -> None:
    for node_uuid in (row["src_uuid"], row["dst_uuid"]):
        key = (row["pg_id"], node_uuid)
        witness = witness_from_edge(row, entity_uuid=node_uuid)
        current = occurrence.setdefault(key, {"first": witness, "last": witness})
        first_key = (current["first"]["timestamp_ns"], current["first"]["evidence_id"])
        last_key = (current["last"]["timestamp_ns"], current["last"]["evidence_id"])
        candidate_key = (witness["timestamp_ns"], witness["evidence_id"])
        if candidate_key < first_key:
            current["first"] = witness
        if candidate_key > last_key:
            current["last"] = witness


def aggregate_direct_relations(
    rows: Iterable[Mapping[str, Any]],
    membership: Mapping[tuple[str, bytes], str],
    *,
    lineage_event_types: set[str],
    occurrence: dict[tuple[str, bytes], dict[str, dict[str, Any]]] | None = None,
) -> tuple[dict[tuple[str, str, str], list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    relations: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    community_evidence: dict[str, dict[str, Any]] = {}
    occurrence = occurrence if occurrence is not None else {}

    for row in rows:
        update_occurrence_witnesses(occurrence, row)
        src = membership[(row["pg_id"], row["src_uuid"])]
        dst = membership[(row["pg_id"], row["dst_uuid"])]
        witness = witness_from_edge(row)
        community_evidence.setdefault(src, witness)
        community_evidence.setdefault(dst, witness)
        if src == dst:
            continue
        relation_type = direct_relation_type(row["event_type"], lineage_event_types)
        relations[(src, dst, relation_type)].append(witness)
    return relations, community_evidence


def aggregate_continuations(
    pg_records: list[Mapping[str, Any]],
    members_by_pg: Mapping[str, Mapping[bytes, str]],
    occurrence: Mapping[tuple[str, bytes], Mapping[str, Mapping[str, Any]]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    relations: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    ordered = sorted(pg_records, key=lambda row: (row["start_ns"], row["end_ns"], row["pg_id"]))
    for left, right in pairwise(ordered):
        relation_type = continuation_relation_type(left, right)
        if relation_type is None:
            continue
        left_members = members_by_pg[left["pg_id"]]
        right_members = members_by_pg[right["pg_id"]]
        for entity_uuid in sorted(left_members.keys() & right_members.keys()):
            left_occurrence = occurrence.get((left["pg_id"], entity_uuid))
            right_occurrence = occurrence.get((right["pg_id"], entity_uuid))
            if left_occurrence is None or right_occurrence is None:
                continue
            left_witness = dict(left_occurrence["last"])
            right_witness = dict(right_occurrence["first"])
            if left_witness["timestamp_ns"] > right_witness["timestamp_ns"]:
                continue
            left_witness["continuation_side"] = "left"
            right_witness["continuation_side"] = "right"
            key = (left_members[entity_uuid], right_members[entity_uuid], relation_type)
            relations[key].extend((left_witness, right_witness))
    return relations


def materialize_relation_records(
    relations: Mapping[tuple[str, str, str], list[dict[str, Any]]],
    *,
    rule_version: str,
    construction_run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    edge_rows = []
    witness_rows = []
    for (src, dst, relation_type), witnesses in sorted(relations.items()):
        fmg_edge_id = edge_id(relation_type, src, dst)
        ordered = sorted(
            witnesses,
            key=lambda row: (
                row["timestamp_ns"],
                row["evidence_id"],
                row.get("continuation_side", "event"),
            ),
        )
        entity_ids = sorted(
            {row["entity_uuid"] for row in ordered if row.get("entity_uuid") is not None}
        )
        edge_rows.append(
            {
                "fmg_edge_id": fmg_edge_id,
                "src_community_id": src,
                "dst_community_id": dst,
                "edge_type": relation_type,
                "evidence_semantics": "identity_continuity"
                if relation_type in {"split_continuation", "entity_continuation"}
                else "causal_event",
                "time_relation": "continues"
                if relation_type in {"split_continuation", "entity_continuation"}
                else "before",
                "witness_count": len(ordered),
                "witness_entity_count": len(entity_ids),
                "first_witness_ns": ordered[0]["timestamp_ns"],
                "last_witness_ns": ordered[-1]["timestamp_ns"],
                "rule_version": rule_version,
                "construction_run_id": construction_run_id,
            }
        )
        for index, witness in enumerate(ordered):
            witness_rows.append(
                {
                    "fmg_edge_id": fmg_edge_id,
                    "witness_index": index,
                    "continuation_side": witness.get("continuation_side"),
                    **{key: witness[key] for key in witness if key != "continuation_side"},
                }
            )
    return edge_rows, witness_rows
