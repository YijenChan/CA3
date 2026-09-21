"""Compact causal-signature construction and residual scoring for CP6-D4."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pyarrow as pa
from sklearn.covariance import LedoitWolf

from ca3.detector_features import ENTITY_TYPES


def _fixed_list_matrix(table: pa.Table, name: str, width: int) -> np.ndarray:
    column = table.column(name).combine_chunks()
    return column.values.to_numpy().reshape(table.num_rows, width).astype(np.float32)


def causal_signature_arrays(
    nodes: pa.Table,
    edges: pa.Table,
    *,
    event_types: Sequence[str],
) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """Build node targets and directed context without using UUID as a feature.

    The context separates incoming and outgoing relation distributions and the
    entity types found at the opposite causal endpoint.  UUIDs are used only to
    join the evidence tables.
    """
    node_count = nodes.num_rows
    action_count = len(event_types)
    entity_count = len(ENTITY_TYPES)
    uuids = nodes.column("node_uuid").to_pylist()
    index = {value: position for position, value in enumerate(uuids)}
    entity_ids = nodes.column("entity_type_id").combine_chunks().to_numpy().astype(np.int64)

    incoming_actions = np.zeros((node_count, action_count), dtype=np.float32)
    outgoing_actions = np.zeros((node_count, action_count), dtype=np.float32)
    incoming_types = np.zeros((node_count, entity_count), dtype=np.float32)
    outgoing_types = np.zeros((node_count, entity_count), dtype=np.float32)
    event_index = {name: position for position, name in enumerate(event_types)}

    for row in edges.select(["src_uuid", "dst_uuid", "event_type", "event_count"]).to_pylist():
        source = index.get(row["src_uuid"])
        target = index.get(row["dst_uuid"])
        relation = event_index.get(row["event_type"])
        if source is None or target is None or relation is None:
            continue
        weight = np.float32(np.log1p(row["event_count"]))
        outgoing_actions[source, relation] += weight
        incoming_actions[target, relation] += weight
        outgoing_types[source, entity_ids[target]] += weight
        incoming_types[target, entity_ids[source]] += weight

    def normalize_rows(values: np.ndarray) -> np.ndarray:
        denominator = values.sum(axis=1, keepdims=True)
        return np.divide(values, denominator, out=np.zeros_like(values), where=denominator > 0)

    type_one_hot = np.eye(entity_count, dtype=np.float32)[entity_ids]
    context = np.concatenate(
        [
            type_one_hot,
            normalize_rows(incoming_actions),
            normalize_rows(outgoing_actions),
            normalize_rows(incoming_types),
            normalize_rows(outgoing_types),
            np.log1p(
                np.column_stack(
                    [
                        nodes.column("in_degree").combine_chunks().to_numpy(),
                        nodes.column("out_degree").combine_chunks().to_numpy(),
                    ]
                )
            ).astype(np.float32),
        ],
        axis=1,
    )

    actions = _fixed_list_matrix(nodes, "action_distribution", action_count)
    roles = np.column_stack(
        [
            nodes.column("subject_count").combine_chunks().to_numpy(),
            nodes.column("predicate_count").combine_chunks().to_numpy(),
            nodes.column("predicate2_count").combine_chunks().to_numpy(),
        ]
    ).astype(np.float32)
    roles = normalize_rows(roles)
    temporal = np.column_stack(
        [
            nodes.column("span_ratio").combine_chunks().to_numpy(),
            nodes.column("mean_gap_ratio").combine_chunks().to_numpy(),
            nodes.column("max_gap_ratio").combine_chunks().to_numpy(),
        ]
    ).astype(np.float32)
    structure = np.log1p(
        np.column_stack(
            [
                nodes.column("event_count").combine_chunks().to_numpy(),
                nodes.column("in_degree").combine_chunks().to_numpy(),
                nodes.column("out_degree").combine_chunks().to_numpy(),
                nodes.column("unique_neighbor_count").combine_chunks().to_numpy(),
            ]
        )
    ).astype(np.float32)
    target = np.concatenate([actions, roles, temporal, structure], axis=1)

    context_names = (
        [f"self_type:{name}" for name in ENTITY_TYPES]
        + [f"incoming_relation:{name}" for name in event_types]
        + [f"outgoing_relation:{name}" for name in event_types]
        + [f"incoming_neighbor_type:{name}" for name in ENTITY_TYPES]
        + [f"outgoing_neighbor_type:{name}" for name in ENTITY_TYPES]
        + ["context:log_in_degree", "context:log_out_degree"]
    )
    target_names = (
        [f"behavior:{name}" for name in event_types]
        + ["role:subject", "role:predicate", "role:predicate2"]
        + ["temporal:span", "temporal:mean_gap", "temporal:max_gap"]
        + [
            "structure:event_count",
            "structure:in_degree",
            "structure:out_degree",
            "structure:unique_neighbors",
        ]
    )
    if not np.isfinite(context).all() or not np.isfinite(target).all():
        raise ValueError("causal signature contains non-finite values")
    return context, target, context_names, target_names


def robust_residual_scores(
    residuals: np.ndarray,
    *,
    calibration_center: np.ndarray,
    calibration_scale: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return decomposed calibrated residuals and one unweighted anomaly score."""
    standardized = np.abs(residuals - calibration_center) / calibration_scale
    return standardized.mean(axis=1), standardized


def residual_calibration(residuals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fit coordinate-wise median/MAD calibration with a stable zero-scale fallback."""
    center = np.median(residuals, axis=0)
    scale = np.median(np.abs(residuals - center), axis=0) * np.float32(1.4826)
    positive = scale[scale > 1e-6]
    fallback = float(np.median(positive)) if positive.size else 1.0
    scale = np.where(scale > 1e-6, scale, fallback).astype(np.float32)
    return center.astype(np.float32), scale


def fit_grouped_joint_residuals(
    residuals: np.ndarray, group_ids: np.ndarray
) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Fit parameter-free shrinkage covariance per entity type."""
    models = {}
    for group in np.unique(group_ids):
        selected = residuals[group_ids == group]
        estimator = LedoitWolf().fit(selected)
        models[int(group)] = (
            estimator.location_.astype(np.float32),
            estimator.precision_.astype(np.float32),
        )
    return models


def grouped_joint_residual_scores(
    residuals: np.ndarray,
    group_ids: np.ndarray,
    models: dict[int, tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """Score joint deviations and retain additive per-coordinate evidence."""
    scores = np.zeros(len(residuals), dtype=np.float64)
    contributions = np.zeros_like(residuals, dtype=np.float32)
    for group in np.unique(group_ids):
        indices = np.flatnonzero(group_ids == group)
        if int(group) not in models:
            raise ValueError(f"missing residual calibration for entity type {group}")
        center, precision = models[int(group)]
        delta = residuals[indices] - center
        whitened = delta @ precision
        contribution = delta * whitened
        contributions[indices] = contribution
        scores[indices] = contribution.sum(axis=1)
    return scores, contributions
