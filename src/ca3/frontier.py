"""Evidence-gated initial-compromise assessment and frontier control for CA3."""

from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import asdict, dataclass
from typing import Literal

import orjson

IcStatus = Literal["absent", "attempted", "probable", "supported", "conflicted"]
GapType = Literal[
    "evidence_integrity",
    "connectivity",
    "entry",
    "stage_constraint",
    "left_time",
    "right_time",
    "host_scope",
    "competition",
]
Action = Literal[
    "verify_claim",
    "retrieve_bridge",
    "extend_left",
    "extend_right",
    "extend_host",
    "stop_complete",
    "stop_limited",
]


def _stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(orjson.dumps(value, option=orjson.OPT_SORT_KEYS)).hexdigest()
    return f"{prefix}-{digest[:20]}"


@dataclass(frozen=True)
class EntityFact:
    entity_id: str
    entity_type: str
    local_address: str | None = None
    local_port: int | None = None
    remote_address: str | None = None
    remote_port: int | None = None
    path: str | None = None


@dataclass(frozen=True)
class EvidenceAtom:
    evidence_id: str
    timestamp_ns: int
    event_type: str
    src_entity_id: str
    dst_entity_id: str
    community_id: str


@dataclass(frozen=True)
class InitialCompromiseAssessment:
    assessment_id: str
    status: IcStatus
    entry_subject_id: str | None
    entry_flow_id: str | None
    first_local_subject_id: str | None
    community_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    attack_query: str | None


@dataclass(frozen=True)
class FrontierItem:
    item_id: str
    gap_type: GapType
    critical: bool
    status: Literal["open", "closed", "blocked"]
    reason_code: str
    direction: Literal["left", "right", "host", "none"] = "none"


@dataclass(frozen=True)
class ScopeAvailability:
    left: bool = False
    right: bool = False
    host: bool = False


@dataclass(frozen=True)
class ControllerState:
    ic: InitialCompromiseAssessment
    frontier: tuple[FrontierItem, ...]
    scope: ScopeAvailability
    remaining_actions: int


@dataclass(frozen=True)
class ControlDecision:
    action: Action
    reason_code: str
    frontier_item_id: str | None
    terminal: bool


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


def assess_initial_compromise(
    atoms: list[EvidenceAtom],
    entities: dict[str, EntityFact],
    *,
    local_networks: tuple[str, ...],
    entry_service_ports: tuple[int, ...] = (80, 443),
    callback_horizon_ns: int,
    local_effect_horizon_ns: int,
) -> InitialCompromiseAssessment:
    """Assess entry without treating ATT&CK or an anomaly score as forensic proof.

    A supported claim needs a boundary ingress, a subsequent external callback from
    the affected subject, and a write-then-execute local effect. The evidence slice
    determines candidate scope; this function does not consume labels or scores.
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
        ids = tuple(sorted(atom.evidence_id for atom in malformed))
        payload = {"status": "conflicted", "evidence_ids": ids}
        return InitialCompromiseAssessment(
            assessment_id=_stable_id("ic", payload),
            status="conflicted",
            entry_subject_id=None,
            entry_flow_id=None,
            first_local_subject_id=None,
            community_ids=(),
            evidence_ids=ids,
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

    best: (
        tuple[int, EvidenceAtom, EvidenceAtom | None, EvidenceAtom | None, EvidenceAtom | None]
        | None
    ) = None
    for entry in ingress:
        callbacks = [
            atom
            for atom in ordered
            if atom.src_entity_id == entry.dst_entity_id
            and atom.dst_entity_id in external_flows
            and atom.event_type in {"EVENT_CONNECT", "EVENT_SENDTO", "EVENT_SENDMSG"}
            and entry.timestamp_ns <= atom.timestamp_ns <= entry.timestamp_ns + callback_horizon_ns
        ]
        callback = callbacks[0] if callbacks else None
        writes = [
            atom
            for atom in ordered
            if atom.src_entity_id == entry.dst_entity_id
            and atom.event_type == "EVENT_WRITE"
            and entities[atom.dst_entity_id].entity_type.startswith("FILE_OBJECT")
            and entry.timestamp_ns
            <= atom.timestamp_ns
            <= entry.timestamp_ns + local_effect_horizon_ns
        ]
        write = None
        execute = None
        for candidate_write in writes:
            matches = [
                atom
                for atom in ordered
                if atom.src_entity_id == candidate_write.dst_entity_id
                and atom.event_type == "EVENT_EXECUTE"
                and candidate_write.timestamp_ns
                <= atom.timestamp_ns
                <= entry.timestamp_ns + local_effect_horizon_ns
                and entities[atom.dst_entity_id].entity_type == "SUBJECT_PROCESS"
            ]
            if matches:
                write, execute = candidate_write, matches[0]
                break
        rank = 3 if callback and execute else 2 if callback or execute else 1
        candidate = (rank, entry, callback, write, execute)
        if best is None or (rank, -entry.timestamp_ns, entry.evidence_id) > (
            best[0],
            -best[1].timestamp_ns,
            best[1].evidence_id,
        ):
            best = candidate

    if best is None:
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

    rank, entry, callback, write, execute = best
    selected = [atom for atom in (entry, callback, write, execute) if atom is not None]
    status: IcStatus = "supported" if rank == 3 else "probable" if rank == 2 else "attempted"
    reasons = {
        "attempted": ("boundary_ingress_only",),
        "probable": ("boundary_ingress_with_partial_consequence",),
        "supported": ("boundary_ingress_callback_and_local_effect",),
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
        attack_query="exploit public-facing web server for initial access",
    )


def decide_next_action(state: ControllerState) -> ControlDecision:
    """Choose one auditable action; no scalar completeness score is used."""

    open_critical = sorted(
        (item for item in state.frontier if item.critical and item.status == "open"),
        key=lambda item: item.item_id,
    )
    if not open_critical and state.ic.status == "supported":
        return ControlDecision("stop_complete", "ic_supported_and_frontier_closed", None, True)
    if state.remaining_actions <= 0:
        item_id = open_critical[0].item_id if open_critical else None
        return ControlDecision("stop_limited", "action_budget_exhausted", item_id, True)

    def first(gap_type: GapType) -> FrontierItem | None:
        return next((item for item in open_critical if item.gap_type == gap_type), None)

    integrity = first("evidence_integrity")
    if state.ic.status == "conflicted" or integrity:
        return ControlDecision(
            "verify_claim",
            "invalid_or_conflicting_evidence",
            integrity.item_id if integrity else None,
            False,
        )
    connectivity = first("connectivity")
    if connectivity:
        return ControlDecision(
            "retrieve_bridge", connectivity.reason_code, connectivity.item_id, False
        )

    if state.ic.status == "absent":
        if state.scope.left:
            return ControlDecision(
                "extend_left", "entry_not_observed", _item_id(first("entry")), False
            )
        if state.scope.host:
            return ControlDecision(
                "extend_host", "entry_may_be_cross_host", _item_id(first("entry")), False
            )
        return ControlDecision(
            "stop_limited", "entry_evidence_unavailable", _item_id(first("entry")), True
        )
    if state.ic.status in {"attempted", "probable"}:
        if state.scope.right:
            return ControlDecision(
                "extend_right", "entry_success_not_yet_evidenced", _item_id(first("entry")), False
            )
        return ControlDecision(
            "stop_limited", "entry_consequence_unavailable", _item_id(first("entry")), True
        )

    stage = first("stage_constraint")
    if stage:
        action: Action = {
            "left": "extend_left",
            "right": "extend_right",
            "host": "extend_host",
            "none": "verify_claim",
        }[stage.direction]
        available = {
            "left": state.scope.left,
            "right": state.scope.right,
            "host": state.scope.host,
            "none": True,
        }[stage.direction]
        if available:
            return ControlDecision(action, stage.reason_code, stage.item_id, False)
        return ControlDecision("stop_limited", "stage_evidence_unavailable", stage.item_id, True)

    for gap_type, action in (
        ("left_time", "extend_left"),
        ("right_time", "extend_right"),
        ("host_scope", "extend_host"),
    ):
        item = first(gap_type)
        if item:
            available = getattr(state.scope, item.direction) if item.direction != "none" else False
            if available:
                return ControlDecision(action, item.reason_code, item.item_id, False)  # type: ignore[arg-type]
            return ControlDecision("stop_limited", "frontier_scope_unavailable", item.item_id, True)

    competition = first("competition")
    if competition:
        return ControlDecision("verify_claim", competition.reason_code, competition.item_id, False)
    if open_critical:
        return ControlDecision(
            "verify_claim", open_critical[0].reason_code, open_critical[0].item_id, False
        )
    return ControlDecision("stop_limited", "initial_compromise_not_supported", None, True)


def _item_id(item: FrontierItem | None) -> str | None:
    return item.item_id if item else None


def assessment_dict(value: InitialCompromiseAssessment) -> dict[str, object]:
    result = asdict(value)
    result["community_ids"] = list(value.community_ids)
    result["evidence_ids"] = list(value.evidence_ids)
    result["reason_codes"] = list(value.reason_codes)
    return result
