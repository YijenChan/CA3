"""Single-host, left-only progressive investigation control for CA3 v7."""

from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass
from typing import Literal

import orjson

from ca3.frontier import EntityFact, EvidenceAtom, IcStatus, InitialCompromiseAssessment

V7FrontierKind = Literal["validation", "connectivity", "entry"]
V7Action = Literal["continue", "retrieve_bridge", "extend_left", "terminate", "suspend"]


def _stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(orjson.dumps(value, option=orjson.OPT_SORT_KEYS)).hexdigest()
    return f"{prefix}-{digest[:20]}"


def _is_external_flow(entity: EntityFact, local_networks: tuple[str, ...]) -> bool:
    if entity.entity_type != "NET_FLOW" or not entity.remote_address:
        return False
    remote = ipaddress.ip_address(entity.remote_address)
    local = tuple(ipaddress.ip_network(network) for network in local_networks)
    if (
        remote.is_loopback
        or remote.is_private
        or remote.is_link_local
        or remote.is_multicast
        or remote.is_unspecified
    ):
        return False
    return not any(remote in network for network in local)


def assess_initial_compromise_in_scope(
    atoms: list[EvidenceAtom],
    entities: dict[str, EntityFact],
    *,
    local_networks: tuple[str, ...],
    entry_service_ports: tuple[int, ...] = (80, 443),
) -> InitialCompromiseAssessment:
    """Assess public-service entry using ordering inside the bounded evidence scope.

    The scope is supplied by the investigation round. No development-specific
    callback or local-effect duration is used here. Identity-continuity FMG edges
    are not inputs and therefore cannot raise the IC state.
    """

    ordered = sorted(atoms, key=lambda atom: (atom.timestamp_ns, atom.evidence_id))
    malformed = [
        atom
        for atom in ordered
        if atom.timestamp_ns < 0
        or atom.src_entity_id not in entities
        or atom.dst_entity_id not in entities
    ]
    if malformed:
        evidence_ids = tuple(sorted(atom.evidence_id for atom in malformed))
        payload = {"status": "conflicted", "evidence_ids": evidence_ids}
        return InitialCompromiseAssessment(
            assessment_id=_stable_id("ic", payload),
            status="conflicted",
            entry_subject_id=None,
            entry_flow_id=None,
            first_local_subject_id=None,
            community_ids=(),
            evidence_ids=evidence_ids,
            reason_codes=("invalid_evidence_reference",),
            attack_query=None,
        )

    external_flows = {
        entity_id
        for entity_id, entity in entities.items()
        if _is_external_flow(entity, local_networks)
    }
    ingress = [
        atom
        for atom in ordered
        if atom.event_type in {"EVENT_ACCEPT", "EVENT_RECVFROM", "EVENT_RECVMSG"}
        and atom.src_entity_id in external_flows
        and entities[atom.src_entity_id].local_port in entry_service_ports
        and entities[atom.dst_entity_id].entity_type == "SUBJECT_PROCESS"
    ]

    candidates: list[
        tuple[int, EvidenceAtom, EvidenceAtom | None, EvidenceAtom | None, EvidenceAtom | None]
    ] = []
    for entry in ingress:
        callback = next(
            (
                atom
                for atom in ordered
                if atom.src_entity_id == entry.dst_entity_id
                and atom.dst_entity_id in external_flows
                and atom.event_type in {"EVENT_CONNECT", "EVENT_SENDTO", "EVENT_SENDMSG"}
                and atom.timestamp_ns >= entry.timestamp_ns
            ),
            None,
        )
        write = None
        execute = None
        for candidate_write in ordered:
            if not (
                candidate_write.src_entity_id == entry.dst_entity_id
                and candidate_write.event_type == "EVENT_WRITE"
                and candidate_write.timestamp_ns >= entry.timestamp_ns
                and entities[candidate_write.dst_entity_id].entity_type.startswith("FILE_OBJECT")
            ):
                continue
            candidate_execute = next(
                (
                    atom
                    for atom in ordered
                    if atom.src_entity_id == candidate_write.dst_entity_id
                    and atom.event_type == "EVENT_EXECUTE"
                    and atom.timestamp_ns >= candidate_write.timestamp_ns
                    and entities[atom.dst_entity_id].entity_type == "SUBJECT_PROCESS"
                ),
                None,
            )
            if candidate_execute is not None:
                write, execute = candidate_write, candidate_execute
                break
        rank = (
            3
            if callback is not None and execute is not None
            else 2
            if (callback is not None or execute is not None)
            else 1
        )
        candidates.append((rank, entry, callback, write, execute))

    if not candidates:
        payload = {"status": "absent"}
        return InitialCompromiseAssessment(
            assessment_id=_stable_id("ic", payload),
            status="absent",
            entry_subject_id=None,
            entry_flow_id=None,
            first_local_subject_id=None,
            community_ids=(),
            evidence_ids=(),
            reason_codes=("no_boundary_ingress",),
            attack_query=None,
        )

    rank, entry, callback, write, execute = min(
        candidates,
        key=lambda value: (-value[0], value[1].timestamp_ns, value[1].evidence_id),
    )
    selected = [atom for atom in (entry, callback, write, execute) if atom is not None]
    status: IcStatus = "supported" if rank == 3 else "probable" if rank == 2 else "attempted"
    reasons = {
        "attempted": ("boundary_ingress_only",),
        "probable": ("boundary_ingress_with_linked_partial_consequence",),
        "supported": ("boundary_ingress_callback_and_ordered_local_effect",),
    }[status]
    payload = {
        "status": status,
        "evidence_ids": sorted(atom.evidence_id for atom in selected),
        "entry_subject_id": entry.dst_entity_id,
    }
    return InitialCompromiseAssessment(
        assessment_id=_stable_id("ic", payload),
        status=status,
        entry_subject_id=entry.dst_entity_id,
        entry_flow_id=entry.src_entity_id,
        first_local_subject_id=execute.dst_entity_id if execute else entry.dst_entity_id,
        community_ids=tuple(sorted({atom.community_id for atom in selected})),
        evidence_ids=tuple(sorted(atom.evidence_id for atom in selected)),
        reason_codes=reasons,
        attack_query="exploit public-facing service for initial access",
    )


@dataclass(frozen=True)
class V7Frontier:
    frontier_id: str
    kind: V7FrontierKind
    reason_code: str
    critical: bool = True
    status: Literal["open", "resolved", "blocked"] = "open"


@dataclass(frozen=True)
class V7ControllerState:
    ic: InitialCompromiseAssessment
    frontiers: tuple[V7Frontier, ...]
    earlier_scope_available: bool
    remaining_actions: int
    entry_connected_to_backbone: bool
    backbone_transitions_witnessed: bool


@dataclass(frozen=True)
class V7ControlDecision:
    action: V7Action
    reason_code: str
    frontier_id: str | None
    terminal: bool


def decide_v7_action(state: V7ControllerState) -> V7ControlDecision:
    """Apply the frozen validation -> connectivity -> entry priority."""

    open_frontiers = sorted(
        (
            frontier
            for frontier in state.frontiers
            if frontier.critical and frontier.status == "open"
        ),
        key=lambda frontier: (frontier.kind, frontier.frontier_id),
    )

    def first(kind: V7FrontierKind) -> V7Frontier | None:
        return next((frontier for frontier in open_frontiers if frontier.kind == kind), None)

    complete = (
        state.ic.status == "supported"
        and state.entry_connected_to_backbone
        and state.backbone_transitions_witnessed
        and not open_frontiers
    )
    if complete:
        return V7ControlDecision("terminate", "entry_boundary_resolved", None, True)
    if state.remaining_actions <= 0:
        return V7ControlDecision(
            "suspend",
            "action_budget_exhausted",
            open_frontiers[0].frontier_id if open_frontiers else None,
            True,
        )

    validation = first("validation")
    if state.ic.status == "conflicted" or validation is not None:
        return V7ControlDecision(
            "continue",
            "bounded_verification_required",
            validation.frontier_id if validation else None,
            False,
        )

    connectivity = first("connectivity")
    if connectivity is not None:
        return V7ControlDecision(
            "retrieve_bridge", connectivity.reason_code, connectivity.frontier_id, False
        )
    if not state.backbone_transitions_witnessed:
        return V7ControlDecision("suspend", "unmaterialized_connectivity_frontier", None, True)

    if state.ic.status != "supported":
        entry = first("entry")
        if state.earlier_scope_available:
            return V7ControlDecision(
                "extend_left",
                "entry_boundary_unresolved",
                entry.frontier_id if entry else None,
                False,
            )
        return V7ControlDecision(
            "suspend",
            "earlier_evidence_unavailable",
            entry.frontier_id if entry else None,
            True,
        )

    if not state.entry_connected_to_backbone:
        return V7ControlDecision("suspend", "supported_entry_not_connected_to_backbone", None, True)

    entry = first("entry")
    if entry is not None:
        return V7ControlDecision(
            "suspend", "inconsistent_open_entry_frontier", entry.frontier_id, True
        )
    return V7ControlDecision("suspend", "unresolved_investigation_state", None, True)
