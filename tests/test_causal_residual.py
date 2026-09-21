import numpy as np
import pyarrow as pa

from ca3.causal_residual import (
    causal_signature_arrays,
    fit_grouped_joint_residuals,
    grouped_joint_residual_scores,
    residual_calibration,
)


def test_causal_signature_keeps_incoming_and_outgoing_context_separate():
    a, b = b"a" * 16, b"b" * 16
    nodes = pa.table(
        {
            "node_uuid": pa.array([a, b], type=pa.binary(16)),
            "entity_type_id": [0, 1],
            "action_distribution": [[1.0, 0.0], [0.0, 1.0]],
            "subject_count": [1, 0],
            "predicate_count": [0, 1],
            "predicate2_count": [0, 0],
            "span_ratio": [0.1, 0.2],
            "mean_gap_ratio": [0.01, 0.02],
            "max_gap_ratio": [0.03, 0.04],
            "event_count": [1, 1],
            "in_degree": [0, 1],
            "out_degree": [1, 0],
            "unique_neighbor_count": [1, 1],
        }
    )
    edges = pa.table(
        {
            "src_uuid": pa.array([a], type=pa.binary(16)),
            "dst_uuid": pa.array([b], type=pa.binary(16)),
            "event_type": ["READ"],
            "event_count": [2],
        }
    )
    context, target, context_names, target_names = causal_signature_arrays(
        nodes, edges, event_types=["READ", "WRITE"]
    )
    assert context.shape == (2, 36)
    assert target.shape == (2, 12)
    assert context[0, context_names.index("outgoing_relation:READ")] == 1.0
    assert context[1, context_names.index("incoming_relation:READ")] == 1.0
    assert target[0, target_names.index("behavior:READ")] == 1.0


def test_residual_calibration_has_positive_scale_for_constant_coordinates():
    _, scale = residual_calibration(np.ones((4, 3), dtype=np.float32))
    assert np.all(scale > 0)


def test_grouped_joint_residual_is_additively_decomposed():
    calibration = np.array([[0.0, 0.0], [1.0, 0.5], [-1.0, -0.5]], dtype=np.float32)
    groups = np.zeros(3, dtype=np.int8)
    models = fit_grouped_joint_residuals(calibration, groups)
    scores, contributions = grouped_joint_residual_scores(calibration, groups, models)
    assert np.allclose(scores, contributions.sum(axis=1))
    assert scores[0] <= scores[1]
