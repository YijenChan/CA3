from ca3.detector_context import CausalContextIndex


def test_bounded_context_walks_forward_and_backward_with_evidence_untouched():
    a, b, c = b"a" * 16, b"b" * 16, b"c" * 16
    edges = [
        {"src_uuid": a, "dst_uuid": b, "event_type": "WRITE", "first_timestamp_ns": 1},
        {"src_uuid": b, "dst_uuid": c, "event_type": "EXECUTE", "first_timestamp_ns": 2},
    ]
    result = CausalContextIndex(edges).query(b, hops=2, edge_budget=2)
    assert len(result) == 2
    assert {row["traversal_direction"] for row in result} == {"forward", "backward"}
    assert {row["event_type"] for row in result} == {"WRITE", "EXECUTE"}


def test_context_respects_global_edge_budget():
    seed = b"s" * 16
    edges = [
        {
            "src_uuid": seed,
            "dst_uuid": bytes([index]) * 16,
            "event_type": "X",
            "first_timestamp_ns": index,
        }
        for index in range(1, 6)
    ]
    assert len(CausalContextIndex(edges).query(seed, hops=2, edge_budget=3)) == 3


def test_neighbor_covering_balances_directions_and_distinct_neighbors():
    seed = b"s" * 16
    incoming_a, incoming_b = b"a" * 16, b"b" * 16
    outgoing_a, outgoing_b = b"c" * 16, b"d" * 16
    edges = [
        {"src_uuid": seed, "dst_uuid": outgoing_a, "event_type": "X", "first_timestamp_ns": 1},
        {"src_uuid": seed, "dst_uuid": outgoing_a, "event_type": "Y", "first_timestamp_ns": 2},
        {"src_uuid": seed, "dst_uuid": outgoing_b, "event_type": "Z", "first_timestamp_ns": 3},
        {"src_uuid": incoming_a, "dst_uuid": seed, "event_type": "X", "first_timestamp_ns": 4},
        {"src_uuid": incoming_b, "dst_uuid": seed, "event_type": "Y", "first_timestamp_ns": 5},
    ]
    result = CausalContextIndex(edges).query_neighbor_covering(seed, hops=1, edge_budget=4)
    assert {row["traversal_direction"] for row in result} == {"forward", "backward"}
    neighbors = {
        row["dst_uuid"] if row["traversal_direction"] == "forward" else row["src_uuid"]
        for row in result
    }
    assert neighbors == {incoming_a, incoming_b, outgoing_a, outgoing_b}


def test_neighbor_covering_prioritizes_residual_aligned_relations():
    seed = b"s" * 16
    ordinary = [bytes([index]) * 16 for index in range(1, 5)]
    important = b"i" * 16
    edges = [
        {
            "src_uuid": seed,
            "dst_uuid": neighbor,
            "event_type": "COMMON",
            "first_timestamp_ns": index,
        }
        for index, neighbor in enumerate(ordinary, start=1)
    ] + [
        {
            "src_uuid": seed,
            "dst_uuid": important,
            "event_type": "RARE",
            "first_timestamp_ns": 100,
        }
    ]
    result = CausalContextIndex(edges).query_neighbor_covering(
        seed, hops=1, edge_budget=2, priority_event_types={"RARE"}
    )
    assert important in {row["dst_uuid"] for row in result}


def test_neighbor_covering_uses_neighbor_score_inside_relation_priority():
    seed = b"s" * 16
    low, high = b"l" * 16, b"h" * 16
    edges = [
        {"src_uuid": seed, "dst_uuid": low, "event_type": "RARE", "first_timestamp_ns": 1},
        {"src_uuid": seed, "dst_uuid": high, "event_type": "RARE", "first_timestamp_ns": 2},
    ]
    result = CausalContextIndex(edges).query_neighbor_covering(
        seed,
        hops=1,
        edge_budget=1,
        priority_event_types={"RARE"},
        neighbor_scores={low: 0.1, high: 0.9},
    )
    assert result[0]["dst_uuid"] == high
