"""Detector-only evaluation separated from downstream label refinement."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import pyarrow as pa

REQUIRED_SCORE_COLUMNS = {
    "pg_id",
    "start_ns",
    "end_ns",
    "node_uuid",
    "variant",
    "score",
    "is_candidate",
}


def validate_score_table(scores: pa.Table) -> None:
    missing = REQUIRED_SCORE_COLUMNS - set(scores.column_names)
    if missing:
        raise ValueError(f"score table is missing required columns: {sorted(missing)}")


def evaluate_detector_scores(
    scores: pa.Table,
    *,
    labels: set[bytes],
    attack_start_ns: int,
    attack_end_ns: int,
    recall_budgets: Sequence[int],
) -> dict[str, Any]:
    """Evaluate preliminary Detector output without downstream refinement."""
    validate_score_table(scores)
    variants: dict[str, dict[bytes, dict[str, Any]]] = defaultdict(dict)
    records_in_window: dict[str, int] = defaultdict(int)
    for row in scores.to_pylist():
        if row["end_ns"] <= attack_start_ns or row["start_ns"] >= attack_end_ns:
            continue
        node_uuid = row["node_uuid"]
        if not isinstance(node_uuid, bytes):
            continue
        variant = row["variant"]
        records_in_window[variant] += 1
        current = variants[variant].get(node_uuid)
        if current is None or row["score"] > current["score"]:
            variants[variant][node_uuid] = {
                "score": row["score"],
                "is_candidate": bool(row["is_candidate"])
                or bool(current and current["is_candidate"]),
            }
        elif row["is_candidate"]:
            current["is_candidate"] = True

    results = {}
    for variant, nodes in sorted(variants.items()):
        candidates = {node_uuid for node_uuid, value in nodes.items() if value["is_candidate"]}
        covered = labels & candidates
        unmatched = candidates - labels
        precision = len(covered) / len(candidates) if candidates else 0.0
        recall = len(covered) / len(labels) if labels else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        ranked = sorted(nodes, key=lambda node_uuid: (-nodes[node_uuid]["score"], node_uuid))
        rank = {node_uuid: index for index, node_uuid in enumerate(ranked, start=1)}
        label_ranks = {
            node_uuid.hex(): rank[node_uuid] for node_uuid in labels if node_uuid in rank
        }
        recall_at_budget = {}
        for budget in recall_budgets:
            top = set(ranked[:budget])
            recall_at_budget[str(budget)] = len(labels & top) / len(labels) if labels else 0.0
        label_percentiles = {
            node_uuid.hex(): 1.0 - ((rank[node_uuid] - 1) / max(len(ranked), 1))
            for node_uuid in labels
            if node_uuid in rank
        }
        results[variant] = {
            "scoreable_unique_nodes": len(nodes),
            "score_records_in_window": records_in_window[variant],
            "unique_preliminary_candidates": len(candidates),
            "covered_label_count": len(covered),
            "covered_labels": sorted(node_uuid.hex() for node_uuid in covered),
            "compatibility_unmatched_candidates": len(unmatched),
            "compatibility_precision": precision,
            "label_recall": recall,
            "compatibility_f1": f1,
            "label_ranks": label_ranks,
            "label_score_percentiles": label_percentiles,
            "recall_at_unique_node_budget": recall_at_budget,
        }
    return {
        "evaluation_stage": "detector_only",
        "attack_start_ns": attack_start_ns,
        "attack_end_ns": attack_end_ns,
        "label_count": len(labels),
        "metric_warning": (
            "Compatibility precision treats unmatched Orthrus candidates as false positives even "
            "though the labels are not exhaustive benign annotations."
        ),
        "variants": results,
    }
