"""Witness-preserving PG insertion, including backward admission of older PGs."""

from __future__ import annotations

from collections import defaultdict

from ca3.fmg import (
    aggregate_continuations,
    aggregate_direct_relations,
    community_id,
    materialize_relation_records,
)


class IncrementalFMG:
    def __init__(self, lineage_types):
        self.lineage_types = set(lineage_types)
        self.pgs = {}
        self.members = {}
        self.occurrences = {}
        self.communities = {}
        self.memberships = []
        self.direct = defaultdict(list)
        self.continuations = {}

    def add_pg(self, pg, nodes, edges, partition, percentiles, selected, anchor_threshold=0.99):
        pgid = pg["pg_id"]
        if pgid in self.pgs:
            raise ValueError("Cannot rescore/reinsert an admitted PG")
        if any(
            pg["start_ns"] < old["end_ns"] and old["start_ns"] < pg["end_ns"]
            for old in self.pgs.values()
        ):
            raise ValueError("Overlapping admitted PGs")
        self.pgs[pgid] = dict(pg)
        lookup = {}
        for i, node in enumerate(nodes):
            cid = community_id(pg["logical_day"], pgid, int(partition[i]))
            lookup[(pgid, node["node_uuid"])] = cid
            c = self.communities.setdefault(
                cid,
                {
                    "community_id": cid,
                    "pg_id": pgid,
                    "logical_day": pg["logical_day"],
                    "start_ns": pg["start_ns"],
                    "end_ns": pg["end_ns"],
                    "node_count": 0,
                    "anchor_count": 0,
                    "context_carrier_count": 0,
                    "max_percentile": 0.0,
                },
            )
            c["node_count"] += 1
            c["max_percentile"] = max(c["max_percentile"], float(percentiles[i]))
            role = (
                ("anchor" if percentiles[i] >= anchor_threshold else "context_carrier")
                if selected[i]
                else None
            )
            if role:
                c[role + "_count"] += 1
            self.memberships.append(
                {
                    "community_id": cid,
                    "pg_id": pgid,
                    "node_uuid": node["node_uuid"],
                    "entity_type": node["entity_type"],
                    "selected_candidate": bool(selected[i]),
                    "seed_role": role,
                }
            )
        self.members[pgid] = {node: cid for (_, node), cid in lookup.items()}
        direct, _ = aggregate_direct_relations(
            edges, lookup, lineage_event_types=self.lineage_types, occurrence=self.occurrences
        )
        self.direct.update(direct)
        # Only adjacent pairs incident to the inserted PG can acquire new stitches.
        ordered = sorted(self.pgs.values(), key=lambda r: (r["start_ns"], r["end_ns"], r["pg_id"]))
        pos = next(i for i, r in enumerate(ordered) if r["pg_id"] == pgid)
        if pos > 0 and pos + 1 < len(ordered):
            self.continuations.pop((ordered[pos - 1]["pg_id"], ordered[pos + 1]["pg_id"]), None)
        for left, right in zip(
            ordered[max(0, pos - 1) : pos + 1], ordered[max(0, pos - 1) + 1 : pos + 2]
        ):
            self.continuations[(left["pg_id"], right["pg_id"])] = aggregate_continuations(
                [left, right], self.members, self.occurrences
            )

    def relations(self):
        result = dict(self.direct)
        for relations in self.continuations.values():
            result.update(relations)
        return result

    def records(self):
        return materialize_relation_records(
            self.relations(),
            rule_version="rq6-incremental-v1",
            construction_run_id="content-comparison",
        )

    def signature(self):
        """Canonical identity for checking fresh rebuild versus incremental insertion."""
        import hashlib

        import orjson

        edges, witnesses = self.records()
        return hashlib.sha256(
            orjson.dumps(
                {
                    "communities": sorted(
                        self.communities.values(), key=lambda c: c["community_id"]
                    ),
                    "memberships": sorted(
                        self.memberships, key=lambda m: (m["pg_id"], m["node_uuid"])
                    ),
                    "edges": edges,
                    "witnesses": [
                        {k: (v.hex() if isinstance(v, bytes) else v) for k, v in w.items()}
                        for w in witnesses
                    ],
                },
                option=orjson.OPT_SORT_KEYS,
                default=lambda v: v.hex() if isinstance(v, bytes) else str(v),
            )
        ).hexdigest()
