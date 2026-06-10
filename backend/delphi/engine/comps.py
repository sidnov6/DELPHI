"""Comparable-company analysis: winsorized multiple stats and implied ranges.

Pure, deterministic functions. No I/O, no randomness, no external state.
"""

from __future__ import annotations

import math

import numpy as np

_MULTIPLE_KEYS = ("pe_fwd", "ev_ebitda", "ev_sales", "growth")


def winsorize(values: list[float], p: float = 0.05) -> list[float]:
    """Clip values at the p and 1-p quantiles (linear-interpolated).

    Args:
        values: Input values.
        p: Tail probability to clip on each side, in [0, 0.5).

    Returns:
        New list with values clipped to [quantile(p), quantile(1-p)].

    Raises:
        ValueError: If p is outside [0, 0.5).
    """
    if not 0.0 <= p < 0.5:
        raise ValueError(f"p must be in [0, 0.5), got {p}")
    if not values:
        return []
    arr = np.asarray(values, dtype=float)
    lo, hi = np.quantile(arr, [p, 1.0 - p])
    return [float(v) for v in np.clip(arr, lo, hi)]


def _valid_multiples(multiples: list[float]) -> list[float]:
    """Filter out None, NaN, and non-positive entries (negative multiples are meaningless)."""
    return [
        float(m)
        for m in multiples
        if m is not None and not math.isnan(float(m)) and float(m) > 0.0
    ]


def peer_multiple_stats(multiples: list[float]) -> dict:
    """Summary statistics of a peer multiple set after winsorization.

    Ignores None, NaN, and non-positive entries, winsorizes the remainder at
    the 5%/95% quantiles, then computes quartiles and mean.

    Args:
        multiples: Raw peer multiples (may contain None/NaN/non-positive).

    Returns:
        {"p25", "median", "p75", "mean", "n"}; stats are None when n == 0.
        n is the count of valid (pre-winsorization) observations.
    """
    valid = _valid_multiples(multiples)
    if not valid:
        return {"p25": None, "median": None, "p75": None, "mean": None, "n": 0}
    arr = np.asarray(winsorize(valid), dtype=float)
    return {
        "p25": float(np.quantile(arr, 0.25)),
        "median": float(np.quantile(arr, 0.50)),
        "p75": float(np.quantile(arr, 0.75)),
        "mean": float(arr.mean()),
        "n": len(valid),
    }


def implied_range(
    metric_value: float,
    multiples: list[float],
    net_debt: float = 0.0,
    shares_out: float = 1.0,
    is_enterprise: bool = False,
) -> dict:
    """Implied per-share value range from peer multiples applied to a metric.

    Applies the winsorized p25/median/p75 multiples to metric_value. For
    enterprise multiples (EV/EBITDA, EV/Sales) the product is an EV, so net
    debt is subtracted before dividing by shares; equity multiples (P/E)
    yield equity value directly.

    Args:
        metric_value: Company metric the multiples apply to (e.g. EBITDA, EPS base).
        multiples: Peer multiples.
        net_debt: Net debt, subtracted only when is_enterprise.
        shares_out: Shares outstanding for the per-share conversion.
        is_enterprise: Whether the multiples are enterprise-value based.

    Returns:
        {"low", "mid", "high"} per-share values from p25/median/p75.

    Raises:
        ValueError: If no valid multiples remain or shares_out is non-positive.
    """
    if shares_out <= 0:
        raise ValueError(f"shares_out must be positive, got {shares_out}")
    stats = peer_multiple_stats(multiples)
    if stats["n"] == 0:
        raise ValueError("no valid multiples to derive an implied range")

    def to_per_share(multiple: float) -> float:
        value = multiple * metric_value
        if is_enterprise:
            value -= net_debt
        return value / shares_out

    return {
        "low": to_per_share(stats["p25"]),
        "mid": to_per_share(stats["median"]),
        "high": to_per_share(stats["p75"]),
    }


def comp_table(peers: list[dict]) -> list[dict]:
    """Build a comparables table with a median summary row appended.

    Args:
        peers: Rows like {"ticker", "name", "pe_fwd", "ev_ebitda", "ev_sales",
            "growth"}; metric fields may be None/NaN.

    Returns:
        Copies of the peer rows plus a summary row (ticker="MEDIAN",
        name="Peer Median") holding the per-column median across peers,
        ignoring None/NaN (None when a column has no valid values).
    """
    rows = [dict(p) for p in peers]
    median_row: dict = {"ticker": "MEDIAN", "name": "Peer Median"}
    for key in _MULTIPLE_KEYS:
        col = [
            float(p[key])
            for p in peers
            if p.get(key) is not None and not math.isnan(float(p[key]))
        ]
        median_row[key] = float(np.median(col)) if col else None
    rows.append(median_row)
    return rows
