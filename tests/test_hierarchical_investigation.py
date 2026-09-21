from ca3.hierarchical_investigation import (
    CoiCandidate,
    evidence_coverage,
    rank_coi,
    select_backbone_transition,
    select_core_continuations,
    select_forward_neighborhood,
    validate_assistant_references,
    validate_lead_references,
)


def _candidate(
    community_id: str,
    *,
    anchors: int = 1,
    boundary: int = 0,
    score: float = 1.0,
) -> CoiCandidate:
    return CoiCandidate(community_id, anchors, 0, boundary, score, 0.0, 0)


def test_boundary_relevance_precedes_strength_among_anchor_communities() -> None:
    ranked = rank_coi(
        [_candidate("high-score", score=100.0), _candidate("entry", boundary=1, score=2.0)]
    )
    assert ranked[0].community_id == "entry"


def test_anchor_precedes_boundary_only_carrier() -> None:
    ranked = rank_coi(
        [_candidate("carrier", anchors=0, boundary=2), _candidate("anchor", anchors=1)]
    )
    assert ranked[0].community_id == "anchor"


def test_forward_expansion_prefers_causal_edge() -> None:
    candidates = {name: _candidate(name) for name in ("root", "causal", "continuity")}
    edges = [
        {
            "fmg_edge_id": "z",
            "src_community_id": "root",
            "dst_community_id": "continuity",
            "evidence_semantics": "identity_continuity",
        },
        {
            "fmg_edge_id": "a",
            "src_community_id": "root",
            "dst_community_id": "causal",
            "evidence_semantics": "causal_event",
        },
    ]
    communities, edge_ids = select_forward_neighborhood("root", edges, candidates, max_neighbors=1)
    assert communities == ["root", "causal"]
    assert edge_ids == ["a"]


def test_agent_reference_gates_reject_hallucinated_ids() -> None:
    lead = {
        "actions": [
            {
                "community_ids": ["known", "invented"],
                "evidence_ids": ["event:known", "event:invented"],
            }
        ]
    }
    assert validate_lead_references(
        lead,
        allowed_community_ids={"known"},
        allowed_evidence_ids={"event:known"},
    ) == ["unknown_community:invented", "unknown_evidence:event:invented"]
    assistant = {
        "supporting_evidence_ids": ["event:known"],
        "conflicting_evidence_ids": ["event:known"],
    }
    assert validate_assistant_references(assistant, allowed_evidence_ids={"event:known"}) == [
        "support_conflict_overlap:event:known"
    ]


def test_core_continuation_requires_a_core_witness() -> None:
    edges = [
        {
            "fmg_edge_id": "core-edge",
            "src_community_id": "current",
            "dst_community_id": "next",
            "evidence_semantics": "identity_continuity",
            "first_witness_ns": 10,
        },
        {
            "fmg_edge_id": "benign-edge",
            "src_community_id": "current",
            "dst_community_id": "other",
            "evidence_semantics": "identity_continuity",
            "first_witness_ns": 5,
        },
    ]
    selected = select_core_continuations(
        {"current"},
        edges,
        {"core-edge": {"implant"}, "benign-edge": {"daemon"}},
        {"implant"},
        {"current"},
    )
    assert [edge["fmg_edge_id"] for edge in selected] == ["core-edge"]


def test_backbone_transition_prefers_causal_lineage() -> None:
    edges = [
        {
            "fmg_edge_id": "continuity",
            "src_community_id": "a",
            "dst_community_id": "b",
            "evidence_semantics": "identity_continuity",
            "edge_type": "entity_continuation",
        },
        {
            "fmg_edge_id": "causal",
            "src_community_id": "a",
            "dst_community_id": "b",
            "evidence_semantics": "causal_event",
            "edge_type": "entity_lineage",
        },
    ]
    assert select_backbone_transition("a", "b", edges)["fmg_edge_id"] == "causal"


def test_evidence_coverage_is_audit_only() -> None:
    message = {"actions": [{"evidence_ids": ["a", "b"]}]}
    assert evidence_coverage(message, {"a", "b", "c"}) == {
        "expected_count": 3,
        "covered_count": 2,
        "recall": 2 / 3,
    }
