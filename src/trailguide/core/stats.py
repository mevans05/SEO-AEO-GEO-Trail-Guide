"""Small statistics helpers used by the dark-traffic and decay models.

Deliberately stdlib-only and deliberately modest: these support correlation and
trend claims that are always reported with their sample size and fit quality, so
a weak relationship is visible as a weak relationship rather than laundered into
a confident number.
"""

from __future__ import annotations

from statistics import fmean
from typing import Sequence


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation coefficient, or ``None`` when it is undefined."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x, mean_y = fmean(xs), fmean(ys)
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    numerator = sum(a * b for a, b in zip(dx, dy))
    denom_x = sum(a * a for a in dx) ** 0.5
    denom_y = sum(b * b for b in dy) ** 0.5
    if denom_x == 0 or denom_y == 0:
        return None
    return numerator / (denom_x * denom_y)


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float] | None:
    """Ordinary least squares fit, returning ``(slope, intercept)``."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x, mean_y = fmean(xs), fmean(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    return slope, mean_y - slope * mean_x


def trend_ratio(values: Sequence[float], window: int = 3) -> float | None:
    """Ratio of the last ``window`` periods to the preceding ``window``.

    A value below 1 means decline. Used by the decay analyzer to separate pages
    that are genuinely losing ground from normal month-to-month noise.
    """
    if len(values) < window * 2:
        return None
    recent = sum(values[-window:])
    prior = sum(values[-window * 2 : -window])
    if prior <= 0:
        return None
    return recent / prior


def weighted_mean(pairs: Sequence[tuple[float, float]]) -> float:
    """Weighted mean of ``(value, weight)`` pairs; 0.0 when all weights are zero."""
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in pairs) / total_weight


def percentile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile of ``values`` for ``fraction`` in ``[0, 1]``."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)
