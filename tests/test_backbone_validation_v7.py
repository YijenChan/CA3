from ca3.backbone_validation import (
    RetainedTransition,
    validate_entry_to_seed_path,
    validate_identity_stitch_chain,
)


def edge(role: str, semantics: str, witnesses: tuple[str, ...] = ("event:1",)):
    return RetainedTransition("e1", "c1", "c2", role, semantics, witnesses)


def test_witnessed_identity_edge_can_only_stitch_time_partitions() -> None:
    result = validate_entry_to_seed_path(
        ("c1", "c2"), (edge("temporal_stitch", "identity_continuity"),)
    )
    assert result.valid


def test_identity_edge_cannot_claim_an_attack_transition() -> None:
    result = validate_entry_to_seed_path(
        ("c1", "c2"), (edge("attack_transition", "identity_continuity"),)
    )
    assert not result.valid
    assert result.reason_codes == ("identity_edge_promoted_to_attack_transition",)


def test_attack_transition_requires_witnesses() -> None:
    result = validate_entry_to_seed_path(
        ("c1", "c2"), (edge("attack_transition", "causal_event", ()),)
    )
    assert not result.valid
    assert "unwitnessed_retained_edge" in result.reason_codes


def test_identity_stitches_cannot_switch_to_an_unrelated_shared_entity() -> None:
    transitions = (
        RetainedTransition("e1", "c1", "c2", "temporal_stitch", "identity_continuity", ("w1",)),
        RetainedTransition("e2", "c2", "c3", "temporal_stitch", "identity_continuity", ("w2",)),
    )
    result = validate_identity_stitch_chain(
        transitions,
        witness_entities={"e1": {"core", "continued"}, "e2": {"generic"}},
        initial_core_entity_ids={"core"},
    )
    assert not result.valid
    assert result.invalid_edge_ids == ("e2",)


def test_identity_stitches_may_propagate_a_witnessed_core_identity() -> None:
    transitions = (
        RetainedTransition("e1", "c1", "c2", "temporal_stitch", "identity_continuity", ("w1",)),
        RetainedTransition("e2", "c2", "c3", "temporal_stitch", "identity_continuity", ("w2",)),
    )
    result = validate_identity_stitch_chain(
        transitions,
        witness_entities={"e1": {"core", "continued"}, "e2": {"continued"}},
        initial_core_entity_ids={"core"},
    )
    assert result.valid
