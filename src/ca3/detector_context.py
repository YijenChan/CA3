"""Evidence-preserving local causal contexts for preliminary Detector nodes."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from typing import Any


class CausalContextIndex:
    """Index one PG once, then answer bounded forward/backward seed queries."""

    def __init__(self, edges: Sequence[dict[str, Any]]) -> None:
        self.edges = list(edges)
        self.forward: dict[bytes, list[int]] = defaultdict(list)
        self.backward: dict[bytes, list[int]] = defaultdict(list)
        for index, edge in enumerate(self.edges):
            self.forward[edge["src_uuid"]].append(index)
            self.backward[edge["dst_uuid"]].append(index)
        for adjacency in (self.forward, self.backward):
            for indices in adjacency.values():
                indices.sort(
                    key=lambda index: (
                        self.edges[index]["first_timestamp_ns"],
                        self.edges[index]["src_uuid"],
                        self.edges[index]["dst_uuid"],
                        self.edges[index]["event_type"],
                    )
                )

    def query(self, seed: bytes, *, hops: int, edge_budget: int) -> list[dict[str, Any]]:
        if hops < 1 or edge_budget < 1:
            raise ValueError("hops and edge_budget must be positive")
        queue = deque((("forward", seed, 1), ("backward", seed, 1)))
        visited_nodes = {"forward": {seed}, "backward": {seed}}
        visited_edges: set[tuple[str, int]] = set()
        output = []
        while queue and len(output) < edge_budget:
            direction, node_uuid, hop = queue.popleft()
            adjacency = self.forward if direction == "forward" else self.backward
            for edge_index in adjacency.get(node_uuid, []):
                marker = (direction, edge_index)
                if marker in visited_edges:
                    continue
                visited_edges.add(marker)
                edge = self.edges[edge_index]
                output.append({**edge, "traversal_direction": direction, "hop": hop})
                if len(output) >= edge_budget:
                    break
                next_uuid = edge["dst_uuid"] if direction == "forward" else edge["src_uuid"]
                if hop < hops and next_uuid not in visited_nodes[direction]:
                    visited_nodes[direction].add(next_uuid)
                    queue.append((direction, next_uuid, hop + 1))
        return output

    def query_neighbor_covering(
        self,
        seed: bytes,
        *,
        hops: int,
        edge_budget: int,
        priority_event_types: set[str] | None = None,
        neighbor_scores: Mapping[bytes, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Cover distinct one-hop neighbors in both directions before deeper evidence."""
        if hops < 1 or edge_budget < 1:
            raise ValueError("hops and edge_budget must be positive")
        directions = (
            ("forward", self.forward.get(seed, [])),
            ("backward", self.backward.get(seed, [])),
        )
        priority_event_types = priority_event_types or set()
        neighbor_scores = neighbor_scores or {}
        priority_representatives: dict[str, list[int]] = {}
        representatives: dict[str, list[int]] = {}
        remaining: dict[str, list[int]] = {}
        for direction, indices in directions:
            by_neighbor: dict[bytes, list[int]] = defaultdict(list)
            for edge_index in indices:
                edge = self.edges[edge_index]
                neighbor = edge["dst_uuid"] if direction == "forward" else edge["src_uuid"]
                by_neighbor[neighbor].append(edge_index)
            priority_first = []
            regular_first = []
            rest = []
            for neighbor_indices in by_neighbor.values():
                prioritized = [
                    index
                    for index in neighbor_indices
                    if self.edges[index]["event_type"] in priority_event_types
                ]
                chosen = prioritized[0] if prioritized else neighbor_indices[0]
                if prioritized:
                    priority_first.append(chosen)
                else:
                    regular_first.append(chosen)
                rest.extend(index for index in neighbor_indices if index != chosen)

            def sort_key(index: int, current_direction: str = direction) -> tuple[Any, ...]:
                edge = self.edges[index]
                neighbor = edge["dst_uuid"] if current_direction == "forward" else edge["src_uuid"]
                return (
                    -neighbor_scores.get(neighbor, float("-inf")),
                    edge["first_timestamp_ns"],
                    edge["src_uuid"],
                    edge["dst_uuid"],
                    edge["event_type"],
                )

            priority_representatives[direction] = sorted(priority_first, key=sort_key)
            representatives[direction] = sorted(regular_first, key=sort_key)
            rest.sort(key=sort_key)
            remaining[direction] = rest

        output = []
        used = set()

        def interleave(groups: dict[str, list[int]]) -> None:
            positions = {direction: 0 for direction in groups}
            while len(output) < edge_budget:
                advanced = False
                for direction in ("forward", "backward"):
                    position = positions[direction]
                    if position >= len(groups[direction]):
                        continue
                    edge_index = groups[direction][position]
                    positions[direction] += 1
                    advanced = True
                    if edge_index in used:
                        continue
                    used.add(edge_index)
                    output.append(
                        {
                            **self.edges[edge_index],
                            "traversal_direction": direction,
                            "hop": 1,
                        }
                    )
                    if len(output) >= edge_budget:
                        return
                if not advanced:
                    return

        interleave(priority_representatives)
        interleave(representatives)
        interleave(remaining)
        if len(output) >= edge_budget or hops == 1:
            return output
        for edge in self.query(seed, hops=hops, edge_budget=edge_budget):
            marker = (
                edge["src_uuid"],
                edge["dst_uuid"],
                edge["event_type"],
                edge["first_timestamp_ns"],
            )
            existing = {
                (
                    item["src_uuid"],
                    item["dst_uuid"],
                    item["event_type"],
                    item["first_timestamp_ns"],
                )
                for item in output
            }
            if marker in existing:
                continue
            output.append(edge)
            if len(output) >= edge_budget:
                break
        return output
