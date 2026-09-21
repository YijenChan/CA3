import numpy as np

from ca3.incremental_fmg import IncrementalFMG


def packet(i):
    pg = {
        "pg_id": f"p{i}",
        "logical_day": 6,
        "start_ns": i * 10,
        "end_ns": (i + 1) * 10,
        "candidate_start_ns": 0,
        "candidate_end_ns": 30,
        "left_split_boundary": i > 0,
        "right_split_boundary": i < 2,
    }
    nodes = [
        {"node_uuid": b"a" * 16, "entity_type": "SUBJECT_PROCESS"},
        {"node_uuid": b"b" * 16, "entity_type": "FILE_OBJECT"},
    ]
    edges = [
        {
            "pg_id": pg["pg_id"],
            "src_uuid": b"a" * 16,
            "dst_uuid": b"b" * 16,
            "event_type": "EVENT_WRITE",
            "predicate_index": 1,
            "first_event_uuid": bytes([i + 1]) * 16,
            "first_timestamp_ns": i * 10 + 1,
            "event_count": 1,
            "first_raw_shard": 0,
            "first_raw_line": i + 1,
            "first_raw_offset": i * 100,
        }
    ]
    return pg, nodes, edges, [0, 1], np.array([1.0, 0.0]), np.array([True, False])


def test_backward_and_middle_insert_match_recompute():
    states = []
    for order in ([0, 1, 2], [2, 1, 0], [0, 2, 1]):
        state = IncrementalFMG([])
        for i in order:
            state.add_pg(*packet(i))
        states.append(state.signature())
    assert len(set(states)) == 1


def test_duplicate_pg_rejected():
    import pytest

    state = IncrementalFMG([])
    state.add_pg(*packet(0))
    with pytest.raises(ValueError):
        state.add_pg(*packet(0))
