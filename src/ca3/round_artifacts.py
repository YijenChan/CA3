"""D-drive-only, hash-addressed middleware persistence for CA3 investigation rounds."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import orjson

from ca3.paths import require_d_drive

ROUND_FILES = {
    "campaign_snapshot": "campaign_snapshot.json",
    "scheduled_coi": "scheduled_coi.json",
    "retrieved_communities": "retrieved_communities.json",
    "lead_proposal_raw": "lead_proposal.raw.json",
    "lead_proposal_validated": "lead_proposal.validated.json",
    "assistant_task": "assistant_task.json",
    "assistant_verdict_raw": "assistant_verdict.raw.json",
    "assistant_verdict_validated": "assistant_verdict.validated.json",
    "resolved_witnesses": "resolved_witnesses.json",
    "witness_certificates": "witness_certificates.json",
    "ic_assessment": "ic_assessment.json",
    "frontiers": "frontiers.json",
    "control_action": "control_action.json",
    "ledger_delta": "ledger_delta.json",
    "backbone_before": "backbone_before.json",
    "backbone_after": "backbone_after.json",
    "scope_request": "scope_request.json",
    "usage_latency": "usage_latency.json",
}


def _encoded(value: Any) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n"


def _write_once(path: Path, value: Any) -> str:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite frozen artifact: {path}")
    payload = _encoded(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


class RoundArtifactWriter:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = require_d_drive(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def write_run_manifest(self, manifest: Mapping[str, Any]) -> Path:
        path = self.run_dir / "manifest.json"
        _write_once(path, dict(manifest))
        return path

    def write_round(self, round_index: int, bundle: Mapping[str, Any]) -> Path:
        missing = sorted(set(ROUND_FILES) - set(bundle))
        extra = sorted(set(bundle) - set(ROUND_FILES))
        if missing or extra:
            raise ValueError(f"round bundle mismatch: missing={missing}, extra={extra}")
        round_dir = self.run_dir / "rounds" / f"round_{round_index:03d}"
        if round_dir.exists():
            raise FileExistsError(f"round already exists: {round_dir}")
        round_dir.mkdir(parents=True)
        hashes = {
            key: _write_once(round_dir / filename, bundle[key])
            for key, filename in ROUND_FILES.items()
        }
        _write_once(
            round_dir / "round_manifest.json",
            {"round_index": round_index, "files": ROUND_FILES, "sha256": hashes},
        )
        return round_dir
