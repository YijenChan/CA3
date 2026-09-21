import pyarrow as pa

from ca3.detector_evaluation import evaluate_detector_scores


def test_detector_evaluation_separates_ranking_from_candidate_threshold():
    a, b, c = b"a" * 16, b"b" * 16, b"c" * 16
    scores = pa.Table.from_pylist(
        [
            {
                "pg_id": "p1",
                "start_ns": 0,
                "end_ns": 10,
                "node_uuid": a,
                "variant": "model",
                "score": 0.9,
                "is_candidate": True,
            },
            {
                "pg_id": "p1",
                "start_ns": 0,
                "end_ns": 10,
                "node_uuid": b,
                "variant": "model",
                "score": 0.8,
                "is_candidate": False,
            },
            {
                "pg_id": "p1",
                "start_ns": 0,
                "end_ns": 10,
                "node_uuid": c,
                "variant": "model",
                "score": 0.7,
                "is_candidate": True,
            },
        ]
    )
    result = evaluate_detector_scores(
        scores,
        labels={a, b},
        attack_start_ns=0,
        attack_end_ns=10,
        recall_budgets=[1, 2],
    )["variants"]["model"]
    assert result["label_recall"] == 0.5
    assert result["recall_at_unique_node_budget"] == {"1": 0.5, "2": 1.0}
    assert result["label_ranks"][b.hex()] == 2


def test_candidate_decision_is_or_across_repeated_node_instances():
    label = b"a" * 16
    scores = pa.table(
        {
            "pg_id": ["pg-1", "pg-2"],
            "start_ns": [0, 0],
            "end_ns": [10, 10],
            "node_uuid": [label, label],
            "variant": ["model", "model"],
            "score": [0.5, 0.9],
            "is_candidate": [True, False],
        }
    )
    result = evaluate_detector_scores(
        scores,
        labels={label},
        attack_start_ns=0,
        attack_end_ns=10,
        recall_budgets=[1],
    )["variants"]["model"]
    assert result["unique_preliminary_candidates"] == 1
    assert result["label_recall"] == 1.0
