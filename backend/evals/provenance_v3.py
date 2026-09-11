"""Deterministic provenance fingerprints for frozen Evaluation v3 runs."""

from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        relative = path.resolve().relative_to(ROOT)
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@lru_cache(maxsize=1)
def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@lru_cache(maxsize=1)
def source_version() -> str:
    """Hash the executable backend, dependency lock and evaluation contract.

    The Git commit records repository ancestry.  This content hash additionally identifies
    the exact working-tree source used before the evaluation changes are committed.
    """
    paths = [
        path
        for path in (ROOT / "backend").rglob("*.py")
        if not path.name.startswith("test_")
    ]
    paths.append(ROOT / "requirements.txt")
    return f"matched-v3.3-source-sha256:{_digest(paths)}"


def dataset_version(label: str, paths: list[str | Path]) -> str:
    resolved: list[Path] = []
    for raw in paths:
        path = ROOT / raw
        if path.is_dir():
            resolved.extend(item for item in path.rglob("*") if item.is_file())
        else:
            resolved.append(path)
    return f"{label}-sha256:{_digest(resolved)}"


def frozen_cache_version(path: str | Path) -> str:
    """Identify cached model output without claiming the model was called again."""
    return f"frozen-cache-sha256:{_digest([ROOT / path])}"
