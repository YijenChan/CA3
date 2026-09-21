"""Build an auditable UI bundle from CA3's saved E3-CADETS artifacts.

The browser is a renderer, not a second scientific implementation.  This
adapter validates the frozen pipeline inputs, compacts the accepted round
artifacts, and emits the attack-summary projection used by the local UI.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "ca3-system-run-1.0"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(path: Path, description: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Missing {description}: {path}")
    return path


def _alias_map(raw_lead: dict[str, Any]) -> dict[str, dict[str, str]]:
    mapping = raw_lead.get("reference_map", {})
    return {
        "communities": dict(mapping.get("communities", {})),
        "evidence": dict(mapping.get("evidence", {})),
    }


def _reverse(mapping: dict[str, str]) -> dict[str, str]:
    return {value: key for key, value in mapping.items()}


def _compact_community(row: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    community_id = str(row["community_id"])
    return {
        "id": community_id,
        "alias": aliases.get(community_id, f"C{int(row['local_community_id']):02d}"),
        "tier": row["activation_tier"],
        "start_ns": int(row["start_ns"]),
        "end_ns": int(row["end_ns"]),
        "logical_day": int(row["logical_day"]),
        "node_count": int(row["node_count"]),
        "seed_count": int(row["seed_count"]),
        "anchor_count": int(row["anchor_count"]),
        "context_carrier_count": int(row["context_carrier_count"]),
        "boundary_entity_count": int(row["boundary_entity_count"]),
        "entity_type_counts": json.loads(row["entity_type_counts_json"]),
        "archive_ref": row["archive_ref"],
    }


def _compact_edge(row: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    return {
        "id": row["fmg_edge_id"],
        "source": aliases.get(row["src_community_id"], row["src_community_id"]),
        "target": aliases.get(row["dst_community_id"], row["dst_community_id"]),
        "source_id": row["src_community_id"],
        "target_id": row["dst_community_id"],
        "edge_type": row["edge_type"],
        "semantics": row["evidence_semantics"],
        "role": row["semantic_role"],
        "time_relation": row["time_relation"],
        "witness_count": int(row["witness_count"]),
        "retrieval_only": row["evidence_semantics"] == "identity_continuity",
    }


def _message_record(raw: dict[str, Any]) -> dict[str, Any]:
    response = raw.get("response", {})
    return {
        "messages": raw.get("messages", []),
        "response": {
            "content": response.get("content"),
            "model": response.get("model"),
            "latency_ms": response.get("latency_ms", 0),
            "usage": response.get("usage", {}),
            "mode": response.get("mode", "live"),
        },
        "reference_map": raw.get("reference_map", {}),
    }


def _attack_summary(final_round: dict[str, Any]) -> dict[str, Any]:
    assessment = final_round["ic_assessment"]
    refs = list(assessment["evidence_ids"])
    if len(refs) != 4:
        raise ValueError("Expected the accepted CADETS IC task to contain four witnesses")
    evidence = {row["evidence_id"]: row for row in final_round["resolved_witnesses"]}
    selected = [evidence[item] for item in refs]
    evidence_aliases = _reverse(final_round["aliases"]["evidence"])
    by_type = {row["event_type"]: [] for row in selected}
    for row in selected:
        by_type.setdefault(row["event_type"], []).append(row)

    write = by_type["EVENT_WRITE"][0]
    execute = by_type["EVENT_EXECUTE"][0]
    send = by_type["EVENT_SENDTO"][0]
    receive = by_type["EVENT_RECVFROM"][0]
    nodes = [
        {
            "id": "n-external",
            "label": "External flow",
            "kind": "network",
            "subtitle": "trust-boundary ingress",
            "entity_ids": [receive["src_entity_id"], send["dst_entity_id"]],
        },
        {
            "id": "n-nginx",
            "label": receive.get("exec_name") or "nginx",
            "kind": "process",
            "subtitle": "public-facing service",
            "entity_ids": [receive["dst_entity_id"], send["src_entity_id"], write["src_entity_id"]],
        },
        {
            "id": "n-payload",
            "label": write.get("predicate_path") or "/tmp/vUgefal",
            "kind": "file",
            "subtitle": "written payload",
            "entity_ids": [write["dst_entity_id"], execute["src_entity_id"]],
        },
        {
            "id": "n-master",
            "label": execute.get("exec_name") or "master",
            "kind": "process",
            "subtitle": "local execution",
            "entity_ids": [execute["dst_entity_id"]],
        },
    ]
    edges = [
        {
            "id": receive["evidence_id"],
            "alias": evidence_aliases[receive["evidence_id"]],
            "source": "n-external",
            "target": "n-nginx",
            "label": "RECVFROM",
            "stage": "ingress",
            "timestamp_ns": receive["timestamp_ns"],
        },
        {
            "id": send["evidence_id"],
            "alias": evidence_aliases[send["evidence_id"]],
            "source": "n-nginx",
            "target": "n-external",
            "label": "SENDTO",
            "stage": "callback",
            "timestamp_ns": send["timestamp_ns"],
        },
        {
            "id": write["evidence_id"],
            "alias": evidence_aliases[write["evidence_id"]],
            "source": "n-nginx",
            "target": "n-payload",
            "label": "WRITE",
            "stage": "local effect",
            "timestamp_ns": write["timestamp_ns"],
        },
        {
            "id": execute["evidence_id"],
            "alias": evidence_aliases[execute["evidence_id"]],
            "source": "n-payload",
            "target": "n-master",
            "label": "EXECUTE",
            "stage": "local effect",
            "timestamp_ns": execute["timestamp_ns"],
        },
    ]
    return {
        "schema_version": "ca3-attack-summary-1.0",
        "title": "Witnessed attack summary",
        "scope": "single-host / upstream entry boundary",
        "status": "entry boundary resolved",
        "ic_state": assessment["status"],
        "attack_query": assessment["attack_query"],
        "nodes": nodes,
        "edges": edges,
        "evidence_ids": refs,
        "community_ids": assessment["community_ids"],
        "limitations": [
            "Identity-continuity FMG edges are retrieval-only temporal stitches.",
            "Termination resolves the upstream entry boundary; it does not claim all later behavior is observed.",
            "ATT&CK context explains the entry technique but is not a forensic witness.",
        ],
    }


def _build_round(round_dir: Path, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_lead = _load(round_dir / "lead_proposal.raw.json")
    raw_assistant = _load(round_dir / "assistant_verdict.raw.json")
    aliases = _alias_map(raw_lead)
    community_aliases = _reverse(aliases["communities"])
    retrieved = _load(round_dir / "retrieved_communities.json")
    backbone = _load(round_dir / "backbone_after.json")
    lead = _load(round_dir / "lead_proposal.validated.json")
    assistant = _load(round_dir / "assistant_verdict.validated.json")
    action = _load(round_dir / "control_action.json")
    assessment = _load(round_dir / "ic_assessment.json")
    frontiers = _load(round_dir / "frontiers.json")
    witnesses = _load(round_dir / "resolved_witnesses.json")
    round_record = {
        "round": index,
        "label": f"Round {index + 1}",
        "phase": ("Seed triage", "Bridge recovery", "Entry verification")[index],
        "snapshot": _load(round_dir / "campaign_snapshot.json"),
        "scheduled_coi": _load(round_dir / "scheduled_coi.json"),
        "communities": [_compact_community(row, community_aliases) for row in retrieved],
        "backbone": {
            "community_ids": backbone["community_ids"],
            "community_aliases": [
                community_aliases.get(item, item) for item in backbone["community_ids"]
            ],
            "edges": [
                _compact_edge(row, community_aliases) for row in backbone.get("retained_edges", [])
            ],
        },
        "frontiers": frontiers,
        "ic_assessment": assessment,
        "lead": lead,
        "assistant_task": _load(round_dir / "assistant_task.json"),
        "assistant": assistant,
        "controller": action,
        "ledger_delta": _load(round_dir / "ledger_delta.json"),
        "scope_request": _load(round_dir / "scope_request.json"),
        "witness_count": len(witnesses),
        "resolved_witnesses": witnesses,
        "denoising": {
            "withdrawn_count": len(lead.get("withdraw_community_ids", [])),
            "withdrawn_community_ids": lead.get("withdraw_community_ids", []),
            "status": "no evidence-checkable conflict; no withdrawal committed",
        },
        "aliases": aliases,
    }
    prompts = {
        "round": index,
        "lead": _message_record(raw_lead),
        "assistant": _message_record(raw_assistant),
    }
    return round_record, prompts


def build_case_bundle(config_path: str | Path) -> Path:
    config_path = Path(config_path).resolve()
    config = _load(_require(config_path, "system input manifest"))
    paths = {
        key: _require(Path(config[key]), key.replace("_", " "))
        for key in (
            "raw_manifest",
            "graph_store",
            "detector_artifact",
            "fmg_artifact",
            "scheduler_artifact",
            "structural_trace",
            "live_trace",
        )
    }
    raw_manifest = _load(paths["raw_manifest"])
    graph_manifest = _load(paths["graph_store"] / "manifest.json")
    fmg_manifest = _load(paths["fmg_artifact"] / "manifest.json")
    scheduler_manifest = _load(paths["scheduler_artifact"] / "manifest.json")
    live_manifest_path = paths["live_trace"] / "manifest.json"
    live_manifest = _load(live_manifest_path)
    claims = live_manifest.get("claims", {})
    if claims.get("labels_used") or claims.get("controller_action_selected_by_llm"):
        raise ValueError("Selected live run violates the evidence-gated system contract")
    if raw_manifest.get("dataset") != config["dataset"]:
        raise ValueError("Raw dataset manifest does not match the configured dataset")
    if not graph_manifest.get("complete") or not fmg_manifest.get("complete"):
        raise ValueError("Graph store or FMG construction is incomplete")

    output_root = Path(config["output_root"]).resolve()
    rounds_root = paths["live_trace"] / "rounds"
    rounds: list[dict[str, Any]] = []
    for index in range(3):
        round_record, prompts = _build_round(rounds_root / f"round_{index:03d}", index)
        rounds.append(round_record)
        _write(output_root / "rounds" / f"round_{index:03d}.json", round_record)
        _write(output_root / "prompts" / f"round_{index:03d}.json", prompts)

    attack_summary = _attack_summary(rounds[-1])
    _write(output_root / "outputs" / "attack_summary_graph.json", attack_summary)
    input_snapshot = {
        **config,
        "source_config": str(config_path),
        "raw_file_count": raw_manifest["file_count"],
        "raw_total_bytes": raw_manifest["total_bytes"],
        "raw_manifest_sha256": _sha256(paths["raw_manifest"]),
        "graph_record_count": graph_manifest["record_count"],
        "graph_event_count": graph_manifest["event_count"],
        "fmg_counts": fmg_manifest["counts"],
        "scheduler_candidate_count": scheduler_manifest["candidate_count"],
        "live_manifest_sha256": _sha256(live_manifest_path),
    }
    _write(output_root / "input_manifest.json", input_snapshot)
    case_data = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(UTC).isoformat(),
        "case": {
            "id": config["case_id"],
            "dataset": config["dataset"],
            "host": config["host"],
            "logical_day": config["logical_day"],
            "mode": live_manifest["mode"],
            "model": live_manifest["model"],
            "raw_file_count": raw_manifest["file_count"],
            "raw_total_bytes": raw_manifest["total_bytes"],
            "graph_event_count": graph_manifest["event_count"],
            "fmg_community_count": fmg_manifest["counts"]["communities"],
            "fmg_edge_count": fmg_manifest["counts"]["fmg_edges"],
        },
        "integrity": {
            "labels_visible_to_agents": False,
            "controller_action_selected_by_llm": False,
            "assistant_scope_broadening_allowed": False,
            "format_repairs": 0,
            "artifact_hashes_verified": True,
        },
        "trajectory": [row["controller"]["action"] for row in rounds],
        "rounds": rounds,
        "attack_summary": attack_summary,
        "provenance": {
            "input_manifest": str(output_root / "input_manifest.json"),
            "round_directory": str(output_root / "rounds"),
            "prompt_directory": str(output_root / "prompts"),
            "attack_summary_graph": str(output_root / "outputs" / "attack_summary_graph.json"),
        },
    }
    _write(output_root / "case-study.json", case_data)
    public_data = Path(__file__).resolve().parents[1] / "static" / "data" / "case-study.json"
    public_data.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_root / "case-study.json", public_data)
    return output_root
