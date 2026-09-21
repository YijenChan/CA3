"""Sequential API accounting with reservations, retained failures, and no secret logs."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


class BudgetExhausted(RuntimeError):
    pass


class MeteredAPI:
    def __init__(self, config, directory):
        self.agent = config["agent"]
        self.budget = config["budget"]
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "usage.jsonl"
        self.key = os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise ValueError("OPENAI_API_KEY is required")
        self.records = (
            [json.loads(line) for line in self.path.read_text().splitlines()]
            if self.path.exists()
            else []
        )

    @property
    def reserved_or_spent(self):
        return sum(r["accounted_cost_usd"] for r in self.records)

    def call(self, messages, tag):
        payload = {
            "model": self.agent["model"],
            "messages": messages,
            "reasoning_effort": self.agent["reasoning_effort"],
            "max_completion_tokens": self.agent["max_completion_tokens"],
            "response_format": {"type": "json_object"},
        }
        # UTF-8 bytes plus message overhead is a deliberately conservative token bound.
        bound = len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 512
        reserve = (
            bound * self.budget["input_usd_per_million"]
            + self.agent["max_completion_tokens"] * self.budget["output_usd_per_million"]
        ) / 1e6
        if self.reserved_or_spent + reserve > self.budget["max_cost_usd"]:
            raise BudgetExhausted("Cost cap reached before request reservation")
        index = len(self.records) + 1
        request = urllib.request.Request(
            self.agent["api_base"] + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
        )
        record = {
            "index": index,
            "tag": tag,
            "requested_model": self.agent["model"],
            "status": "pending",
            "accounted_cost_usd": reserve,
            "usage": None,
            "reservation_usd": reserve,
        }
        # Persist reservation first, so an interrupted request is not silently free on restart.
        self.records.append(record)
        self._rewrite()
        (self.directory / f"request-{index:05d}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        t = time.perf_counter()
        raw = {}
        try:
            with urllib.request.urlopen(request, timeout=self.agent["timeout_seconds"]) as response:
                raw = json.load(response)
            usage = raw.get("usage")
            record.update(status="response_received", returned_model=raw.get("model"), usage=usage)
            if usage:
                p = usage.get("prompt_tokens", 0)
                c = usage.get("completion_tokens", 0)
                cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                record["accounted_cost_usd"] = (
                    (p - cached) * self.budget["input_usd_per_million"]
                    + cached * self.budget["cached_input_usd_per_million"]
                    + c * self.budget["output_usd_per_million"]
                ) / 1e6
            (self.directory / f"response-{index:05d}.json").write_text(
                json.dumps(raw, indent=2), encoding="utf-8"
            )
            value = json.loads(raw["choices"][0]["message"]["content"])
            if not isinstance(value, dict):
                raise TypeError("Expected a JSON object")
            if raw["choices"][0].get("finish_reason") != "stop":
                raise ValueError("Incomplete model output")
            return value
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = re.sub(r"sk-[A-Za-z0-9_.-]+", "<redacted>", str(exc))[:500]
            raise
        finally:
            record["elapsed_seconds"] = time.perf_counter() - t
            self._rewrite()

    def _rewrite(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text("".join(json.dumps(r) + "\n" for r in self.records), encoding="utf-8")
        temporary.replace(self.path)
