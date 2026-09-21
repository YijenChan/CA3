"""Deterministic Detector evidence selection for the frozen CA3 v7 design."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

EvidenceRole = Literal["anchor", "context_carrier"]


@dataclass(frozen=True)
class EvidenceCandidate:
    """One scored entity record from a single provenance graph."""

    pg_id: str
    entity_id: str
    percentile: float
    stable_tie_id: str


@dataclass(frozen=True)
class EvidenceSelectionConfig:
    context_threshold: float
    anchor_threshold: float
    max_entities_per_pg: int
    pg_fraction: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.context_threshold <= 1.0:
            raise ValueError("context_threshold must be in [0, 1]")
        if not self.context_threshold < self.anchor_threshold <= 1.0:
            raise ValueError("anchor_threshold must exceed context_threshold and be at most 1")
        if self.max_entities_per_pg < 1:
            raise ValueError("max_entities_per_pg must be positive")
        if not 0.0 < self.pg_fraction <= 1.0:
            raise ValueError("pg_fraction must be in (0, 1]")


@dataclass(frozen=True)
class SelectedEvidence:
    pg_id: str
    entity_id: str
    percentile: float
    role: EvidenceRole
    rank_within_pg: int
    pg_budget: int


def select_evidence(
    candidates: Iterable[EvidenceCandidate],
    config: EvidenceSelectionConfig,
) -> tuple[SelectedEvidence, ...]:
    """Apply the v7 threshold-then-budget policy independently in each PG.

    ``candidates`` must contain every scoreable entity in each represented PG so
    that the budget uses the true PG entity count. A PG with no entity above the
    context threshold contributes no selected evidence.
    """

    grouped: dict[str, list[EvidenceCandidate]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        if not 0.0 <= candidate.percentile <= 1.0:
            raise ValueError(f"invalid percentile for {candidate.entity_id}")
        key = (candidate.pg_id, candidate.entity_id)
        if key in seen:
            raise ValueError(f"duplicate entity record: {candidate.pg_id}/{candidate.entity_id}")
        seen.add(key)
        grouped[candidate.pg_id].append(candidate)

    selected: list[SelectedEvidence] = []
    for pg_id in sorted(grouped):
        rows = grouped[pg_id]
        budget = min(
            config.max_entities_per_pg,
            math.ceil(config.pg_fraction * len(rows)),
        )
        eligible = [row for row in rows if row.percentile >= config.context_threshold]
        eligible.sort(key=lambda row: (-row.percentile, row.stable_tie_id, row.entity_id))
        for rank, row in enumerate(eligible[:budget], start=1):
            role: EvidenceRole = (
                "anchor" if row.percentile >= config.anchor_threshold else "context_carrier"
            )
            selected.append(
                SelectedEvidence(
                    pg_id=pg_id,
                    entity_id=row.entity_id,
                    percentile=row.percentile,
                    role=role,
                    rank_within_pg=rank,
                    pg_budget=budget,
                )
            )
    return tuple(selected)
