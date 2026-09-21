from ca3.frontier import (
    ControllerState,
    EntityFact,
    EvidenceAtom,
    FrontierItem,
    ScopeAvailability,
    assess_initial_compromise,
    decide_next_action,
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
        EvidenceAtom("write", 30, "EVENT_WRITE", "server", "payload", "c2"),
        EvidenceAtom("execute", 40, "EVENT_EXECUTE", "payload", "implant", "c3"),
    ]


def _assessment(atoms: list[EvidenceAtom]):
    return assess_initial_compromise(
        atoms,
        _entities(),
        local_networks=("10.0.0.0/8",),
        entry_service_ports=(80,),
        callback_horizon_ns=100,
        local_effect_horizon_ns=100,
    )


def test_initial_compromise_requires_ingress_callback_and_local_effect() -> None:
    assessment = _assessment(_atoms())
    assert assessment.status == "supported"
    assert assessment.entry_subject_id == "server"
    assert assessment.first_local_subject_id == "implant"
    assert assessment.evidence_ids == ("accept", "connect", "execute", "write")


def test_ingress_attempt_does_not_become_supported() -> None:
    assessment = _assessment(_atoms()[:1])
    assert assessment.status == "attempted"


def test_partial_success_is_probable_not_supported() -> None:
    assessment = _assessment(_atoms()[:2])
    assert assessment.status == "probable"


def test_loopback_flow_cannot_satisfy_entry() -> None:
    entities = _entities()
    entities["ingress"] = EntityFact("ingress", "NET_FLOW", "127.0.0.1", 80, "127.0.0.1", 44000)
    assessment = assess_initial_compromise(
        _atoms(),
        entities,
        local_networks=("10.0.0.0/8",),
        entry_service_ports=(80,),
        callback_horizon_ns=100,
        local_effect_horizon_ns=100,
    )
    assert assessment.status == "absent"


def test_missing_entry_prefers_left_extension() -> None:
    state = ControllerState(
        ic=_assessment([]),
        frontier=(FrontierItem("entry", "entry", True, "open", "missing_entry"),),
        scope=ScopeAvailability(left=True, right=True),
        remaining_actions=3,
    )
    assert decide_next_action(state).action == "extend_left"


def test_attempted_entry_extends_right_for_success_consequence() -> None:
    state = ControllerState(
        ic=_assessment(_atoms()[:1]),
        frontier=(FrontierItem("entry", "entry", True, "open", "entry_unconfirmed"),),
        scope=ScopeAvailability(left=True, right=True),
        remaining_actions=3,
    )
    decision = decide_next_action(state)
    assert decision.action == "extend_right"
    assert decision.reason_code == "entry_success_not_yet_evidenced"


def test_connectivity_precedes_entry_extension() -> None:
    state = ControllerState(
        ic=_assessment([]),
        frontier=(
            FrontierItem("entry", "entry", True, "open", "missing_entry"),
            FrontierItem("bridge", "connectivity", True, "open", "missing_bridge"),
        ),
        scope=ScopeAvailability(left=True),
        remaining_actions=3,
    )
    assert decide_next_action(state).action == "retrieve_bridge"


def test_supported_entry_and_closed_frontier_is_complete() -> None:
    state = ControllerState(
        ic=_assessment(_atoms()),
        frontier=(),
        scope=ScopeAvailability(),
        remaining_actions=0,
    )
    assert decide_next_action(state).action == "stop_complete"


def test_budget_exhaustion_is_limited_not_complete() -> None:
    state = ControllerState(
        ic=_assessment(_atoms()[:2]),
        frontier=(FrontierItem("entry", "entry", True, "open", "entry_unconfirmed"),),
        scope=ScopeAvailability(right=True),
        remaining_actions=0,
    )
    decision = decide_next_action(state)
    assert decision.action == "stop_limited"
    assert decision.reason_code == "action_budget_exhausted"
