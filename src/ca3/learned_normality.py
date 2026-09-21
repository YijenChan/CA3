"""Lightweight learned-normality utilities for CP6-D1."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pyarrow as pa

from ca3.detector_features import ENTITY_TYPES

TEMPORAL_COLUMNS = ("span_ratio", "mean_gap_ratio", "max_gap_ratio")


def feature_matrix(table: pa.Table, *, event_types: Sequence[str]) -> tuple[np.ndarray, list[str]]:
    """Materialize only the manuscript-declared type/action/time inputs."""
    type_ids = table.column("entity_type_id").combine_chunks().to_numpy()
    one_hot = np.eye(len(ENTITY_TYPES), dtype=np.float32)[type_ids]
    actions_column = table.column("action_distribution").combine_chunks()
    actions = actions_column.values.to_numpy().reshape(table.num_rows, len(event_types))
    temporal = np.column_stack(
        [table.column(name).combine_chunks().to_numpy() for name in TEMPORAL_COLUMNS]
    ).astype(np.float32, copy=False)
    matrix = np.concatenate((one_hot, actions, temporal), axis=1).astype(np.float32, copy=False)
    if not np.isfinite(matrix).all():
        raise ValueError("Detector feature matrix contains non-finite values")
    names = (
        [f"type:{name}" for name in ENTITY_TYPES]
        + [f"action:{name}" for name in event_types]
        + [f"temporal:{name}" for name in TEMPORAL_COLUMNS]
    )
    return matrix, names


def calibration_percentiles(reference_scores: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """Return the empirical benign CDF; larger values are more anomalous."""
    ordered = np.sort(np.asarray(reference_scores, dtype=np.float64))
    if ordered.size == 0:
        raise ValueError("Calibration scores cannot be empty")
    return np.searchsorted(ordered, scores, side="right") / ordered.size


def pg_minmax_scores(pg_ids: Sequence[str], scores: np.ndarray) -> np.ndarray:
    """Reproduce the manuscript's within-PG min-max score deterministically."""
    ids = np.asarray(pg_ids)
    _, inverse = np.unique(ids, return_inverse=True)
    minima = np.full(inverse.max() + 1, np.inf, dtype=np.float64)
    maxima = np.full(inverse.max() + 1, -np.inf, dtype=np.float64)
    np.minimum.at(minima, inverse, scores)
    np.maximum.at(maxima, inverse, scores)
    denominator = maxima[inverse] - minima[inverse]
    return np.divide(
        scores - minima[inverse],
        denominator,
        out=np.zeros_like(scores, dtype=np.float64),
        where=denominator > 0,
    )


def pg_top_fraction_mask(
    pg_ids: Sequence[str], scores: np.ndarray, *, fraction: float
) -> np.ndarray:
    """Select a fixed top fraction inside every PG with deterministic tie breaks."""
    if not 0 < fraction <= 1:
        raise ValueError("PG candidate fraction must be in (0, 1]")
    ids = np.asarray(pg_ids)
    scores = np.asarray(scores)
    selected = np.zeros(len(scores), dtype=bool)
    _, inverse = np.unique(ids, return_inverse=True)
    for group in range(inverse.max() + 1):
        indices = np.flatnonzero(inverse == group)
        keep = max(1, int(np.ceil(len(indices) * fraction)))
        order = np.lexsort((indices, -scores[indices]))
        selected[indices[order[:keep]]] = True
    return selected


def top_standardized_deviations(
    standardized_row: np.ndarray, feature_names: Sequence[str], *, limit: int = 5
) -> list[dict[str, float | str]]:
    order = np.argsort(np.abs(standardized_row))[::-1][:limit]
    return [
        {"feature": feature_names[index], "standardized_deviation": float(standardized_row[index])}
        for index in order
    ]
