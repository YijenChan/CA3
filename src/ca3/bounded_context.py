"""Deterministic within-PG edge retrieval with a per-seed budget."""

from collections import defaultdict


def select_bounded_context(edges, seed_rows, percentiles, *, budget=40):
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for edge_index, edge in enumerate(edges):
        outgoing[edge["src_uuid"]].append(edge_index)
        incoming[edge["dst_uuid"]].append(edge_index)
    refs = []
    unique = set()
    for seed in seed_rows:
        entity = seed["node_uuid"]
        matched_types = set(seed["attribution_event_types"])

        def ordered(ids, center, *, matched=frozenset(matched_types)):
            def key(position):
                edge = edges[position]
                other = edge["dst_uuid"] if edge["src_uuid"] == center else edge["src_uuid"]
                return (
                    edge["event_type"] not in matched,
                    -percentiles.get(other, 0),
                    edge["first_timestamp_ns"],
                    edge["first_event_uuid"],
                    edge["predicate_index"],
                    edge["src_uuid"],
                    edge["dst_uuid"],
                )

            return sorted(ids, key=key)

        def interleaved(center):
            ins = ordered(incoming[center], center)
            outs = ordered(outgoing[center], center)
            for position in range(max(len(ins), len(outs))):
                if position < len(ins):
                    yield ins[position]
                if position < len(outs):
                    yield outs[position]

        chosen = []
        seen = set()
        for index in interleaved(entity):
            if index not in seen:
                chosen.append(index)
                seen.add(index)
            if len(chosen) >= budget:
                break
        neighbors = sorted(
            {
                value
                for index in chosen
                for value in (edges[index]["src_uuid"], edges[index]["dst_uuid"])
                if value != entity
            }
        )
        for neighbor in neighbors:
            if len(chosen) >= budget:
                break
            for index in interleaved(neighbor):
                if index not in seen:
                    chosen.append(index)
                    seen.add(index)
                if len(chosen) >= budget:
                    break
        for rank, index in enumerate(chosen):
            edge = edges[index]
            unique.add(index)
            refs.append(
                {
                    "pg_id": edge["pg_id"],
                    "seed_uuid": entity,
                    "rank": rank + 1,
                    "first_event_uuid": edge["first_event_uuid"],
                    "predicate_index": edge["predicate_index"],
                    "src_uuid": edge["src_uuid"],
                    "dst_uuid": edge["dst_uuid"],
                }
            )
    return [edges[index] for index in sorted(unique)], refs
