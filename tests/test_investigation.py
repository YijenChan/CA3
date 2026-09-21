from dataclasses import replace

import pytest

from ca3.investigation import (
    FmgIndex,
    append_event,
    candidate_dict,
    initial_snapshot,
    reduce_ledger,
)


def _index() -> FmgIndex:
    communities = [
        {"community_id": "left", "start_ns": 0, "end_ns": 10},
        {"community_id": "middle", "start_ns": 5, "end_ns": 15},
        {"community_id": "right", "start_ns": 10, "end_ns": 20},
    ]
    edges = [
        {
            "fmg_edge_id": "e1",
            "src_community_id": "left",
            "dst_community_id": "middle",
            "edge_type": "entity_lineage",
            "evidence_semantics": "causal_event",
        },
        {
            "fmg_edge_id": "e2",
            "src_community_id": "middle",
            "dst_community_id": "right",
            "edge_type": "entity_continuation",
            "evidence_semantics": "identity_continuity",
        },
    ]
    witnesses = [
        {"fmg_edge_id": "e1", "evidence_id": "w1"},
        {"fmg_edge_id": "e2", "evidence_id": "w2"},
    ]
    return FmgIndex(communities, edges, witnesses)


def test_bridge_retrieval_returns_observed_path_with_witnesses() -> None:
    index = _index()
    query = index.make_query(gap_id="g1", left_community_id="left", right_community_id="right")
    candidates = index.retrieve(query)
    assert len(candidates) == 1
    assert candidates[0].community_path == ("left", "middle", "right")
    assert candidates[0].witness_ids == ("w1", "w2")
    assert candidates[0].support_class == "mixed_path"
    assert index.validate_candidate(query, candidates[0]) == []


def test_bridge_query_rejects_an_existing_direct_relation() -> None:
    index = _index()
    with pytest.raises(ValueError, match="direct FMG relation"):
        index.make_query(gap_id="g", left_community_id="left", right_community_id="middle")


def test_candidate_validation_rejects_path_tampering() -> None:
    index = _index()
    query = index.make_query(gap_id="g1", left_community_id="left", right_community_id="right")
    candidate = index.retrieve(query)[0]
    tampered = replace(candidate, edge_path=("e2", "e1"))
    assert "first_edge_path_mismatch" in index.validate_candidate(query, tampered)


def test_retrieval_does_not_mutate_backbone_before_acceptance() -> None:
    index = _index()
    query = index.make_query(gap_id="g1", left_community_id="left", right_community_id="right")
    candidate = index.retrieve(query)[0]
    backbone = ["left", "right"]
    ledger = []
    append_event(
        ledger,
        backbone_community_ids=backbone,
        event_type="gap_opened",
        actor="controller",
        round_index=0,
        payload={"gap_id": "g1", "gap_type": "connectivity", "status": "open"},
    )
    append_event(
        ledger,
        backbone_community_ids=backbone,
        event_type="bridge_query_issued",
        actor="controller",
        round_index=0,
        payload={"gap_id": "g1", "query_id": query.query_id},
    )
    append_event(
        ledger,
        backbone_community_ids=backbone,
        event_type="bridge_candidate_retrieved",
        actor="retriever",
        round_index=0,
        payload={"gap_id": "g1", **candidate_dict(candidate)},
    )
    pending = reduce_ledger(backbone, ledger)
    assert pending["backbone_community_ids"] == ["left", "right"]
    assert pending["next_action"] == "verify_claim"

    append_event(
        ledger,
        backbone_community_ids=backbone,
        event_type="bridge_candidate_accepted",
        actor="controller",
        round_index=1,
        payload={"gap_id": "g1", **candidate_dict(candidate)},
    )
    accepted = reduce_ledger(backbone, ledger)
    assert accepted["backbone_community_ids"] == ["left", "middle", "right"]
    assert accepted["backbone_edge_ids"] == ["e1", "e2"]


def test_empty_ledger_snapshot_is_deterministic() -> None:
    assert initial_snapshot(["b", "a"]) == reduce_ledger(["a", "b"], [])
