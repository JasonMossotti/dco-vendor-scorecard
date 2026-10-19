"""The three methods behind every detector: a robust trend, a drift test on a residual, and a fleet hazard fit.

Standard library only. Each is small enough to check by hand.
"""

from __future__ import annotations

import math
from statistics import median


def theil_sen(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Robust line through the points: the median of every pairwise slope, and the median intercept.

    A single outlier or a one-day dip barely moves it, unlike a least-squares fit.
    """
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i]) for i in range(n) for j in range(i + 1, n) if xs[j] != xs[i]]
    s = median(slopes) if slopes else 0.0
    return s, median(y - s * x for x, y in zip(xs, ys))


def robust_sigma(values: list[float], floor: float = 0.0) -> float:
    """Scatter from the median absolute deviation (1.4826 x MAD estimates a normal standard deviation)."""
    if not values:
        return floor
    m = median(values)
    return max(floor, 1.4826 * median(abs(v - m) for v in values))


def days_to_level(now: float, slope_per_day: float, level: float, bad: int = 1) -> float | None:
    """Days until a straight-line trend reaches ``level``, moving in the ``bad`` direction (+1 up, -1 down).

    0 if it is already there; None if the trend is flat or moving away.
    """
    gap, rate = bad * (level - now), bad * slope_per_day
    if gap <= 0:
        return 0.0
    return gap / rate if rate > 0 else None


def cusum_step(s: float, residual: float, k: float) -> float:
    """One step of a one-sided (upward) CUSUM: it accumulates residuals beyond the allowance k."""
    return max(0.0, s + residual - k)


def weibull_fit(times: list[float], failed: list[bool], entry: list[float] | None = None) -> dict[str, float] | None:
    """Maximum-likelihood Weibull fit with right censoring (units still running count as survivors) and
    left truncation (``entry``: each unit's age when observation began, so failures before the data
    started are not mistaken for a quiet early life).

    Returns shape (beta) and scale (eta) in the units of ``times``. beta below 1 means early-life
    failures, about 1 random failures, above 1 wear-out.
    """
    t = [max(x, 1e-9) for x in times]
    a = [max(min(x, y), 0.0) for x, y in zip(entry, t)] if entry else [0.0] * len(t)
    r = sum(failed)
    if r < 3:
        return None
    lnf = sum(math.log(x) for x, f in zip(t, failed) if f) / r

    def g(beta: float) -> float:
        num = sum(math.pow(x, beta) * math.log(x) - (math.pow(y, beta) * math.log(y) if y > 0 else 0.0) for x, y in zip(t, a))
        den = sum(math.pow(x, beta) - math.pow(y, beta) for x, y in zip(t, a))
        return num / den - 1.0 / beta - lnf

    lo, hi = 0.05, 20.0
    if g(lo) > 0 or g(hi) < 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if g(mid) < 0 else (lo, mid)
    beta = (lo + hi) / 2
    eta = math.pow(sum(math.pow(x, beta) - math.pow(y, beta) for x, y in zip(t, a)) / r, 1.0 / beta)
    return {"beta": beta, "eta": eta, "failures": r, "units": len(t)}


def weibull_conditional(fit: dict[str, float], age: float, horizon: float) -> float:
    """Probability a unit of this age fails within the horizon, given it has survived so far."""
    b, e = fit["beta"], fit["eta"]
    return 1.0 - math.exp(math.pow(age / e, b) - math.pow((age + horizon) / e, b))
