"""Small stats helpers for reporting — Wilson 95% CI for proportion metrics.

Every headline metric in this project is a proportion over n independent synthetic cases
(recall, refusal, field accuracy, false-accept …), so the Wilson score interval is the
right, deterministic interval — no bootstrap resampling needed. Report as
``value [lo, hi] (n=…)`` in the write-up; intervals widen honestly at small n.
"""
import math


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials (95% by default)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3))


def fmt_prop(p: float, n: int) -> str:
    """``0.67 [0.35, 0.88] (n=9)`` — the write-up cell format."""
    k = round(p * n)
    lo, hi = wilson_ci(k, n)
    return f"{p:.2f} [{lo:.2f}, {hi:.2f}] (n={n})"


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for discordant paired outcomes.

    ``b`` and ``c`` are the off-diagonal counts.  The calculation is the exact
    two-sided binomial test under p=0.5 and requires no optional statistics package.
    """
    if b < 0 or c < 0:
        raise ValueError("McNemar discordant counts must be non-negative")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / (2**n)
    return round(min(1.0, 2 * tail), 8)
