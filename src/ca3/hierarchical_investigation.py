"""Deterministic scheduling and agent-output gates for CA3 hierarchical investigation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CoiCandidate:
    community_id: str
    anchor_count: int
    carrier_count: int
    boundary_flow_count: int
    max_anchor_score: float
    max_carrier_score: float
    start_ns: int

    @property
    def has_anchor(self) -> bool:
        return self.anchor_count > 0

    @property
    def schedule_key(self) -> tuple[int, int, float, float, int, str]:
        return (
            -int(self.has_anchor),
            -self.boundary_flow_count,
            -self.max_anchor_score,
            -self.max_carrier_score,
            self.start_ns,
            self.community_id,
        )


def rank_coi(candidates: list[CoiCandidate]) -> list[CoiCandidate]:
    return sorted(candidates, key=lambda value: value.schedule_key)


def select_forward_neighborhood(
    root_community_id: str,
    edges: list[dict[str, Any]],
    candidates: dict[str, CoiCandidate],
    *,
    max_neighbors: int,
) -> tuple[list[str], list[str]]:
    """Select observed forward neighbors; continuity ranks after causal evidence."""

    outgoing = [
        edge
        for edge in edges
        if edge["src_community_id"] == root_community_id and edge["dst_community_id"] in candidates
    ]
    outgoing.sort(
        key=lambda edge: (
            int(edge["evidence_semantics"] != "causal_event"),
            candidates[edge["dst_community_id"]].schedule_key,
            edge["fmg_edge_id"],
        )
    )
    selected = outgoing[:max_neighbors]
    community_ids = [root_community_id]
    for edge in selected:
        if edge["dst_community_id"] not in community_ids:
            community_ids.append(edge["dst_community_id"])
    return community_ids, [edge["fmg_edge_id"] for edge in selected]


def select_core_continuations(
    frontier_community_ids: set[str],
    edges: list[dict[str, Any]],
    witness_entities: dict[str, set[str]],
    core_entity_ids: set[str],
    excluded_community_ids: set[str],
) -> list[dict[str, Any]]:
    selected = [
        edge
        for edge in edges
        if edge["src_community_id"] in frontier_community_ids
        and edge["dst_community_id"] not in excluded_community_ids
        and edge["evidence_semantics"] == "identity_continuity"
        and witness_entities.get(edge["fmg_edge_id"], set()) & core_entity_ids
    ]
    return sorted(
        selected,
        key=lambda edge: (
            edge["first_witness_ns"],
            edge["dst_community_id"],
            edge["fmg_edge_id"],
        ),
    )


def select_backbone_transition(
    src_community_id: str,
    dst_community_id: str,
    edges: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = [
        edge
        for edge in edges
        if edge["src_community_id"] == src_community_id
        and edge["dst_community_id"] == dst_community_id
    ]
    candidates.sort(
        key=lambda edge: (
            int(edge["evidence_semantics"] != "causal_event"),
            int(edge["edge_type"] != "entity_lineage"),
            edge["fmg_edge_id"],
        )
    )
    return candidates[0] if candidates else None


def validate_lead_references(
    message: dict[str, Any],
    *,
    allowed_community_ids: set[str],
    allowed_evidence_ids: set[str],
) -> list[str]:
    errors = []
    for action in message.get("actions", []):
        for community_id in action.get("community_ids", []):
            if community_id not in allowed_community_ids:
                errors.append(f"unknown_community:{community_id}")
        for evidence_id in action.get("evidence_ids", []):
            if evidence_id not in allowed_evidence_ids:
                errors.append(f"unknown_evidence:{evidence_id}")
    return sorted(set(errors))


def validate_assistant_references(
    message: dict[str, Any], *, allowed_evidence_ids: set[str]
) -> list[str]:
    errors = []
    for field in ("supporting_evidence_ids", "conflicting_evidence_ids"):
        for evidence_id in message.get(field, []):
            if evidence_id not in allowed_evidence_ids:
                errors.append(f"unknown_evidence:{evidence_id}")
    overlap = set(message.get("supporting_evidence_ids", [])) & set(
        message.get("conflicting_evidence_ids", [])
    )
    errors.extend(f"support_conflict_overlap:{value}" for value in overlap)
    return sorted(set(errors))


def evidence_coverage(
    message: dict[str, Any], expected_evidence_ids: set[str]
) -> dict[str, float | int]:
    cited = {
        evidence_id
        for action in message.get("actions", [])
        for evidence_id in action.get("evidence_ids", [])
    }
    covered = cited & expected_evidence_ids
    return {
        "expected_count": len(expected_evidence_ids),
        "covered_count": len(covered),
        "recall": len(covered) / len(expected_evidence_ids) if expected_evidence_ids else 1.0,
    }
