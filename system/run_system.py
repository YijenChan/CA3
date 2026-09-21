"""Command-line entry point for the local CA3 system."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SYSTEM_ROOT))

from ca3_system.pipeline import build_case_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Build CA3 UI artifacts from a saved pipeline run")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    output = build_case_bundle(args.config)
    print(json.dumps({"status": "complete", "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
