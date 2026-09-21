"""Evidence gates for a retained CA3 backbone."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TransitionRole = Literal["attack_transition", "temporal_stitch"]
EvidenceSemantics = Literal["causal_event", "identity_continuity"]


@dataclass(frozen=True)
class RetainedTransition:
    edge_id: str
    src_community_id: str
    dst_community_id: str
    role: TransitionRole
    evidence_semantics: EvidenceSemantics
    witness_ids: tuple[str, ...]


@dataclass(frozen=True)
class BackboneValidation:
    connected: bool
    all_edges_witnessed: bool
    all_attack_transitions_causal: bool
    valid: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class IdentityStitchValidation:
    valid: bool
    invalid_edge_ids: tuple[str, ...]


def validate_identity_stitch_chain(
    transitions: tuple[RetainedTransition, ...],
    *,
    witness_entities: dict[str, set[str]],
    initial_core_entity_ids: set[str],
) -> IdentityStitchValidation:
    """Prevent a path from switching between unrelated shared identities."""

    eligible = set(initial_core_entity_ids)
    invalid = []
    for edge in transitions:
        if edge.evidence_semantics != "identity_continuity":
            continue
        current = witness_entities.get(edge.edge_id, set())
        if not current or not current.intersection(eligible):
            invalid.append(edge.edge_id)
            continue
        # Only identities actually witnessed on this stitch can justify the
        # next identity stitch. A causal edge is validated independently.
        eligible = current
    return IdentityStitchValidation(not invalid, tuple(invalid))


def validate_entry_to_seed_path(
    community_ids: tuple[str, ...], transitions: tuple[RetainedTransition, ...]
) -> BackboneValidation:
    """Validate a directed entry-to-seed path without promoting identity to causality.

    Identity-continuity edges may stitch the same persistent entity across PG
    boundaries, but they cannot be labelled as an attack transition. Every
    transition that carries attack semantics must have causal-event evidence.
    """

    reasons: list[str] = []
    connected = len(community_ids) == 1 or (
        len(transitions) == len(community_ids) - 1
        and all(
            edge.src_community_id == community_ids[index]
            and edge.dst_community_id == community_ids[index + 1]
            for index, edge in enumerate(transitions)
        )
    )
    if not connected:
        reasons.append("entry_to_seed_path_disconnected")

    witnessed = all(edge.witness_ids for edge in transitions)
    if not witnessed:
        reasons.append("unwitnessed_retained_edge")

    causal = all(
        edge.role != "attack_transition" or edge.evidence_semantics == "causal_event"
        for edge in transitions
    )
    if not causal:
        reasons.append("identity_edge_promoted_to_attack_transition")

    return BackboneValidation(
        connected=connected,
        all_edges_witnessed=witnessed,
        all_attack_transitions_causal=causal,
        valid=connected and witnessed and causal,
        reason_codes=tuple(reasons),
    )
