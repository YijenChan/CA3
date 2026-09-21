"""Small, versioned ATT&CK retrieval adapter for CA3 semantic context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson

TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class AttackTechnique:
    technique_id: str
    name: str
    tactics: tuple[str, ...]
    description: str
    stix_id: str
    modified: str


def _external_id(obj: dict[str, Any]) -> str | None:
    for reference in obj.get("external_references", []):
        value = reference.get("external_id", "")
        if re.fullmatch(r"T\d{4}(?:\.\d{3})?", value):
            return value
    return None


def load_enterprise_techniques(path: Path) -> tuple[str, list[AttackTechnique]]:
    bundle = orjson.loads(path.read_bytes())
    collection = next(obj for obj in bundle["objects"] if obj.get("type") == "x-mitre-collection")
    version = str(collection["x_mitre_version"])
    techniques = []
    for obj in bundle["objects"]:
        technique_id = _external_id(obj) if obj.get("type") == "attack-pattern" else None
        if not technique_id or obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        techniques.append(
            AttackTechnique(
                technique_id=technique_id,
                name=obj["name"],
                tactics=tuple(
                    sorted(phase["phase_name"] for phase in obj.get("kill_chain_phases", []))
                ),
                description=obj.get("description", ""),
                stix_id=obj["id"],
                modified=obj["modified"],
            )
        )
    return version, sorted(techniques, key=lambda value: value.technique_id)


def retrieve_techniques(
    query: str, techniques: list[AttackTechnique], *, top_k: int = 5
) -> list[tuple[AttackTechnique, int]]:
    query_tokens = set(TOKEN.findall(query.lower()))
    ranked = []
    for technique in techniques:
        name_tokens = set(TOKEN.findall(technique.name.lower()))
        tactic_tokens = set(TOKEN.findall(" ".join(technique.tactics).replace("-", " ")))
        description_tokens = set(TOKEN.findall(technique.description.lower()))
        score = (
            4 * len(query_tokens & name_tokens)
            + 2 * len(query_tokens & tactic_tokens)
            + len(query_tokens & description_tokens)
        )
        if score:
            ranked.append((technique, score))
    ranked.sort(key=lambda pair: (-pair[1], pair[0].technique_id))
    return ranked[:top_k]


def compact_record(technique: AttackTechnique, score: int) -> dict[str, object]:
    return {
        "technique_id": technique.technique_id,
        "name": technique.name,
        "tactics": list(technique.tactics),
        "stix_id": technique.stix_id,
        "modified": technique.modified,
        "retrieval_score": score,
    }
