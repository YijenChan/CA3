"""Build the immutable, resumable E3-CADETS graph store."""

from __future__ import annotations

import argparse
from pathlib import Path

from ca3.graph_store import build_store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--semantics", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100_000)
    parser.add_argument("--compression-level", type=int, default=6)
    parser.add_argument("--max-shards", type=int)
    parser.add_argument("--max-records-per-shard", type=int)
    args = parser.parse_args()
    manifest = build_store(
        protocol_path=args.protocol,
        semantics_path=args.semantics,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
        compression_level=args.compression_level,
        max_shards=args.max_shards,
        max_records_per_shard=args.max_records_per_shard,
    )
    print(
        f"complete={manifest['complete']} records={manifest['record_count']:,} "
        f"events={manifest['event_count']:,} nodes={manifest['node_definition_count']:,}",
        flush=True,
    )


if __name__ == "__main__":
    main()
