"""Resumable construction of the immutable CA3 Parquet graph store."""

from __future__ import annotations

import bisect
import hashlib
import re
import tomllib
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import orjson
import pyarrow as pa
import pyarrow.parquet as pq

from ca3.cdm18 import datum_type
from ca3.graph_schema import (
    EVENT_SCHEMA,
    NODE_SCHEMA,
    event_row,
    json_bytes,
    load_directions,
    node_row,
    schema_fingerprint,
)
from ca3.paths import require_d_drive
from ca3.protocol import PRIMARY_PHASES, validate_primary_split

PART_RE = re.compile(r"^(?P<base>.+\.json)(?:\.(?P<part>\d+))?$")


def shard_key(path: Path) -> tuple[str, int]:
    match = PART_RE.match(path.name)
    if match is None:
        return path.name, 0
    return match.group("base"), int(match.group("part") or 0)


def build_day_boundaries(protocol: dict[str, Any]) -> tuple[list[int], list[int]]:
    first_day, last_day = protocol["dataset"]["day_graph_range"]
    offset = protocol["dataset"]["reference_window_utc_offset_hours"]
    logical_timezone = timezone(timedelta(hours=offset))
    days = list(range(first_day, last_day + 1))
    boundaries = [
        int(datetime(2018, 4, day, tzinfo=logical_timezone).timestamp() * 1_000_000_000)
        for day in days
    ]
    final = datetime(2018, 4, last_day, tzinfo=logical_timezone) + timedelta(days=1)
    boundaries.append(int(final.timestamp() * 1_000_000_000))
    return days, boundaries


def logical_day(timestamp_ns: int | None, days: list[int], boundaries: list[int]) -> int | None:
    if timestamp_ns is None:
        return None
    index = bisect.bisect_right(boundaries, timestamp_ns) - 1
    return days[index] if 0 <= index < len(days) else None


def phase_by_day(protocol: dict[str, Any]) -> dict[int, str]:
    split = protocol["ca3_primary_split"]
    mapping = {}
    for key in PRIMARY_PHASES:
        phase = key.removesuffix("_days")
        for day in split[key]:
            if day in mapping:
                raise ValueError(f"logical day {day} belongs to multiple phases")
            mapping[day] = phase
    return mapping


def schema_with_metadata(schema: pa.Schema, table_name: str) -> pa.Schema:
    return schema.with_metadata(
        {
            b"ca3.schema_version": b"1",
            b"ca3.table": table_name.encode(),
            b"ca3.evidence_reference": b"raw_shard+raw_line+raw_offset",
        }
    )


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(json_bytes(value))
    temporary.replace(path)


class BufferedParquetWriter:
    def __init__(
        self,
        path: Path,
        schema: pa.Schema,
        *,
        batch_size: int,
        compression_level: int,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.temporary = path.with_suffix(path.suffix + ".tmp")
        self.schema = schema
        self.batch_size = batch_size
        self.rows: list[dict[str, Any]] = []
        self.count = 0
        self.writer = pq.ParquetWriter(
            self.temporary,
            schema,
            compression="zstd",
            compression_level=compression_level,
            use_dictionary=True,
            write_statistics=True,
        )

    def append(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        if len(self.rows) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self.rows:
            return
        table = pa.Table.from_pylist(self.rows, schema=self.schema)
        self.writer.write_table(table, row_group_size=self.batch_size)
        self.count += len(self.rows)
        self.rows.clear()

    def close(self) -> None:
        self.flush()
        if self.count == 0:
            self.writer.write_table(pa.Table.from_pylist([], schema=self.schema))
        self.writer.close()
        self.temporary.replace(self.path)

    def abort(self) -> None:
        self.writer.close()
        if self.temporary.exists():
            self.temporary.unlink()


def process_shard(
    path: Path,
    *,
    shard_id: int,
    output_dir: Path,
    protocol: dict[str, Any],
    directions: dict[str, str],
    default_direction: str,
    batch_size: int,
    compression_level: int,
    max_records: int | None = None,
) -> dict[str, Any]:
    days, boundaries = build_day_boundaries(protocol)
    phases = phase_by_day(protocol)
    event_schema = schema_with_metadata(EVENT_SCHEMA, "events")
    node_schema = schema_with_metadata(NODE_SCHEMA, "node_definitions")
    event_path = output_dir / "events" / f"shard-{shard_id:03d}.parquet"
    node_path = output_dir / "nodes" / f"shard-{shard_id:03d}.parquet"
    event_writer = BufferedParquetWriter(
        event_path,
        event_schema,
        batch_size=batch_size,
        compression_level=compression_level,
    )
    node_writer = BufferedParquetWriter(
        node_path,
        node_schema,
        batch_size=batch_size,
        compression_level=compression_level,
    )

    record_types: Counter[str] = Counter()
    event_types: Counter[str] = Counter()
    directions_seen: Counter[str] = Counter()
    days_seen: Counter[int] = Counter()
    records = 0
    complete = True
    source_digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            byte_offset = 0
            for line_number, line in enumerate(stream, start=1):
                if max_records is not None and records >= max_records:
                    complete = False
                    break
                source_digest.update(line)
                record = orjson.loads(line)
                record_type, body = datum_type(record)
                records += 1
                record_types[record_type] += 1
                if record_type == "Event":
                    event_type = str(body.get("type"))
                    direction = directions.get(event_type, default_direction)
                    timestamp_ns = body.get("timestampNanos")
                    timestamp_ns = timestamp_ns if isinstance(timestamp_ns, int) else None
                    day = logical_day(timestamp_ns, days, boundaries)
                    phase = phases.get(day) if day is not None else None
                    event_writer.append(
                        event_row(
                            body,
                            direction=direction,
                            logical_day=day,
                            phase=phase,
                            raw_shard=shard_id,
                            raw_line=line_number,
                            raw_offset=byte_offset,
                        )
                    )
                    event_types[event_type] += 1
                    directions_seen[direction] += 1
                    if day is not None:
                        days_seen[day] += 1
                else:
                    row = node_row(
                        record_type,
                        body,
                        raw_shard=shard_id,
                        raw_line=line_number,
                        raw_offset=byte_offset,
                    )
                    if row is not None:
                        node_writer.append(row)
                byte_offset += len(line)
        event_writer.close()
        node_writer.close()
    except BaseException:
        event_writer.abort()
        node_writer.abort()
        raise

    return {
        "schema_version": 1,
        "source_name": path.name,
        "source_bytes": path.stat().st_size,
        "source_sha256": source_digest.hexdigest() if complete else None,
        "raw_shard": shard_id,
        "complete": complete,
        "records": records,
        "events": event_writer.count,
        "node_definitions": node_writer.count,
        "record_types": dict(record_types.most_common()),
        "event_types": dict(event_types.most_common()),
        "flow_directions": dict(directions_seen.most_common()),
        "logical_day_events": {str(day): count for day, count in sorted(days_seen.items())},
        "event_file": event_path.relative_to(output_dir).as_posix(),
        "event_bytes": event_path.stat().st_size,
        "node_file": node_path.relative_to(output_dir).as_posix(),
        "node_bytes": node_path.stat().st_size,
    }


def build_store(
    *,
    protocol_path: Path,
    semantics_path: Path,
    output_dir: Path,
    batch_size: int = 100_000,
    compression_level: int = 6,
    max_shards: int | None = None,
    max_records_per_shard: int | None = None,
) -> dict[str, Any]:
    protocol_path = require_d_drive(protocol_path)
    semantics_path = require_d_drive(semantics_path)
    output_dir = require_d_drive(output_dir)
    with protocol_path.open("rb") as stream:
        protocol = tomllib.load(stream)
    validate_primary_split(protocol)
    directions, default_direction = load_directions(semantics_path)
    raw_dir = require_d_drive(Path(protocol["dataset"]["raw_dir"]))
    shards = sorted(raw_dir.glob("*.json*"), key=shard_key)
    if max_shards is not None:
        shards = shards[:max_shards]

    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir / "checkpoints"
    summaries = []
    for shard_id, path in enumerate(shards):
        checkpoint_path = checkpoint_dir / f"shard-{shard_id:03d}.json"
        event_path = output_dir / "events" / f"shard-{shard_id:03d}.parquet"
        node_path = output_dir / "nodes" / f"shard-{shard_id:03d}.parquet"
        if checkpoint_path.exists() and event_path.exists() and node_path.exists():
            checkpoint = orjson.loads(checkpoint_path.read_bytes())
            if checkpoint.get("complete") and checkpoint.get("source_name") == path.name:
                print(f"[{shard_id + 1}/{len(shards)}] resume {path.name}", flush=True)
                summaries.append(checkpoint)
                continue
        print(f"[{shard_id + 1}/{len(shards)}] build {path.name}", flush=True)
        summary = process_shard(
            path,
            shard_id=shard_id,
            output_dir=output_dir,
            protocol=protocol,
            directions=directions,
            default_direction=default_direction,
            batch_size=batch_size,
            compression_level=compression_level,
            max_records=max_records_per_shard,
        )
        write_json_atomic(checkpoint_path, summary)
        summaries.append(summary)

    manifest = {
        "schema_version": 1,
        "dataset": protocol["dataset"]["name"],
        "created_utc": datetime.now(UTC).isoformat(),
        "protocol": protocol_path.as_posix(),
        "semantics": semantics_path.as_posix(),
        "event_schema_sha256": schema_fingerprint(EVENT_SCHEMA),
        "node_schema_sha256": schema_fingerprint(NODE_SCHEMA),
        "complete": len(summaries) == len(shards) and all(item["complete"] for item in summaries),
        "shard_count": len(summaries),
        "record_count": sum(item["records"] for item in summaries),
        "event_count": sum(item["events"] for item in summaries),
        "node_definition_count": sum(item["node_definitions"] for item in summaries),
        "event_bytes": sum(item["event_bytes"] for item in summaries),
        "node_bytes": sum(item["node_bytes"] for item in summaries),
        "shards": summaries,
    }
    write_json_atomic(output_dir / "manifest.json", manifest)
    return manifest
