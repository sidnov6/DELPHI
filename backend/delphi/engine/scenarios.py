"""Scenario analysis on the DCF: sensitivity grids, tornado charts, Monte Carlo.

Deterministic given inputs (Monte Carlo is seeded). No I/O, no network.
"""

from __future__ import annotations

import numpy as np

from .dcf import dcf_from_assumptions, wacc

# Assumption keys whose tornado/grid values are additive deltas applied to
# every element of the underlying list rather than absolute replacements.
_PATH_KEYS = ("growth_path", "ebit_margin_path")


def _with_assumption(base: dict, key: str, value: float) -> dict:
    """Copy base assumptions with one key set; path keys get an additive shift."""
    a = dict(base)
    if key in _PATH_KEYS:
        a[key] = [x + value for x in base[key]]
    else:
        a[key] = value
    return a


def sensitivity_grid(
    base_assumptions: dict,
    row_key: str,
    row_values: list[float],
    col_key: str,
    col_values: list[float],
) -> dict:
    """Two-way per-share sensitivity grid over DCF assumptions.

    Reruns dcf_from_assumptions per (row, col) cell. Cells that violate the
    Gordon constraint (terminal_growth >= wacc) or otherwise raise ValueError
    are returned with value None rather than failing the grid.

    Args:
        base_assumptions: Assumptions accepted by dcf_from_assumptions.
        row_key: Assumption key varied across rows (path keys take additive deltas).
        row_values: Values for row_key.
        col_key: Assumption key varied across columns.
        col_values: Values for col_key.

    Returns:
        {"rows": row_values, "cols": col_values,
         "cells": [{"row": r, "col": c, "value": per_share | None}, ...]},
        cells in row-major order.
    """
    cells: list[dict] = []
    for r in row_values:
        for c in col_values:
            a = _with_assumption(_with_assumption(base_assumptions, row_key, r), col_key, c)
            try:
                value: float | None = dcf_from_assumptions(a)["per_share"]
            except ValueError:
                value = None  # e.g. terminal_growth >= wacc in this cell
            cells.append({"row": r, "col": c, "value": value})
    return {"rows": list(row_values), "cols": list(col_values), "cells": cells}


def tornado(
    base_assumptions: dict,
    variables: dict[str, tuple[float, float]],
) -> list[dict]:
    """One-at-a-time sensitivity of per-share value to each assumption.

    For each variable the DCF is rerun at its (low, high) setting with all
    other assumptions at base. For "growth_path"/"ebit_margin_path" the tuple
    is an additive delta applied to every element; otherwise values replace
    the assumption outright.

    Args:
        base_assumptions: Assumptions accepted by dcf_from_assumptions.
        variables: {key: (low, high)} settings to test.

    Returns:
        [{"variable", "low_value", "high_value", "base_value"}, ...] sorted by
        |high_value - low_value| descending. Values are per-share, or None for
        settings that violate the Gordon constraint.
    """
    base_value = dcf_from_assumptions(base_assumptions)["per_share"]

    def run(key: str, setting: float) -> float | None:
        try:
            return dcf_from_assumptions(_with_assumption(base_assumptions, key, setting))[
                "per_share"
            ]
        except ValueError:
            return None

    results = [
        {
            "variable": key,
            "low_value": run(key, low),
            "high_value": run(key, high),
            "base_value": base_value,
        }
        for key, (low, high) in variables.items()
    ]

    def impact(row: dict) -> float:
        if row["low_value"] is None or row["high_value"] is None:
            return float("-inf")  # unrunnable settings sort last
        return abs(row["high_value"] - row["low_value"])

    return sorted(results, key=impact, reverse=True)


def monte_carlo_dcf(
    base_assumptions: dict,
    n: int = 2000,
    seed: int = 42,
    growth_sd: float = 0.02,
    margin_sd: float = 0.02,
    wacc_sd: float = 0.005,
    tg_sd: float = 0.0025,
    last_price: float | None = None,
) -> dict:
    """Monte Carlo distribution of DCF per-share value under assumption shocks.

    Per draw, independent normal shocks: one common additive shock to every
    element of growth_path, one to every element of ebit_margin_path, an
    additive WACC shock applied by shifting rf, and an additive
    terminal_growth shock. Terminal growth is clamped to wacc - 0.005 so the
    Gordon constraint always holds. Deterministic for a given seed.

    Args:
        base_assumptions: Assumptions accepted by dcf_from_assumptions
            (CAPM inputs required; the rf-shift carries the WACC shock).
        n: Number of draws.
        seed: Seed for numpy's default_rng.
        growth_sd: Std dev of the common growth shock.
        margin_sd: Std dev of the common margin shock.
        wacc_sd: Std dev of the WACC (rf) shock.
        tg_sd: Std dev of the terminal-growth shock.
        last_price: If given, include "prob_upside" = share of draws above it.

    Returns:
        {"per_share_draws_summary": {"p5","p25","p50","p75","p95","mean"},
         "draws_histogram": {"bin_edges": [21 floats], "counts": [20 ints]},
         "draws_stats": {"n","mean","std","min","max"}}
        plus "prob_upside" when last_price is provided.

    Raises:
        ValueError: If n is not positive.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")

    rng = np.random.default_rng(seed)
    growth_shocks = rng.normal(0.0, growth_sd, n)
    margin_shocks = rng.normal(0.0, margin_sd, n)
    wacc_shocks = rng.normal(0.0, wacc_sd, n)
    tg_shocks = rng.normal(0.0, tg_sd, n)

    draws = np.empty(n)
    for i in range(n):
        a = dict(base_assumptions)
        a["growth_path"] = [g + growth_shocks[i] for g in base_assumptions["growth_path"]]
        a["ebit_margin_path"] = [
            m + margin_shocks[i] for m in base_assumptions["ebit_margin_path"]
        ]
        a["rf"] = base_assumptions["rf"] + wacc_shocks[i]
        wacc_i = wacc(
            rf=a["rf"],
            erp=a["erp"],
            beta=a["beta"],
            cost_of_debt=a["cost_of_debt"],
            tax_rate=a["tax_rate"],
            debt_weight=a["debt_weight"],
        )
        a["wacc"] = wacc_i
        # Clamp so the perpetuity stays defined even in adverse WACC draws.
        a["terminal_growth"] = min(
            base_assumptions["terminal_growth"] + tg_shocks[i], wacc_i - 0.005
        )
        draws[i] = dcf_from_assumptions(a)["per_share"]

    p5, p25, p50, p75, p95 = np.percentile(draws, [5, 25, 50, 75, 95])
    counts, bin_edges = np.histogram(draws, bins=20)
    result: dict = {
        "per_share_draws_summary": {
            "p5": float(p5),
            "p25": float(p25),
            "p50": float(p50),
            "p75": float(p75),
            "p95": float(p95),
            "mean": float(draws.mean()),
        },
        "draws_histogram": {
            "bin_edges": [float(e) for e in bin_edges],
            "counts": [int(c) for c in counts],
        },
        "draws_stats": {
            "n": n,
            "mean": float(draws.mean()),
            "std": float(draws.std(ddof=1)) if n > 1 else 0.0,
            "min": float(draws.min()),
            "max": float(draws.max()),
        },
    }
    if last_price is not None:
        result["prob_upside"] = float(np.mean(draws > last_price))
    return result
