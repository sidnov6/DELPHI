"""Deterministic valuation pipeline.

Agents make judgments; engines make calculations. This module is the seam:
it derives DCF assumptions from the data bundle, runs the engine, and packages
typed artifacts (football field, sensitivity grid, Monte Carlo, ratios) that
both the simulation personas and the live LLM agents narrate from. No LLM here.
"""
from __future__ import annotations

from typing import Any

from ..engine import comps as comps_engine
from ..engine import dcf as dcf_engine
from ..engine import ratios as ratios_engine
from ..engine import scenarios as scenarios_engine
from .state import (
    FootballFieldBar,
    GeoExposure,
    KeyNumber,
    MapArc,
    MapRegion,
    MarketSnapshot,
    MonteCarloSummary,
    ScenarioCell,
)


def derive_assumptions(bundle: dict[str, Any]) -> dict[str, Any]:
    """Build base-case DCF assumptions from financial history + consensus."""
    fin = bundle["financials"]
    est = bundle["estimates"]
    mkt = bundle["market"]
    mac = bundle["macro"]

    latest = fin[-1]
    revenue0 = latest["revenue_b"]

    g1 = est["rev_growth_next_fy"]
    g2 = est.get("rev_growth_fy2", g1 * 0.85)
    # Geometric fade to a mature 4%; hypergrowth earns a 7-year explicit
    # window (standard treatment — the franchise doesn't evaporate in year 3).
    horizon = 7 if g1 >= 0.18 else 5
    mature = 0.04
    growth_path = [g1, g2]
    while len(growth_path) < horizon:
        growth_path.append(round(mature + (growth_path[-1] - mature) * 0.62, 4))

    margin = latest["op_margin"]
    # Carry half of any margin *expansion* trend forward (capped +1pp/yr);
    # hold compression flat rather than extrapolating a death spiral —
    # the bear-case variant is where the downside lives.
    trend = (margin - fin[0]["op_margin"]) / max(len(fin) - 1, 1)
    step = max(0.0, min(0.01, trend * 0.5))
    margin_path = [round(margin + step * i, 4) for i in range(horizon)]

    da_pct = latest["da_b"] / latest["revenue_b"]
    capex_pct = latest["capex_b"] / latest["revenue_b"]
    # Investment cycles normalize: fade capex linearly toward maintenance
    # (≈ D&A + 2.5pp) so the terminal year doesn't compound peak capex forever.
    capex_terminal = min(capex_pct, da_pct + 0.025)
    capex_path = [round(capex_pct + (capex_terminal - capex_pct) * i / max(horizon - 1, 1), 4)
                  for i in range(horizon)]
    tax_rate = 0.15 if latest.get("net_income_b", 0) > 0 else 0.21
    # Blume adjustment — betas mean-revert; raw historical beta overstates
    # the forward discount rate for high-vol names. Clamp the result: Yahoo
    # serves negative/near-zero betas (e.g. SHEL −0.25) that would price a
    # cyclical at a sub-Treasury discount rate.
    beta = round(min(2.2, max(0.6, 0.67 * (mkt.get("beta") or 1.0) + 0.33)), 3)

    return {
        "revenue0": revenue0,
        "growth_path": growth_path,
        "ebit_margin_path": margin_path,
        "tax_rate": tax_rate,
        "da_pct_revenue": round(da_pct, 4),
        "capex_pct_revenue": capex_path,
        "nwc_pct_revenue_delta": 0.02,
        "rf": mac["rf_10y"],
        "erp": mac.get("erp", 0.045),
        "beta": beta,
        "cost_of_debt": mac["rf_10y"] + 0.012,
        "debt_weight": 0.05 if mkt["net_debt_b"] < 0 else 0.15,
        "terminal_growth": 0.035,   # wide-moat megacap standard; bear case stresses to 2.5%
        "net_debt": mkt["net_debt_b"],
        "shares_out": mkt["shares_out_b"],
    }


def run_valuation(bundle: dict[str, Any]) -> dict[str, Any]:
    """Run the full deterministic stack. Returns engine-native dicts."""
    a = derive_assumptions(bundle)
    mkt = bundle["market"]
    last_price = mkt["last_price"]

    base = dcf_engine.dcf_from_assumptions(a)

    # Bear / bull DCF variants for the football field.
    # Margin shock scales with the margin base — 400bps off a 62% margin and
    # off a 4% margin are different animals.
    margin_shock = min(0.04, a["ebit_margin_path"][0] * 0.35)
    bear = dcf_engine.dcf_from_assumptions({
        **a,
        "growth_path": [g * 0.6 for g in a["growth_path"]],
        "ebit_margin_path": [m - margin_shock for m in a["ebit_margin_path"]],
        "terminal_growth": 0.025,
    })
    bull = dcf_engine.dcf_from_assumptions({
        **a,
        "growth_path": [g * 1.25 for g in a["growth_path"]],
        "ebit_margin_path": [m + 0.02 for m in a["ebit_margin_path"]],
        "terminal_growth": 0.04,
    })

    peers = bundle["peers"]
    latest = bundle["financials"][-1]
    eps_next = bundle["estimates"]["eps_next_fy"]
    pe_range = comps_engine.implied_range(
        eps_next, [p["pe_fwd"] for p in peers if p.get("pe_fwd")])
    ebitda_next = (latest["ebit_b"] + latest["da_b"]) * (1 + a["growth_path"][0])
    ev_ebitda_range = comps_engine.implied_range(
        ebitda_next, [p["ev_ebitda"] for p in peers if p.get("ev_ebitda")],
        net_debt=mkt["net_debt_b"], shares_out=mkt["shares_out_b"], is_enterprise=True)

    wacc = base["wacc"]
    wacc_values = [round(wacc + d, 4) for d in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    tg_values = [0.02, 0.025, 0.03, 0.035, 0.04]
    grid = scenarios_engine.sensitivity_grid(a, "rf", [a["rf"] + (w - wacc) for w in wacc_values],
                                             "terminal_growth", tg_values)
    # Re-key rows to the effective WACC for display.
    cells = []
    for c in grid["cells"]:
        w = round(wacc + (c["row"] - a["rf"]), 4)
        cells.append({"row": w, "col": c["col"], "value": c["value"]})

    mc = scenarios_engine.monte_carlo_dcf(a, n=2000, seed=42, last_price=last_price)
    # Normalize: expose percentiles under draws_stats for all downstream consumers.
    mc["draws_stats"] = {**mc["draws_stats"], **mc["per_share_draws_summary"]}

    analyst = bundle["estimates"]

    return {
        "assumptions": a,
        "dcf": base,
        "dcf_bear": bear,
        "dcf_bull": bull,
        "comps_pe": pe_range,
        "comps_ev_ebitda": ev_ebitda_range,
        "comp_table": comps_engine.comp_table(peers),
        "sensitivity": {"rows": wacc_values, "cols": tg_values, "cells": cells},
        "monte_carlo": mc,
        "ratios": {
            "dupont": ratios_engine.dupont(
                latest["net_income_b"], latest["revenue_b"],
                latest["total_assets_b"], latest["equity_b"]),
            "altman": ratios_engine.altman_z(
                latest["working_capital_b"], latest["retained_earnings_b"],
                latest["ebit_b"], mkt["market_cap_b"],
                latest["total_liabilities_b"], latest["revenue_b"],
                latest["total_assets_b"]),
            "piotroski": ratios_engine.piotroski_f(
                _piotroski_inputs(bundle["financials"][-1]),
                _piotroski_inputs(bundle["financials"][-2])),
        },
        "analyst_targets": {"mean": analyst["pt_mean"], "high": analyst["pt_high"], "low": analyst["pt_low"]},
        "last_price": last_price,
    }


def _piotroski_inputs(f: dict[str, Any]) -> dict[str, Any]:
    return {
        "net_income": f["net_income_b"],
        "cfo": f["cfo_b"],
        "total_assets": f["total_assets_b"],
        "long_term_debt": f["long_term_debt_b"],
        "current_assets": f["current_assets_b"],
        "current_liabilities": f["current_liabilities_b"],
        "shares_out": f.get("shares_out_b", 1.0),
        "gross_margin": f["gross_margin"],
        "revenue": f["revenue_b"],
    }


# ---------- typed artifact builders (engine dicts → Pydantic for the wire) ----------

def street_available(val: dict[str, Any]) -> bool:
    at = val.get("analyst_targets", {})
    return all(at.get(k) is not None for k in ("mean", "high", "low"))


def football_field(val: dict[str, Any]) -> list[FootballFieldBar]:
    dcf, bear, bull = val["dcf"], val["dcf_bear"], val["dcf_bull"]
    mc = val["monte_carlo"]
    bars = [
        FootballFieldBar(method="DCF (Gordon growth)", low=bear["per_share"],
                         high=bull["per_share"], mid=dcf["per_share"]),
        FootballFieldBar(method="Forward P/E comps", low=val["comps_pe"]["low"],
                         high=val["comps_pe"]["high"], mid=val["comps_pe"]["mid"]),
        FootballFieldBar(method="EV/EBITDA comps", low=val["comps_ev_ebitda"]["low"],
                         high=val["comps_ev_ebitda"]["high"], mid=val["comps_ev_ebitda"]["mid"]),
        FootballFieldBar(method="Monte Carlo p25–p75",
                         low=mc["draws_stats"]["p25"], high=mc["draws_stats"]["p75"],
                         mid=mc["draws_stats"]["p50"]),
    ]
    if street_available(val):
        at = val["analyst_targets"]
        bars.append(FootballFieldBar(method="Street targets", low=at["low"],
                                     high=at["high"], mid=at["mean"]))
    return [b for b in bars if b.low > 0 and b.high >= b.low]


def sensitivity_cells(val: dict[str, Any]) -> tuple[list[ScenarioCell], dict[str, list[float]]]:
    s = val["sensitivity"]
    cells = [ScenarioCell(row=c["row"], col=c["col"], value=c["value"] or 0.0)
             for c in s["cells"] if c["value"] is not None]
    return cells, {"rows": s["rows"], "cols": s["cols"]}


def monte_carlo_summary(val: dict[str, Any]) -> MonteCarloSummary:
    mc = val["monte_carlo"]
    st = mc["draws_stats"]
    return MonteCarloSummary(
        p5=st["p5"], p25=st["p25"], p50=st["p50"], p75=st["p75"], p95=st["p95"],
        prob_upside=mc.get("prob_upside", 0.5),
        histogram=mc["draws_histogram"]["counts"],
        bin_edges=mc["draws_histogram"]["bin_edges"],
    )


def market_snapshot(bundle: dict[str, Any]) -> MarketSnapshot:
    m = bundle["market"]
    return MarketSnapshot(
        ticker=bundle["ticker"], company=bundle["company"],
        currency=bundle.get("currency", "USD"),
        last_price=m["last_price"], market_cap_b=m.get("market_cap_b"),
        pe_fwd=m.get("pe_fwd"), ev_ebitda=m.get("ev_ebitda"),
        week52_low=m.get("week52_low"), week52_high=m.get("week52_high"),
        price_history=m.get("price_history", []), sector=bundle.get("sector"),
    )


def geo_exposure(bundle: dict[str, Any]) -> GeoExposure:
    regions = [MapRegion(**r) for r in bundle.get("geo_revenue", [])]
    arcs = [MapArc(**a) for a in bundle.get("arcs", [])]
    top = max(regions, key=lambda r: r.revenue_share) if regions else None
    commentary = ""
    if top:
        commentary = (f"{top.name} carries {top.revenue_share:.0%} of revenue; "
                      f"{len(arcs)} mapped supply/demand dependencies.")
    return GeoExposure(regions=regions, arcs=arcs, hq=tuple(bundle["hq"]) if bundle.get("hq") else None,
                       commentary=commentary)


def financial_summary(bundle: dict[str, Any], val: dict[str, Any]) -> list[KeyNumber]:
    fin = bundle["financials"]
    latest, prev = fin[-1], fin[-2]
    rev_g = latest["revenue_b"] / prev["revenue_b"] - 1
    fcf_margin = latest["fcf_b"] / latest["revenue_b"]
    alt = val["ratios"]["altman"]
    pio = val["ratios"]["piotroski"]
    return [
        KeyNumber(label="Revenue", value=f"${latest['revenue_b']:.1f}B",
                  delta=f"{rev_g:+.1%} y/y", tone="pos" if rev_g > 0 else "neg"),
        KeyNumber(label="Operating margin", value=f"{latest['op_margin']:.1%}",
                  delta=f"{(latest['op_margin'] - prev['op_margin']) * 100:+.1f}pp",
                  tone="pos" if latest["op_margin"] >= prev["op_margin"] else "neg"),
        KeyNumber(label="FCF margin", value=f"{fcf_margin:.1%}", tone="neutral"),
        KeyNumber(label="Altman Z", value=f"{alt['z']:.2f}",
                  delta=alt["zone"], tone="pos" if alt["zone"] == "safe" else "neg"),
        KeyNumber(label="Piotroski F", value=f"{pio['score']}/9",
                  tone="pos" if pio["score"] >= 6 else ("neutral" if pio["score"] >= 4 else "neg")),
        KeyNumber(label="WACC", value=f"{val['dcf']['wacc']:.1%}", tone="neutral"),
    ]
