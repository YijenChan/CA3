from ca3.fmg import (
    aggregate_continuations,
    aggregate_direct_relations,
    community_id,
    continuation_relation_type,
    direct_relation_type,
    edge_id,
    materialize_relation_records,
)


def _edge_row(event_type: str = "EVENT_WRITE") -> dict:
    return {
        "pg_id": "pg-0-10",
        "src_uuid": b"a" * 16,
        "dst_uuid": b"b" * 16,
        "event_type": event_type,
        "predicate_index": 1,
        "event_count": 1,
        "first_timestamp_ns": 5,
        "first_event_uuid": b"e" * 16,
        "first_raw_shard": 0,
        "first_raw_line": 7,
        "first_raw_offset": 9,
    }


def test_stable_ids() -> None:
    cid = community_id(6, "pg-0-10", 3)
    assert cid == "d06:pg-0-10:c00003"
    assert edge_id("entity_lineage", cid, "other") == edge_id("entity_lineage", cid, "other")


def test_lineage_classification_is_explicit() -> None:
    lineage = {"EVENT_EXECUTE"}
    assert direct_relation_type("EVENT_EXECUTE", lineage) == "entity_lineage"
    assert direct_relation_type("EVENT_WRITE", lineage) == "provenance_reachability"


def test_split_continuation_requires_matching_parent_interval() -> None:
    left = {
        "start_ns": 0,
        "end_ns": 5,
        "candidate_start_ns": 0,
        "candidate_end_ns": 10,
        "left_split_boundary": False,
        "right_split_boundary": True,
    }
    right = {
        "start_ns": 5,
        "end_ns": 10,
        "candidate_start_ns": 0,
        "candidate_end_ns": 10,
        "left_split_boundary": True,
        "right_split_boundary": False,
    }
    assert continuation_relation_type(left, right) == "split_continuation"
    right["candidate_start_ns"] = 5
    assert continuation_relation_type(left, right) == "entity_continuation"


def test_direct_relation_keeps_raw_witness() -> None:
    membership = {
        ("pg-0-10", b"a" * 16): "c1",
        ("pg-0-10", b"b" * 16): "c2",
    }
    occurrence = {}
    relations, community_evidence = aggregate_direct_relations(
        [_edge_row("EVENT_EXECUTE")],
        membership,
        lineage_event_types={"EVENT_EXECUTE"},
        occurrence=occurrence,
    )
    assert list(relations) == [("c1", "c2", "entity_lineage")]
    assert relations[("c1", "c2", "entity_lineage")][0]["raw_offset"] == 9
    assert set(community_evidence) == {"c1", "c2"}
    assert occurrence[("pg-0-10", b"a" * 16)]["first"]["timestamp_ns"] == 5


def test_continuation_needs_two_observed_occurrences() -> None:
    entity = b"a" * 16
    pgs = [
        {
            "pg_id": "left",
            "start_ns": 0,
            "end_ns": 5,
            "candidate_start_ns": 0,
            "candidate_end_ns": 10,
            "left_split_boundary": False,
            "right_split_boundary": True,
        },
        {
            "pg_id": "right",
            "start_ns": 5,
            "end_ns": 10,
            "candidate_start_ns": 0,
            "candidate_end_ns": 10,
            "left_split_boundary": True,
            "right_split_boundary": False,
        },
    ]
    witness = {
        "evidence_id": "e",
        "pg_id": "left",
        "entity_uuid": entity,
        "src_uuid": entity,
        "dst_uuid": b"b" * 16,
        "event_uuid": b"e" * 16,
        "event_type": "EVENT_WRITE",
        "predicate_index": 1,
        "timestamp_ns": 4,
        "event_count": 1,
        "raw_shard": 0,
        "raw_line": 1,
        "raw_offset": 2,
    }
    right_witness = {**witness, "evidence_id": "f", "pg_id": "right", "timestamp_ns": 6}
    relations = aggregate_continuations(
        pgs,
        {"left": {entity: "c1"}, "right": {entity: "c2"}},
        {
            ("left", entity): {"first": witness, "last": witness},
            ("right", entity): {"first": right_witness, "last": right_witness},
        },
    )
    key = ("c1", "c2", "split_continuation")
    assert len(relations[key]) == 2
    edges, witnesses = materialize_relation_records(
        relations, rule_version="v1", construction_run_id="run"
    )
    assert edges[0]["witness_entity_count"] == 1
    assert edges[0]["evidence_semantics"] == "identity_continuity"
    assert {row["continuation_side"] for row in witnesses} == {"left", "right"}
