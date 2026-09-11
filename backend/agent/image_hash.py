"""Perceptual image hash for near-duplicate receipt detection.

An 8×8 difference-hash (dHash): resize the greyscale image to 9×8, emit one bit per adjacent
horizontal pixel pair (left brighter than right?), giving a 64-bit fingerprint. Robust to
small crops, rescale and mild rotation — so the *same receipt photographed twice*, or one
resubmitted with a single field edited, lands within a few Hamming bits of the original, which
an exact field-match `duplicate` rule misses.

Pure Pillow (already a dependency via the synthetic generator) — no `imagehash` package.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

_HASH_SIZE = 8  # → 64-bit hash


def dhash(image: bytes | str | Path, size: int = _HASH_SIZE) -> Optional[int]:
    """Return the dHash of an image as an int (``size*size`` bits), or ``None`` if unreadable.

    Accepts raw bytes or a path. Unreadable input returns ``None`` rather than raising — a
    corrupt upload should degrade to "no fingerprint", not crash the extract endpoint.
    """
    from PIL import Image

    try:
        if isinstance(image, bytes):
            img = Image.open(io.BytesIO(image))
        else:
            img = Image.open(image)
        img = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    except Exception:
        return None
    px = img.tobytes()      # row-major, one byte per pixel (mode "L")
    bits = 0
    for row in range(size):
        base = row * (size + 1)
        for col in range(size):
            bits = (bits << 1) | int(px[base + col] > px[base + col + 1])
    return bits


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two hashes (their perceptual distance)."""
    return (a ^ b).bit_count()
