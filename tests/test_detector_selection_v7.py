import pytest

from ca3.detector_selection import (
    EvidenceCandidate,
    EvidenceSelectionConfig,
    select_evidence,
)


def _config() -> EvidenceSelectionConfig:
    return EvidenceSelectionConfig(0.80, 0.95, 2, 0.50)


def test_benign_pg_can_emit_no_evidence() -> None:
    rows = [
        EvidenceCandidate("pg", "a", 0.20, "a"),
        EvidenceCandidate("pg", "b", 0.79, "b"),
    ]
    assert select_evidence(rows, _config()) == ()


def test_threshold_precedes_budget_and_roles_are_separate() -> None:
    rows = [
        EvidenceCandidate("pg", "a", 0.99, "a"),
        EvidenceCandidate("pg", "b", 0.90, "b"),
        EvidenceCandidate("pg", "c", 0.85, "c"),
        EvidenceCandidate("pg", "d", 0.10, "d"),
    ]
    selected = select_evidence(rows, _config())
    assert [(row.entity_id, row.role) for row in selected] == [
        ("a", "anchor"),
        ("b", "context_carrier"),
    ]
    assert all(row.pg_budget == 2 for row in selected)


def test_stable_id_breaks_equal_score_ties() -> None:
    rows = [
        EvidenceCandidate("pg", "entity-z", 0.90, "b"),
        EvidenceCandidate("pg", "entity-a", 0.90, "a"),
    ]
    config = EvidenceSelectionConfig(0.80, 0.95, 1, 1.0)
    assert select_evidence(rows, config)[0].entity_id == "entity-a"


def test_duplicate_entity_is_rejected() -> None:
    row = EvidenceCandidate("pg", "a", 0.90, "a")
    with pytest.raises(ValueError, match="duplicate entity"):
        select_evidence([row, row], _config())
