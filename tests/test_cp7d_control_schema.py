import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]


def test_cp7d_control_example_validates() -> None:
    schema = json.loads((ROOT / "schemas/cp7d/control.schema.json").read_text())
    example = json.loads((ROOT / "schemas/cp7d/examples/control.minimal.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(example)
