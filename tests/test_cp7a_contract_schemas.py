import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" / "cp7a"
CP7C_SCHEMA_ROOT = ROOT / "schemas" / "cp7c"


def _load(relative_path: str) -> dict:
    return json.loads((SCHEMA_ROOT / relative_path).read_text(encoding="utf-8"))


def _assert_valid(schema_name: str, example_name: str) -> None:
    schema = _load(schema_name)
    instance = _load(f"examples/{example_name}")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(instance)


def test_fmg_example_matches_contract() -> None:
    _assert_valid("fmg.schema.json", "fmg.minimal.json")


def test_investigation_example_matches_contract() -> None:
    _assert_valid("investigation.schema.json", "investigation.minimal.json")


def test_lead_example_matches_contract() -> None:
    _assert_valid("agent_io.schema.json", "lead.minimal.json")


def test_assistant_example_matches_contract() -> None:
    _assert_valid("agent_io.schema.json", "assistant.minimal.json")


def test_example_fmg_edges_have_known_endpoints_and_witnesses() -> None:
    fmg = _load("examples/fmg.minimal.json")
    community_ids = {community["community_id"] for community in fmg["communities"]}
    evidence_ids = {
        ref["evidence_id"] for community in fmg["communities"] for ref in community["evidence_refs"]
    }

    for edge in fmg["edges"]:
        assert edge["src"] in community_ids
        assert edge["dst"] in community_ids
        assert edge["witness_refs"]
        assert {ref["evidence_id"] for ref in edge["witness_refs"]} <= evidence_ids


def test_cp7c_ledger_examples_match_contract() -> None:
    schema = json.loads((CP7C_SCHEMA_ROOT / "ledger.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for name in ("ledger_event.minimal.json", "snapshot.minimal.json"):
        instance = json.loads((CP7C_SCHEMA_ROOT / "examples" / name).read_text(encoding="utf-8"))
        validator.validate(instance)
