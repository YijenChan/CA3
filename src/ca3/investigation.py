"""Typed bridge retrieval and append-only investigation state for CA3."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

import orjson


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(orjson.dumps(value, option=orjson.OPT_SORT_KEYS)).hexdigest()


@dataclass(frozen=True)
class BridgeQuery:
    query_id: str
    gap_id: str
    left_community_id: str
    right_community_id: str
    min_start_ns: int
    max_end_ns: int
    excluded_community_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BridgeCandidate:
    candidate_id: str
    query_id: str
    community_path: tuple[str, str, str]
    edge_path: tuple[str, str]
    edge_types: tuple[str, str]
    evidence_semantics: tuple[str, str]
    support_class: str
    witness_ids: tuple[str, ...]
    rank_key: tuple[int, int, str]

    @property
    def intermediate_community_id(self) -> str:
        return self.community_path[1]


class FmgIndex:
    def __init__(
        self,
        communities: Iterable[Mapping[str, Any]],
        edges: Iterable[Mapping[str, Any]],
        witnesses: Iterable[Mapping[str, Any]],
    ) -> None:
        self.communities = {row["community_id"]: dict(row) for row in communities}
        self.edges = {row["fmg_edge_id"]: dict(row) for row in edges}
        self.outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.edge_pairs: set[tuple[str, str]] = set()
        for edge in self.edges.values():
            self.outgoing[edge["src_community_id"]].append(edge)
            self.incoming[edge["dst_community_id"]].append(edge)
            self.edge_pairs.add((edge["src_community_id"], edge["dst_community_id"]))
        for adjacency in (self.outgoing, self.incoming):
            for rows in adjacency.values():
                rows.sort(key=lambda row: row["fmg_edge_id"])
        witness_ids: dict[str, list[str]] = defaultdict(list)
        for witness in witnesses:
            witness_ids[witness["fmg_edge_id"]].append(witness["evidence_id"])
        self.witness_ids = {
            edge_id: tuple(sorted(set(values))) for edge_id, values in witness_ids.items()
        }

    def make_query(
        self,
        *,
        gap_id: str,
        left_community_id: str,
        right_community_id: str,
        excluded_community_ids: Iterable[str] = (),
    ) -> BridgeQuery:
        if left_community_id not in self.communities or right_community_id not in self.communities:
            raise KeyError("bridge endpoint is absent from the FMG")
        if (left_community_id, right_community_id) in self.edge_pairs:
            raise ValueError("bridge query is invalid because a direct FMG relation already exists")
        left = self.communities[left_community_id]
        right = self.communities[right_community_id]
        payload = {
            "gap_id": gap_id,
            "left": left_community_id,
            "right": right_community_id,
            "min_start_ns": min(left["start_ns"], right["start_ns"]),
            "max_end_ns": max(left["end_ns"], right["end_ns"]),
            "excluded": sorted(set(excluded_community_ids)),
        }
        return BridgeQuery(
            query_id=f"bridge-query-{canonical_hash(payload)[:20]}",
            gap_id=gap_id,
            left_community_id=left_community_id,
            right_community_id=right_community_id,
            min_start_ns=payload["min_start_ns"],
            max_end_ns=payload["max_end_ns"],
            excluded_community_ids=tuple(payload["excluded"]),
        )

    def retrieve(self, query: BridgeQuery) -> list[BridgeCandidate]:
        excluded = set(query.excluded_community_ids)
        candidates = []
        for left_edge in self.outgoing.get(query.left_community_id, []):
            middle_id = left_edge["dst_community_id"]
            if middle_id in excluded or middle_id in {
                query.left_community_id,
                query.right_community_id,
            }:
                continue
            middle = self.communities[middle_id]
            if middle["end_ns"] <= query.min_start_ns or middle["start_ns"] >= query.max_end_ns:
                continue
            for right_edge in self.outgoing.get(middle_id, []):
                if right_edge["dst_community_id"] != query.right_community_id:
                    continue
                semantics = (
                    left_edge["evidence_semantics"],
                    right_edge["evidence_semantics"],
                )
                identity_count = sum(value == "identity_continuity" for value in semantics)
                causal_count = 2 - identity_count
                support_class = (
                    "causal_path"
                    if identity_count == 0
                    else "mixed_path"
                    if identity_count == 1
                    else "identity_only"
                )
                path = (
                    query.left_community_id,
                    middle_id,
                    query.right_community_id,
                )
                edge_path = (left_edge["fmg_edge_id"], right_edge["fmg_edge_id"])
                payload = {"query_id": query.query_id, "path": path, "edges": edge_path}
                candidates.append(
                    BridgeCandidate(
                        candidate_id=f"bridge-{canonical_hash(payload)[:20]}",
                        query_id=query.query_id,
                        community_path=path,
                        edge_path=edge_path,
                        edge_types=(left_edge["edge_type"], right_edge["edge_type"]),
                        evidence_semantics=semantics,
                        support_class=support_class,
                        witness_ids=tuple(
                            sorted(
                                set(self.witness_ids[edge_path[0]])
                                | set(self.witness_ids[edge_path[1]])
                            )
                        ),
                        rank_key=(identity_count, -causal_count, middle_id),
                    )
                )
        return sorted(candidates, key=lambda candidate: candidate.rank_key)

    def validate_candidate(self, query: BridgeQuery, candidate: BridgeCandidate) -> list[str]:
        errors = []
        if candidate.query_id != query.query_id:
            errors.append("query_id_mismatch")
        if candidate.community_path[0] != query.left_community_id:
            errors.append("left_endpoint_mismatch")
        if candidate.community_path[-1] != query.right_community_id:
            errors.append("right_endpoint_mismatch")
        middle = candidate.intermediate_community_id
        if middle in set(query.excluded_community_ids):
            errors.append("excluded_intermediate")
        if any(edge_id not in self.edges for edge_id in candidate.edge_path):
            errors.append("unknown_edge")
            return errors
        first, second = (self.edges[edge_id] for edge_id in candidate.edge_path)
        if (first["src_community_id"], first["dst_community_id"]) != (
            candidate.community_path[0],
            candidate.community_path[1],
        ):
            errors.append("first_edge_path_mismatch")
        if (second["src_community_id"], second["dst_community_id"]) != (
            candidate.community_path[1],
            candidate.community_path[2],
        ):
            errors.append("second_edge_path_mismatch")
        if not candidate.witness_ids:
            errors.append("missing_witness")
        return errors


def initial_snapshot(backbone_community_ids: Iterable[str]) -> dict[str, Any]:
    snapshot = {
        "ledger_offset": -1,
        "backbone_community_ids": sorted(set(backbone_community_ids)),
        "backbone_edge_ids": [],
        "open_gaps": {},
        "retrieved_candidates": {},
        "next_action": "inspect_frontier",
        "action_reason_gap_id": None,
    }
    snapshot["snapshot_hash"] = canonical_hash(snapshot)
    return snapshot


def reduce_ledger(
    backbone_community_ids: Iterable[str], ledger: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    snapshot = initial_snapshot(backbone_community_ids)
    for event in ledger:
        if event["input_snapshot_hash"] != snapshot["snapshot_hash"]:
            raise ValueError(f"ledger hash-chain mismatch at offset {event['offset']}")
        payload = event["payload"]
        event_type = event["event_type"]
        if event_type == "gap_opened":
            snapshot["open_gaps"][payload["gap_id"]] = dict(payload)
            snapshot["next_action"] = "retrieve_bridge"
            snapshot["action_reason_gap_id"] = payload["gap_id"]
        elif event_type == "bridge_query_issued":
            if payload["gap_id"] not in snapshot["open_gaps"]:
                raise ValueError("bridge query references a gap that is not open")
        elif event_type == "bridge_candidate_retrieved":
            snapshot["retrieved_candidates"][payload["candidate_id"]] = dict(payload)
            snapshot["next_action"] = "verify_claim"
        elif event_type == "bridge_candidate_rejected":
            snapshot["retrieved_candidates"].pop(payload["candidate_id"], None)
            snapshot["next_action"] = "retrieve_bridge"
        elif event_type == "bridge_candidate_accepted":
            if payload["candidate_id"] not in snapshot["retrieved_candidates"]:
                raise ValueError("cannot accept an unrecorded bridge candidate")
            snapshot["backbone_community_ids"] = sorted(
                set(snapshot["backbone_community_ids"]) | set(payload["community_path"])
            )
            snapshot["backbone_edge_ids"] = sorted(
                set(snapshot["backbone_edge_ids"]) | set(payload["edge_path"])
            )
            snapshot["open_gaps"].pop(payload["gap_id"], None)
            snapshot["next_action"] = "inspect_frontier"
            snapshot["action_reason_gap_id"] = None
        elif event_type == "stop_recorded":
            snapshot["next_action"] = payload["action"]
            snapshot["action_reason_gap_id"] = payload.get("gap_id")
        else:
            raise ValueError(f"unsupported CP7-C ledger event: {event_type}")
        snapshot["ledger_offset"] = event["offset"]
        snapshot.pop("snapshot_hash", None)
        snapshot["snapshot_hash"] = canonical_hash(snapshot)
    return snapshot


def append_event(
    ledger: list[dict[str, Any]],
    *,
    backbone_community_ids: Iterable[str],
    event_type: str,
    actor: str,
    round_index: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = reduce_ledger(backbone_community_ids, ledger)
    offset = len(ledger)
    event_payload = {
        "offset": offset,
        "event_type": event_type,
        "actor": actor,
        "round": round_index,
        "input_snapshot_hash": snapshot["snapshot_hash"],
        "payload": dict(payload),
    }
    event = {
        **event_payload,
        "event_id": f"ledger-{canonical_hash(event_payload)[:24]}",
    }
    ledger.append(event)
    return event


def candidate_dict(candidate: BridgeCandidate) -> dict[str, Any]:
    value = asdict(candidate)
    value["community_path"] = list(candidate.community_path)
    value["edge_path"] = list(candidate.edge_path)
    value["edge_types"] = list(candidate.edge_types)
    value["evidence_semantics"] = list(candidate.evidence_semantics)
    value["witness_ids"] = list(candidate.witness_ids)
    value["rank_key"] = list(candidate.rank_key)
    return value
