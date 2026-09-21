from __future__ import annotations

import json
from pathlib import Path


def test_synthetic_demo_is_explicit_and_complete() -> None:
    path = Path(__file__).resolve().parents[1] / "system" / "static" / "data" / "case-study.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["case"]["mode"] == "SYNTHETIC"
    assert [item["round"] for item in data["rounds"]] == [0, 1, 2]
    assert data["rounds"][-1]["controller"]["terminal"] is True
    assert data["rounds"][-1]["frontiers"] == []
