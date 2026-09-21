"""Build reusable per-PG tensors and deterministic Leiden communities."""

from __future__ import annotations

import argparse
import hashlib
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any

import igraph as ig
import leidenalg
import numpy as np
import orjson
import pyarrow as pa
import pyarrow.parquet as pq

from ca3.detector_features import ENTITY_TYPES
from ca3.graph_store import write_json_atomic
from ca3.learned_normality import feature_matrix
from ca3.paths import require_d_drive


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def contiguous_slices(values: list[str]) -> dict[str, slice]:
    result = {}
    start = 0
    for index in range(1, len(values) + 1):
        if index == len(values) or values[index] != values[start]:
            key = values[start]
            if key in result:
                raise ValueError(f"PG rows are not contiguous: {key}")
            result[key] = slice(start, index)
            start = index
    return result


def graph_arrays(
    node_table: pa.Table,
    edge_table: pa.Table,
    *,
    event_types: list[str],
    resolution: float,
    community_seed: int,
) -> dict[str, Any]:
    x, _ = feature_matrix(node_table, event_types=event_types)
    uuids = node_table.column("node_uuid").to_pylist()
    index = {node_uuid: position for position, node_uuid in enumerate(uuids)}
    undirected: dict[tuple[int, int], int] = defaultdict(int)
    for row in edge_table.select(["src_uuid", "dst_uuid", "event_count"]).to_pylist():
        source = index.get(row["src_uuid"])
        target = index.get(row["dst_uuid"])
        if source is None or target is None or source == target:
            continue
        key = (min(source, target), max(source, target))
        undirected[key] += row["event_count"]
    pairs = sorted(undirected)
    weights = np.asarray([np.log1p(undirected[pair]) for pair in pairs], dtype=np.float32)
    edge_index = np.asarray(pairs, dtype=np.int32).T if pairs else np.empty((2, 0), dtype=np.int32)
    graph = ig.Graph(n=len(uuids), edges=pairs, directed=False)
    if pairs:
        partition = leidenalg.find_partition(
            graph,
            leidenalg.RBConfigurationVertexPartition,
            weights=weights.tolist(),
            resolution_parameter=resolution,
            seed=community_seed,
        )
        communities = np.asarray(partition.membership, dtype=np.int32)
    else:
        communities = np.arange(len(uuids), dtype=np.int32)
    return {
        "x": x,
        "node_uuid": np.frombuffer(b"".join(uuids), dtype=np.uint8).reshape(-1, 16),
        "edge_index": edge_index,
        "edge_weight": weights,
        "community": communities,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--feature-store", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--days", type=int, nargs="*")
    args = parser.parse_args()
    config_path = require_d_drive(args.config)
    feature_store = require_d_drive(args.feature_store)
    with config_path.open("rb") as stream:
        config = tomllib.load(stream)
    output_dir = require_d_drive(args.output_dir or Path(config["experiment"]["cache_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = orjson.loads((feature_store / "manifest.json").read_bytes())
    results = []
    requested = set(args.days) if args.days else None
    for day in manifest["day_results"]:
        logical_day = day["logical_day"]
        if requested is not None and logical_day not in requested:
            continue
        day_dir = output_dir / f"day-{logical_day:02d}"
        day_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = day_dir / "checkpoint.json"
        if checkpoint.exists():
            saved = orjson.loads(checkpoint.read_bytes())
            if saved.get("complete"):
                results.append(saved)
                print(f"day {logical_day}: resume", flush=True)
                continue
        nodes = pq.read_table(feature_store / day["node_file"])
        edges = pq.read_table(feature_store / day["edge_file"])
        node_slices = contiguous_slices(nodes.column("pg_id").to_pylist())
        edge_slices = contiguous_slices(edges.column("pg_id").to_pylist())
        pg_results = []
        for position, (pg_id, node_slice) in enumerate(node_slices.items()):
            edge_slice = edge_slices.get(pg_id, slice(0, 0))
            arrays = graph_arrays(
                nodes.slice(node_slice.start, node_slice.stop - node_slice.start),
                edges.slice(edge_slice.start, edge_slice.stop - edge_slice.start),
                event_types=manifest["event_types"],
                resolution=config["community"]["resolution"],
                community_seed=config["community"]["seed"],
            )
            file_name = f"pg-{position:04d}.npz"
            np.savez_compressed(day_dir / file_name, **arrays)
            pg_results.append(
                {
                    "pg_id": pg_id,
                    "file": file_name,
                    "nodes": arrays["x"].shape[0],
                    "edges": arrays["edge_index"].shape[1],
                    "communities": int(arrays["community"].max()) + 1,
                }
            )
        result = {
            "complete": True,
            "logical_day": logical_day,
            "phase": day["phase"],
            "pg_count": len(pg_results),
            "node_instances": sum(item["nodes"] for item in pg_results),
            "undirected_edges": sum(item["edges"] for item in pg_results),
            "communities": sum(item["communities"] for item in pg_results),
            "pgs": pg_results,
        }
        write_json_atomic(checkpoint, result)
        results.append(result)
        print(f"day {logical_day}: {len(pg_results)} PGs", flush=True)
    cache_manifest = {
        "checkpoint": config["experiment"]["checkpoint"],
        "complete": all(item["complete"] for item in results),
        "config_sha256": sha256(config_path),
        "feature_manifest_sha256": sha256(feature_store / "manifest.json"),
        "event_types": manifest["event_types"],
        "entity_types": list(ENTITY_TYPES),
        "community": config["community"],
        "days": results,
    }
    write_json_atomic(output_dir / "manifest.json", cache_manifest)


if __name__ == "__main__":
    main()
