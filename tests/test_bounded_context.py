from ca3.bounded_context import select_bounded_context


def test_budget_and_interleaving():
    edges = []
    for i, (s, d) in enumerate([(b"a", b"s"), (b"s", b"b"), (b"b", b"c")]):
        edges.append(
            {
                "src_uuid": s,
                "dst_uuid": d,
                "event_type": "EVENT_WRITE",
                "first_timestamp_ns": i,
                "first_event_uuid": bytes([i]),
                "predicate_index": 1,
                "pg_id": "p",
            }
        )
    selected, refs = select_bounded_context(
        edges, [{"node_uuid": b"s", "attribution_event_types": []}], {}, budget=2
    )
    assert len(refs) == 2 and len(selected) == 2
    assert refs[0]["src_uuid"] == b"a" and refs[1]["dst_uuid"] == b"b"
    selected, refs = select_bounded_context(
        edges, [{"node_uuid": b"s", "attribution_event_types": []}], {}, budget=3
    )
    assert len(refs) == 3
