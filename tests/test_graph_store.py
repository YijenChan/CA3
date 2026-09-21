from __future__ import annotations

import tomllib
from pathlib import Path

from ca3.graph_store import build_day_boundaries, logical_day, phase_by_day

PROTOCOL = Path(__file__).parents[1] / "configs" / "e3_cadets_protocol.toml"


def load_protocol() -> dict:
    with PROTOCOL.open("rb") as stream:
        return tomllib.load(stream)


def test_logical_day_uses_edt_boundary() -> None:
    protocol = load_protocol()
    days, boundaries = build_day_boundaries(protocol)
    assert logical_day(boundaries[0], days, boundaries) == 2
    assert logical_day(boundaries[1] - 1, days, boundaries) == 2
    assert logical_day(boundaries[1], days, boundaries) == 3


def test_phase_mapping_covers_every_logical_day() -> None:
    protocol = load_protocol()
    mapping = phase_by_day(protocol)
    assert mapping[2] == "fit"
    assert mapping[5] == "calibration"
    assert mapping[6] == "development"
    assert mapping[7] == "context"
    assert mapping[12] == "locked_test"
    assert set(mapping) == set(range(2, 14))
