"""Rebuild the gitignored synthetic receipt images used by offline verification.

The JSONL manifests are committed; the PNG files are not. This command reconstructs each
image from its recorded tier and deterministic seed, checks the generated labels against the
manifest, and verifies the image hashes used by the frozen critical-read cache.

Usage: PYTHONPATH=. python -m backend.scripts.materialize_evaluation_receipts
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from ..evals.receipt_data import TIERS, make_receipt_case

ROOT = Path(__file__).resolve().parents[2]
RECEIPT_ROOT = ROOT / "data" / "receipts"
CRITICAL_CACHE = (
    ROOT / "data" / "eval_cache" / "receipts_qwen3.6-27b_critical_v342.jsonl"
)


def _rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _suffix_index(image_name: str) -> int:
    try:
        return int(Path(image_name).stem.rsplit("_", 1)[1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError(f"receipt filename has no numeric suffix: {image_name}") from exc


def _core_seed(row: dict) -> int:
    tier = row["meta"]["tier"]
    return TIERS.index(tier) * 100 + _suffix_index(row["image"])


def _foreign_seed(row: dict) -> int:
    return _suffix_index(row["image"])


def _inconsistent_seed(row: dict) -> int:
    return TIERS.index("inconsistent") * 100 + _suffix_index(row["image"])


def _materialize(directory: Path, seed_for: Callable[[dict], int]) -> int:
    manifest = directory / "manifest.jsonl"
    rows = _rows(manifest)
    directory.mkdir(parents=True, exist_ok=True)
    for row in rows:
        tier = row["meta"]["tier"]
        image, gold, meta = make_receipt_case(tier, seed_for(row))
        if gold != row["gold"] or meta != row["meta"]:
            raise RuntimeError(f"generator does not reproduce manifest row: {row['image']}")
        image.save(directory / row["image"])
    return len(rows)


def _verify_critical_hashes() -> None:
    for row in _rows(CRITICAL_CACHE):
        path = RECEIPT_ROOT / "synthetic_v2" / row["image"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["image_sha256"]:
            raise RuntimeError(f"generated image hash does not match frozen cache: {row['image']}")


def main() -> None:
    counts = {
        "synthetic_v2": _materialize(RECEIPT_ROOT / "synthetic_v2", _core_seed),
        "foreign_currency": _materialize(
            RECEIPT_ROOT / "foreign_currency", _foreign_seed
        ),
        "inconsistent": _materialize(
            RECEIPT_ROOT / "inconsistent", _inconsistent_seed
        ),
    }
    _verify_critical_hashes()
    print(
        "materialized "
        + ", ".join(f"{name}={count}" for name, count in counts.items())
        + "; frozen hashes verified"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
