from pathlib import Path

import orjson
import pytest

from ca3.round_artifacts import ROUND_FILES, RoundArtifactWriter


def _bundle() -> dict[str, object]:
    return {key: {"kind": key} for key in ROUND_FILES}


def test_round_writer_persists_complete_hash_manifest(tmp_path: Path) -> None:
    writer = RoundArtifactWriter(tmp_path)
    round_dir = writer.write_round(0, _bundle())
    manifest = orjson.loads((round_dir / "round_manifest.json").read_bytes())
    assert manifest["round_index"] == 0
    assert set(manifest["sha256"]) == set(ROUND_FILES)


def test_round_writer_rejects_incomplete_bundle(tmp_path: Path) -> None:
    writer = RoundArtifactWriter(tmp_path)
    with pytest.raises(ValueError, match="round bundle mismatch"):
        writer.write_round(0, {"campaign_snapshot": {}})


def test_round_writer_never_overwrites(tmp_path: Path) -> None:
    writer = RoundArtifactWriter(tmp_path)
    writer.write_round(0, _bundle())
    with pytest.raises(FileExistsError):
        writer.write_round(0, _bundle())
