from ca3.frontier import EntityFact, EvidenceAtom
from ca3.progressive_control import (
    V7ControllerState,
    V7Frontier,
    assess_initial_compromise_in_scope,
    decide_v7_action,
)


def _entities() -> dict[str, EntityFact]:
    return {
        "ingress": EntityFact("ingress", "NET_FLOW", "10.0.0.5", 80, "8.8.8.8", 44000),
        "callback": EntityFact("callback", "NET_FLOW", "10.0.0.5", 38000, "1.1.1.1", 80),
        "server": EntityFact("server", "SUBJECT_PROCESS"),
        "implant": EntityFact("implant", "SUBJECT_PROCESS"),
        "payload": EntityFact("payload", "FILE_OBJECT_FILE", path="/tmp/payload"),
    }


def _atoms() -> list[EvidenceAtom]:
    return [
        EvidenceAtom("accept", 10, "EVENT_ACCEPT", "ingress", "server", "c1"),
        EvidenceAtom("connect", 20, "EVENT_CONNECT", "server", "callback", "c1"),
        EvidenceAtom("write", 1_000_000, "EVENT_WRITE", "server", "payload", "c2"),
        EvidenceAtom("execute", 2_000_000, "EVENT_EXECUTE", "payload", "implant", "c3"),
    ]


def _assessment(atoms: list[EvidenceAtom]):
    return assess_initial_compromise_in_scope(
        atoms,
        _entities(),
        local_networks=("10.0.0.0/8",),
        entry_service_ports=(80,),
    )


def test_scope_bounded_ordering_replaces_fixed_horizon() -> None:
    assert _assessment(_atoms()).status == "supported"


def test_partial_entry_stays_probable() -> None:
    assert _assessment(_atoms()[:2]).status == "probable"


def test_unresolved_entry_extends_only_left() -> None:
    state = V7ControllerState(
        ic=_assessment([]),
        frontiers=(V7Frontier("entry", "entry", "missing_entry"),),
        earlier_scope_available=True,
        remaining_actions=3,
        entry_connected_to_backbone=True,
        backbone_transitions_witnessed=True,
    )
    assert decide_v7_action(state).action == "extend_left"


def test_unresolved_entry_does_not_require_a_connected_entry_before_extension() -> None:
    state = V7ControllerState(
        ic=_assessment([]),
        frontiers=(V7Frontier("entry", "entry", "missing_entry"),),
        earlier_scope_available=True,
        remaining_actions=3,
        entry_connected_to_backbone=False,
        backbone_transitions_witnessed=True,
    )
    assert decide_v7_action(state).action == "extend_left"


def test_validation_precedes_connectivity_and_entry() -> None:
    state = V7ControllerState(
        ic=_assessment([]),
        frontiers=(
            V7Frontier("entry", "entry", "missing_entry"),
            V7Frontier("bridge", "connectivity", "missing_bridge"),
            V7Frontier("verify", "validation", "conflicting_reference"),
        ),
        earlier_scope_available=True,
        remaining_actions=3,
        entry_connected_to_backbone=False,
        backbone_transitions_witnessed=False,
    )
    assert decide_v7_action(state).action == "continue"


def test_complete_entry_path_terminates_even_at_budget_boundary() -> None:
    state = V7ControllerState(
        ic=_assessment(_atoms()),
        frontiers=(),
        earlier_scope_available=False,
        remaining_actions=0,
        entry_connected_to_backbone=True,
        backbone_transitions_witnessed=True,
    )
    assert decide_v7_action(state).action == "terminate"


def test_budget_exhaustion_suspends() -> None:
    state = V7ControllerState(
        ic=_assessment([]),
        frontiers=(V7Frontier("entry", "entry", "missing_entry"),),
        earlier_scope_available=True,
        remaining_actions=0,
        entry_connected_to_backbone=True,
        backbone_transitions_witnessed=True,
    )
    assert decide_v7_action(state).action == "suspend"
