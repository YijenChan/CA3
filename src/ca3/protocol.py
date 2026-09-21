"""Validation helpers for the frozen CA3 dataset protocol."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

PRIMARY_PHASES = (
    "fit_days",
    "calibration_days",
    "development_days",
    "context_days",
    "locked_test_days",
)


def validate_primary_split(protocol: Mapping[str, Any]) -> None:
    dataset = protocol["dataset"]
    labels = protocol["label_policy"]
    policy = protocol["ca3_split_policy"]
    split = protocol["ca3_primary_split"]

    if policy["status"] != "frozen":
        raise ValueError("CA3 primary split must be frozen before experiments")

    unsafe_label_flags = (
        "use_labels_for_training",
        "use_labels_for_benign_calibration",
        "use_locked_labels_for_model_selection",
        "global_uuid_is_positive",
    )
    enabled_label_flags = [name for name in unsafe_label_flags if labels[name]]
    if enabled_label_flags:
        raise ValueError(f"unsafe label-policy flags enabled: {enabled_label_flags}")

    first_day, last_day = dataset["day_graph_range"]
    expected_days = set(range(first_day, last_day + 1))
    assigned: set[int] = set()
    previous_max: int | None = None

    for phase in PRIMARY_PHASES:
        days = split[phase]
        if not isinstance(days, Sequence) or isinstance(days, (str, bytes)) or not days:
            raise ValueError(f"{phase} must be a non-empty sequence")
        day_set = set(days)
        if len(day_set) != len(days):
            raise ValueError(f"{phase} contains duplicate days")
        overlap = assigned.intersection(day_set)
        if overlap:
            raise ValueError(f"split days overlap at {sorted(overlap)}")
        if previous_max is not None and min(day_set) <= previous_max:
            raise ValueError("primary phases must be strictly chronological")
        assigned.update(day_set)
        previous_max = max(day_set)

    if assigned != expected_days:
        missing = sorted(expected_days - assigned)
        extra = sorted(assigned - expected_days)
        raise ValueError(f"primary split coverage mismatch: missing={missing}, extra={extra}")

    features = split["feature_policy"]
    forbidden_flags = (
        "allow_raw_uuid_as_model_feature",
        "allow_global_node_malicious_label",
        "allow_future_events_in_features",
        "allow_cross_boundary_windows",
    )
    enabled = [name for name in forbidden_flags if features[name]]
    if enabled:
        raise ValueError(f"unsafe feature-policy flags enabled: {enabled}")
