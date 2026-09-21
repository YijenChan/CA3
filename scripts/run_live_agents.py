"""Run live Lead/Assistant calls over a saved structural trace."""

from __future__ import annotations

import argparse
import copy
import json
import os
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import orjson

from ca3.paths import require_d_drive
from ca3.round_artifacts import ROUND_FILES, RoundArtifactWriter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def load_api_environment() -> dict[str, str]:
    """Load credentials from the process environment, never a repository file."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for live agent execution")
    return {
        "api_key": api_key,
        "api_base": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
    }


def call_json(
    *,
    api: dict[str, str],
    agent: dict[str, Any],
    messages: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "model": agent["model"],
        "messages": messages,
        "temperature": agent["temperature"],
        "max_tokens": agent["max_tokens"],
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        api["api_base"] + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + api["api_key"], "Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=agent["timeout_seconds"]) as response:
            raw = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"agent HTTP {exc.code}: {detail[:500]}") from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    content = raw["choices"][0]["message"]["content"]
    return json.loads(content), {
        "model": raw.get("model"),
        "response_id": raw.get("id"),
        "system_fingerprint": raw.get("system_fingerprint"),
        "usage": raw.get("usage", {}),
        "latency_ms": elapsed_ms,
        "content": content,
    }


def validate_lead(
    value: dict[str, Any],
    *,
    round_index: int,
    allowed_communities: set[str],
    allowed_evidence: set[str],
    available_task: dict[str, Any] | None,
) -> list[str]:
    errors = []
    required = {
        "schema_version",
        "role",
        "round",
        "assessment",
        "retain_community_ids",
        "withdraw_community_ids",
        "gaps",
        "verification_task",
        "recommended_action",
        "rationale",
    }
    if set(value) != required:
        errors.append("top-level keys do not match the required schema")
    if value.get("schema_version") != "cp8d-live-1" or value.get("role") != "lead":
        errors.append("schema_version or role is invalid")
    if value.get("round") != round_index:
        errors.append("round is invalid")
    for key in ("retain_community_ids", "withdraw_community_ids"):
        if not isinstance(value.get(key), list) or not set(value.get(key, [])).issubset(
            allowed_communities
        ):
            errors.append(f"{key} contains an unavailable community")
    task = value.get("verification_task")
    if task is not None:
        if not isinstance(task, dict) or set(task) != {"task_id", "question", "evidence_ids"}:
            errors.append("verification_task has an invalid schema")
        elif not set(task.get("evidence_ids", [])).issubset(allowed_evidence):
            errors.append("verification_task references unavailable evidence")
        elif available_task is None or task != available_task:
            errors.append("verification_task must copy the available typed task exactly")
    if value.get("recommended_action") not in {
        "retrieve_bridge",
        "extend_left",
        "terminate",
        "suspend",
        "continue",
    }:
        errors.append("recommended_action is invalid")
    return errors


def validate_assistant(
    value: dict[str, Any], *, task_id: str, allowed_evidence: set[str]
) -> list[str]:
    errors = []
    required = {
        "schema_version",
        "role",
        "task_id",
        "verdict",
        "supporting_evidence_ids",
        "conflicting_evidence_ids",
        "findings",
        "scope_complete",
    }
    if set(value) != required:
        errors.append("top-level keys do not match the required schema")
    if value.get("schema_version") != "cp8d-live-1" or value.get("role") != "assistant":
        errors.append("schema_version or role is invalid")
    if value.get("task_id") != task_id:
        errors.append("task_id is invalid")
    if value.get("verdict") not in {"supported", "refuted", "unknown"}:
        errors.append("verdict is invalid")
    for key in ("supporting_evidence_ids", "conflicting_evidence_ids"):
        if not isinstance(value.get(key), list) or not set(value.get(key, [])).issubset(
            allowed_evidence
        ):
            errors.append(f"{key} contains unavailable evidence")
    if value.get("scope_complete") is not True:
        errors.append("assistant attempted to broaden or did not complete the bounded scope")
    return errors


def repair_or_normalize(
    *,
    role: str,
    value: dict[str, Any],
    raw: dict[str, Any],
    errors: list[str],
    api: dict[str, str],
    agent: dict[str, Any],
    validator,
    validator_kwargs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not errors:
        return value, raw
    if role == "lead":
        required_schema = {
            "schema_version": "cp8d-live-1",
            "role": "lead",
            "round": validator_kwargs["round_index"],
            "assessment": "short string",
            "retain_community_ids": "array drawn only from allowed_community_ids",
            "withdraw_community_ids": "array drawn only from allowed_community_ids",
            "gaps": "array",
            "verification_task": "null or {task_id, question, evidence_ids}",
            "recommended_action": "retrieve_bridge|extend_left|terminate|suspend|continue",
            "rationale": "short string",
        }
        allowed = {
            "allowed_community_ids": sorted(validator_kwargs["allowed_communities"]),
            "allowed_evidence_ids": sorted(validator_kwargs["allowed_evidence"]),
            "available_verification_task": validator_kwargs["available_task"],
        }
    else:
        required_schema = {
            "schema_version": "cp8d-live-1",
            "role": "assistant",
            "task_id": validator_kwargs["task_id"],
            "verdict": "supported|refuted|unknown",
            "supporting_evidence_ids": "array drawn only from allowed_evidence_ids",
            "conflicting_evidence_ids": "array drawn only from allowed_evidence_ids",
            "findings": "short string",
            "scope_complete": True,
        }
        allowed = {"allowed_evidence_ids": sorted(validator_kwargs["allowed_evidence"])}
    repair_messages = [
        {
            "role": "system",
            "content": (
                "Return only one corrected JSON role output, not a repair report and not the request envelope. "
                "Use exactly the required keys and enum literals; copy allowed IDs exactly."
            ),
        },
        {
            "role": "user",
            "content": orjson.dumps(
                {
                    "validation_errors": errors,
                    "required_output_schema": required_schema,
                    **allowed,
                    "invalid_output": value,
                }
            ).decode(),
        },
    ]
    repaired, repair_raw = call_json(api=api, agent=agent, messages=repair_messages)
    repair_errors = validator(repaired, **validator_kwargs)
    raw["repair"] = repair_raw
    raw["initial_validation_errors"] = errors
    if not repair_errors:
        return repaired, raw
    raw["repair_validation_errors"] = repair_errors
    if role == "lead":
        return {
            "schema_version": "cp8d-live-1",
            "role": "lead",
            "round": validator_kwargs["round_index"],
            "assessment": "unknown_due_to_schema_failure",
            "retain_community_ids": [],
            "withdraw_community_ids": [],
            "gaps": [],
            "verification_task": None,
            "recommended_action": "continue",
            "rationale": "normalized unknown no-op",
        }, raw
    return {
        "schema_version": "cp8d-live-1",
        "role": "assistant",
        "task_id": validator_kwargs["task_id"],
        "verdict": "unknown",
        "supporting_evidence_ids": [],
        "conflicting_evidence_ids": [],
        "findings": "normalized unknown no-op",
        "scope_complete": True,
    }, raw


def main() -> None:
    args = parse_args()
    config_path = require_d_drive(args.config)
    with config_path.open("rb") as stream:
        config = tomllib.load(stream)
    source = require_d_drive(Path(config["inputs"]["structural_trace"]))
    output = require_d_drive(args.output or Path(config["output"]["directory"]))
    writer = RoundArtifactWriter(output)
    api = load_api_environment()
    agent = config["agent"]
    run_usage = []

    for round_dir in sorted((source / "rounds").iterdir()):
        round_index = int(round_dir.name.rsplit("_", 1)[1])
        bundle = {
            key: orjson.loads((round_dir / filename).read_bytes())
            for key, filename in ROUND_FILES.items()
        }
        communities = bundle["retrieved_communities"]
        evidence = bundle["resolved_witnesses"]
        community_ref = {
            row["community_id"]: f"C{index:02d}" for index, row in enumerate(communities, start=1)
        }
        evidence_ref = {
            row["evidence_id"]: f"E{index:02d}" for index, row in enumerate(evidence, start=1)
        }
        community_id = {value: key for key, value in community_ref.items()}
        evidence_id = {value: key for key, value in evidence_ref.items()}
        allowed_communities = set(community_id)
        allowed_evidence = set(evidence_id)
        expected_action = bundle["control_action"]["action"]
        compact_communities = [
            {
                "ref": community_ref[row["community_id"]],
                "start_ns": row["start_ns"],
                "end_ns": row["end_ns"],
                "node_count": row["node_count"],
                "anchor_count": row["anchor_count"],
                "context_carrier_count": row["context_carrier_count"],
                "entity_type_counts": row["entity_type_counts_json"],
            }
            for row in communities
        ]
        compact_evidence = [
            {
                **{key: value for key, value in row.items() if key != "evidence_id"},
                "ref": evidence_ref[row["evidence_id"]],
            }
            for row in evidence
        ]
        compact_certificates = [
            {
                "edge_ref": f"W{index:02d}",
                "src_ref": community_ref.get(row["src_community_id"], "outside-scope"),
                "dst_ref": community_ref.get(row["dst_community_id"], "outside-scope"),
                "edge_type": row["edge_type"],
                "evidence_semantics": row["evidence_semantics"],
                "semantic_role": row["semantic_role"],
                "witness_refs": [
                    evidence_ref[value] for value in row["witness_ids"] if value in evidence_ref
                ],
            }
            for index, row in enumerate(bundle["witness_certificates"], start=1)
        ]
        compact_snapshot = copy.deepcopy(bundle["campaign_snapshot"])
        compact_snapshot["retained_community_ids"] = [
            community_ref.get(value, "outside-scope")
            for value in compact_snapshot["retained_community_ids"]
        ]
        compact_ic = copy.deepcopy(bundle["ic_assessment"])
        compact_ic["community_ids"] = [
            community_ref.get(value, "outside-scope") for value in compact_ic["community_ids"]
        ]
        compact_ic["evidence_ids"] = [
            evidence_ref.get(value, "outside-scope") for value in compact_ic["evidence_ids"]
        ]
        available_task = None
        if compact_ic["status"] == "supported" and all(
            value != "outside-scope" for value in compact_ic["evidence_ids"]
        ):
            available_task = {
                "task_id": f"VT-IC-R{round_index}",
                "question": (
                    "Do the referenced raw events jointly witness time-ordered public-service ingress, "
                    "callback, and a local write-execute consequence?"
                ),
                "evidence_ids": compact_ic["evidence_ids"],
            }
        lead_context = {
            "campaign_snapshot": compact_snapshot,
            "communities": compact_communities,
            "witness_certificates": compact_certificates,
            "evidence": compact_evidence,
            "ic_assessment": compact_ic,
            "frontiers": bundle["frontiers"],
            "available_verification_task": available_task,
            "controller_action_is_hidden_from_agent": True,
        }
        lead_messages = [
            {
                "role": "system",
                "content": (
                    "You are the CA3 Lead investigator. Propose but never commit changes. Use only supplied IDs. "
                    "Identity continuity is a temporal stitch, not proof of an attack transition. ATT&CK is not "
                    "forensic evidence. Return exactly one JSON object with keys schema_version, role, round, "
                    "assessment, retain_community_ids, withdraw_community_ids, gaps, verification_task, "
                    "recommended_action, rationale. schema_version=cp8d-live-1, role=lead. recommended_action "
                    "must be exactly one of retrieve_bridge, extend_left, terminate, suspend, continue. "
                    "verification_task must be null when available_verification_task is null; otherwise either "
                    "copy that typed task card exactly or return null. Never invent a question or task scope. "
                    "The community and evidence IDs in your output must be the supplied short refs such as C01 "
                    "and E01, never raw UUIDs or archive IDs. Copy every ref exactly. Keep assessment and "
                    "rationale concise."
                ),
            },
            {"role": "user", "content": orjson.dumps(lead_context).decode()},
        ]
        lead, lead_raw = call_json(api=api, agent=agent, messages=lead_messages)
        lead_errors = validate_lead(
            lead,
            round_index=round_index,
            allowed_communities=allowed_communities,
            allowed_evidence=allowed_evidence,
            available_task=available_task,
        )
        lead, lead_raw = repair_or_normalize(
            role="lead",
            value=lead,
            raw=lead_raw,
            errors=lead_errors,
            api=api,
            agent=agent,
            validator=validate_lead,
            validator_kwargs={
                "round_index": round_index,
                "allowed_communities": allowed_communities,
                "allowed_evidence": allowed_evidence,
                "available_task": available_task,
            },
        )

        task = lead["verification_task"]
        assistant_messages: list[dict[str, str]] = []
        if task is None:
            assistant = {
                "schema_version": "cp8d-live-1",
                "role": "assistant",
                "task_id": "not-requested",
                "verdict": "not-requested",
                "supporting_evidence_ids": [],
                "conflicting_evidence_ids": [],
                "findings": "Lead issued no bounded verification task.",
                "scope_complete": True,
            }
            assistant_raw = {"mode": "not-requested", "usage": {}, "latency_ms": 0}
        else:
            task_evidence = [
                row for row in compact_evidence if row["ref"] in set(task["evidence_ids"])
            ]
            assistant_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the CA3 Assistant. Verify only the bounded task and supplied raw-event records; "
                        "do not infer unavailable evidence or broaden scope. Return exactly one JSON object with "
                        "keys schema_version, role, task_id, verdict, supporting_evidence_ids, "
                        "conflicting_evidence_ids, findings, scope_complete. schema_version=cp8d-live-1, "
                        "role=assistant, verdict is supported/refuted/unknown, scope_complete=true."
                        " Reference evidence only with the supplied short refs such as E01."
                    ),
                },
                {
                    "role": "user",
                    "content": orjson.dumps(
                        {"task": task, "raw_event_records": task_evidence}
                    ).decode(),
                },
            ]
            assistant, assistant_raw = call_json(api=api, agent=agent, messages=assistant_messages)
            assistant_errors = validate_assistant(
                assistant, task_id=task["task_id"], allowed_evidence=set(task["evidence_ids"])
            )
            assistant, assistant_raw = repair_or_normalize(
                role="assistant",
                value=assistant,
                raw=assistant_raw,
                errors=assistant_errors,
                api=api,
                agent=agent,
                validator=validate_assistant,
                validator_kwargs={
                    "task_id": task["task_id"],
                    "allowed_evidence": set(task["evidence_ids"]),
                },
            )

        resolved_lead = copy.deepcopy(lead)
        resolved_lead["retain_community_ids"] = [
            community_id[value] for value in lead["retain_community_ids"]
        ]
        resolved_lead["withdraw_community_ids"] = [
            community_id[value] for value in lead["withdraw_community_ids"]
        ]
        if resolved_lead["verification_task"] is not None:
            resolved_lead["verification_task"]["evidence_ids"] = [
                evidence_id[value] for value in task["evidence_ids"]
            ]
        resolved_assistant = copy.deepcopy(assistant)
        resolved_assistant["supporting_evidence_ids"] = [
            evidence_id[value] for value in assistant["supporting_evidence_ids"]
        ]
        resolved_assistant["conflicting_evidence_ids"] = [
            evidence_id[value] for value in assistant["conflicting_evidence_ids"]
        ]
        bundle["lead_proposal_raw"] = {
            "reference_map": {"communities": community_id, "evidence": evidence_id},
            "messages": lead_messages,
            "response": lead_raw,
        }
        bundle["lead_proposal_validated"] = resolved_lead
        bundle["assistant_task"] = resolved_lead["verification_task"] or {
            "task_id": "not-requested"
        }
        bundle["assistant_verdict_raw"] = {
            "messages": assistant_messages,
            "response": assistant_raw,
        }
        bundle["assistant_verdict_validated"] = resolved_assistant
        bundle["usage_latency"] = {
            "mode": "live",
            "model": agent["model"],
            "lead": {
                "usage": lead_raw.get("usage", {}),
                "latency_ms": lead_raw.get("latency_ms", 0),
            },
            "assistant": {
                "usage": assistant_raw.get("usage", {}),
                "latency_ms": assistant_raw.get("latency_ms", 0),
            },
            "agent_recommended_action": lead["recommended_action"],
            "deterministic_controller_action": expected_action,
            "recommendation_matched": lead["recommended_action"] == expected_action,
        }
        run_usage.append(bundle["usage_latency"])
        writer.write_round(round_index, bundle)

    writer.write_run_manifest(
        {
            "checkpoint": config["run"]["checkpoint"],
            "investigation_id": config["run"]["investigation_id"],
            "source_structural_trace": source.as_posix(),
            "mode": "live",
            "model": agent["model"],
            "claims": config["claims"],
            "round_usage": run_usage,
        }
    )
    print(
        orjson.dumps(
            {"output": output.as_posix(), "rounds": len(run_usage)}, option=orjson.OPT_INDENT_2
        ).decode()
    )


if __name__ == "__main__":
    main()
