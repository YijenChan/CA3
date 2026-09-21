from __future__ import annotations

import copy
import tomllib
from pathlib import Path

import pytest

from ca3.protocol import validate_primary_split

PROTOCOL = Path(__file__).parents[1] / "configs" / "e3_cadets_protocol.toml"


def load_protocol() -> dict:
    with PROTOCOL.open("rb") as stream:
        return tomllib.load(stream)


def test_frozen_protocol_is_valid() -> None:
    validate_primary_split(load_protocol())


def test_overlapping_days_are_rejected() -> None:
    protocol = copy.deepcopy(load_protocol())
    protocol["ca3_primary_split"]["calibration_days"] = [4]
    with pytest.raises(ValueError, match="overlap"):
        validate_primary_split(protocol)


def test_identity_feature_is_rejected() -> None:
    protocol = copy.deepcopy(load_protocol())
    protocol["ca3_primary_split"]["feature_policy"]["allow_raw_uuid_as_model_feature"] = True
    with pytest.raises(ValueError, match="unsafe feature-policy"):
        validate_primary_split(protocol)


def test_locked_label_selection_is_rejected() -> None:
    protocol = copy.deepcopy(load_protocol())
    protocol["label_policy"]["use_locked_labels_for_model_selection"] = True
    with pytest.raises(ValueError, match="unsafe label-policy"):
        validate_primary_split(protocol)
