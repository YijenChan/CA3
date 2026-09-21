"""Complexity-bounded provenance-graph interval construction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pyarrow as pa


@dataclass(frozen=True)
class PGInterval:
    """A half-open provenance-graph interval produced by the Collector."""

    start_ns: int
    end_ns: int
    depth: int = 0

    @property
    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns

    @property
    def pg_id(self) -> str:
        return f"pg-{self.start_ns}-{self.end_ns}"


def _event_endpoints(row: Mapping[str, Any]) -> tuple[bytes, ...]:
    values = (row.get("subject_uuid"), row.get("predicate_uuid"), row.get("predicate2_uuid"))
    return tuple(value for value in values if isinstance(value, bytes))


def unique_nodes(events: pa.Table) -> set[bytes]:
    """Return the canonical entities touched by an event table."""
    nodes: set[bytes] = set()
    for row in events.select(["subject_uuid", "predicate_uuid", "predicate2_uuid"]).to_pylist():
        nodes.update(_event_endpoints(row))
    return nodes


def split_interval(
    events: pa.Table,
    interval: PGInterval,
    *,
    node_budget: int,
    minimum_interval_ns: int,
) -> list[PGInterval]:
    """Bisect an interval until its node budget or time floor is met."""
    if node_budget < 1 or minimum_interval_ns < 1:
        raise ValueError("node_budget and minimum_interval_ns must be positive")
    timestamps = events.column("timestamp_ns").to_pylist()
    rows = events.to_pylist()

    def visit(current: PGInterval, indices: list[int]) -> list[PGInterval]:
        nodes: set[bytes] = set()
        for index in indices:
            nodes.update(_event_endpoints(rows[index]))
        if len(nodes) <= node_budget or current.duration_ns <= minimum_interval_ns:
            return [current]
        midpoint = current.start_ns + current.duration_ns // 2
        if midpoint <= current.start_ns or midpoint >= current.end_ns:
            return [current]
        left = [index for index in indices if timestamps[index] < midpoint]
        right = [index for index in indices if timestamps[index] >= midpoint]
        if not left or not right:
            return [current]
        return visit(PGInterval(current.start_ns, midpoint, current.depth + 1), left) + visit(
            PGInterval(midpoint, current.end_ns, current.depth + 1), right
        )

    selected = [
        index
        for index, timestamp in enumerate(timestamps)
        if timestamp is not None and interval.start_ns <= timestamp < interval.end_ns
    ]
    return visit(interval, selected)
