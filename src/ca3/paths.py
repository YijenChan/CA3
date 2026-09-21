"""Portable filesystem helpers for CA3.

The research workstation used a D:-drive guard to prevent accidental writes
to the system disk.  A public package must instead respect paths supplied by
the caller, so this module resolves paths without imposing a drive letter.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


def resolve_path(path: Path) -> Path:
    """Return an absolute caller-controlled path."""
    return path.expanduser().resolve()


def require_d_drive(path: Path) -> Path:
    """Backward-compatible alias retained for workstation-era configs."""
    return resolve_path(path)


@dataclass(frozen=True)
class StoragePaths:
    project_root: Path
    dataset_root: Path
    artifact_root: Path
    cache_root: Path
    temp_root: Path

    @classmethod
    def from_toml(cls, config_path: Path) -> StoragePaths:
        with config_path.open("rb") as stream:
            storage = tomllib.load(stream)["storage"]
        return cls(**{key: resolve_path(Path(value)) for key, value in storage.items()})
