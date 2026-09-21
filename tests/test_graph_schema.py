from __future__ import annotations

from ca3.graph_schema import event_row, node_row, properties_map, uuid_bytes

UUID = "269A60A2-39BE-11E8-B8CE-15D78AC88FB6"


def test_uuid_bytes_is_compact_and_case_insensitive() -> None:
    assert len(uuid_bytes(UUID)) == 16
    assert uuid_bytes(UUID) == uuid_bytes(UUID.lower())


def test_event_row_preserves_evidence_and_roles() -> None:
    body = {
        "uuid": UUID,
        "timestampNanos": 123,
        "sequence": 7,
        "type": "EVENT_READ",
        "subject": {"cdm.UUID": UUID},
        "predicateObject": {"cdm.UUID": "7D88BD7B-39C4-11E8-B8CE-15D78AC88FB6"},
        "predicateObjectPath": "/tmp/a",
        "properties": {"map": {"exec": "cat", "fd": "3"}},
    }
    row = event_row(
        body,
        direction="object_to_subject",
        logical_day=4,
        phase="fit",
        raw_shard=2,
        raw_line=99,
        raw_offset=12345,
    )
    assert row["subject_uuid"] == uuid_bytes(UUID)
    assert row["predicate_path"] == "/tmp/a"
    assert row["exec_name"] == "cat"
    assert row["raw_shard"] == 2
    assert row["raw_line"] == 99
    assert row["raw_offset"] == 12345


def test_node_row_reads_host_from_base_object() -> None:
    row = node_row(
        "FileObject",
        {"uuid": UUID, "baseObject": {"hostId": UUID}, "type": "FILE_OBJECT_FILE"},
        raw_shard=0,
        raw_line=2,
        raw_offset=42,
    )
    assert row is not None
    assert row["host_uuid"] == uuid_bytes(UUID)
    assert row["subtype"] == "FILE_OBJECT_FILE"


def test_properties_map_handles_missing_values() -> None:
    assert properties_map({}) == {}
