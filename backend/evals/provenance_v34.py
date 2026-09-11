"""Deterministic provenance and clean-tree checks for Evaluation V3.4."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(path.resolve() for path in paths)):
        relative = path.relative_to(ROOT)
        digest.update(str(relative).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def tracked_tree_clean() -> bool:
    """Untracked personal files do not affect the sealed source; tracked edits do."""
    unstaged = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    return unstaged.returncode == 0 and staged.returncode == 0


def source_version() -> str:
    paths = [
        path for path in (ROOT / "backend").rglob("*.py")
        if not path.name.startswith("test_")
    ]
    paths.extend((ROOT / "frontend-next/src").rglob("*.ts"))
    paths.extend((ROOT / "frontend-next/src").rglob("*.tsx"))
    paths.append(ROOT / "requirements.txt")
    return f"matched-v3.4-source-sha256:{_digest(paths)}"


def dataset_version(label: str, paths: list[str | Path]) -> str:
    resolved: list[Path] = []
    for raw in paths:
        path = Path(raw)
        path = path if path.is_absolute() else ROOT / path
        if path.is_dir():
            resolved.extend(item for item in path.rglob("*") if item.is_file())
        else:
            resolved.append(path)
    return f"{label}-sha256:{_digest(resolved)}"


def frozen_cache_version(path: str | Path) -> str:
    resolved = Path(path)
    resolved = resolved if resolved.is_absolute() else ROOT / resolved
    return f"frozen-cache-sha256:{_digest([resolved])}"


def frozen_cache_bundle_version(paths: list[str | Path]) -> str:
    resolved = [
        path if (path := Path(raw)).is_absolute() else ROOT / path
        for raw in paths
    ]
    return f"frozen-cache-sha256:{_digest(resolved)}"


def file_sha256(path: str | Path) -> str:
    resolved = Path(path)
    resolved = resolved if resolved.is_absolute() else ROOT / resolved
    return hashlib.sha256(resolved.read_bytes()).hexdigest()
