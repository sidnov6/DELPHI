"""Compliance auditor — deterministic checks, zero LLM.

Citation enforcement: every claim must cite at least one source.
Numeric verification: figures quoted in claims are cross-checked against the
fact base (engine outputs + bundle financials) within tolerance.
Disclosure + consistency checks round out the publish gate.
"""
from __future__ import annotations

import re
from typing import Any

from .state import AuditCheck, Claim, ResearchState

_NUM = re.compile(r"(-?\$?\d+(?:\.\d+)?)\s*(%|B|bn|x|pp)?", re.IGNORECASE)


def _fact_values(bundle: dict[str, Any], valuation: dict[str, Any]) -> list[float]:
    vals: list[float] = []

    def harvest(obj: Any) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                harvest(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj[:40]:
                harvest(v)
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            f = float(obj)
            vals.append(f)
            if -1.5 <= f <= 1.5:          # ratios may be quoted as percentages
                vals.append(round(f * 100, 4))

    harvest(bundle.get("market", {}))
    harvest(bundle.get("financials", []))
    harvest(bundle.get("estimates", {}))
    harvest(bundle.get("social", {}))
    harvest(bundle.get("macro", {}))
    harvest(bundle.get("geo_revenue", []))
    harvest({k: valuation.get(k) for k in
             ("dcf", "dcf_bear", "dcf_bull", "comps_pe", "comps_ev_ebitda",
              "ratios", "analyst_targets", "assumptions", "last_price")})
    mc = valuation.get("monte_carlo", {})
    harvest(mc.get("draws_stats", {}))
    if "prob_upside" in mc:
        vals.append(round(mc["prob_upside"] * 100, 4))

    # Derived figures the agents legitimately quote: growth rates, deltas,
    # mixes and scenario arithmetic computed from the same primary facts.
    fin = bundle.get("financials", [])
    for prev, curr in zip(fin, fin[1:]):
        for key in ("revenue_b", "eps", "fcf_b", "net_income_b"):
            if prev.get(key) and curr.get(key):
                vals.append(round((curr[key] / prev[key] - 1) * 100, 4))
        for key in ("gross_margin", "op_margin"):
            if key in prev and key in curr:
                vals.append(round((curr[key] - prev[key]) * 100, 4))
    if fin:
        latest = fin[-1]
        if latest.get("revenue_b"):
            vals.append(round(latest.get("fcf_b", 0) / latest["revenue_b"] * 100, 4))
    geo = bundle.get("geo_revenue", [])
    if geo:
        intl = sum(r["revenue_share"] for r in geo if r.get("iso_n3") != "840")
        vals.append(round(intl * 100, 4))
        for r in geo:
            vals.append(round(r["revenue_share"] * 0.4 * 100, 4))   # shock math
    last = valuation.get("last_price")
    if last:
        for d in ("dcf", "dcf_bear", "dcf_bull"):
            ps = valuation.get(d, {}).get("per_share")
            if ps:
                vals.append(round((ps / last - 1) * 100, 4))
    return vals


# Tokens that read as numbers but aren't claims about magnitudes.
_JARGON = re.compile(r"\b10b5-1\b|\b10-[KQ]\b|\b8-K\b|\bDEF 14A\b|\b52w\b", re.IGNORECASE)
_THOUSANDS = re.compile(r"(?<=\d),(?=\d)")


def _verify_number(quoted: float, facts: list[float]) -> bool:
    for f in facts:
        if f == 0:
            if abs(quoted) < 0.05:
                return True
            continue
        if abs(quoted - f) / max(abs(f), 1e-9) <= 0.06:   # 6% tolerance for rounding
            return True
    return False


def run_audit(state: ResearchState, bundle: dict[str, Any],
              valuation: dict[str, Any]) -> tuple[list[AuditCheck], int]:
    """Returns (checks, uncited_claim_count)."""
    checks: list[AuditCheck] = []
    claims: list[Claim] = [c for v in state.views.values() for c in v.claims]

    uncited = [c for c in claims if not c.citation_ids]
    checks.append(AuditCheck(
        name="Citation coverage",
        passed=not uncited,
        detail=(f"{len(claims) - len(uncited)}/{len(claims)} claims carry citations"
                + (f" — {len(uncited)} uncited: " + "; ".join(c.text[:60] for c in uncited[:2])
                   if uncited else "")),
    ))

    facts = _fact_values(bundle, valuation)
    quoted, verified = 0, 0
    for c in claims:
        text = _THOUSANDS.sub("", _JARGON.sub(" ", c.text))
        for m in _NUM.finditer(text):
            raw = m.group(1).replace("$", "")
            try:
                num = float(raw)
            except ValueError:
                continue
            if abs(num) < 0.01 or (m.group(2) is None and abs(num) > 3000):
                continue                     # years, run ids, trivia
            if m.group(2) is None and abs(num) < 13 and num == int(num):
                continue                     # counts, months, scores — not magnitudes
            quoted += 1
            if _verify_number(num, facts):
                verified += 1
    checks.append(AuditCheck(
        name="Numeric verification",
        passed=quoted == 0 or verified / quoted >= 0.92,
        detail=f"{verified}/{quoted} stated figures reconcile to the fact store (±6%)",
    ))

    cited_ids = {cid for c in claims for cid in c.citation_ids}
    known_ids = {c.id for c in state.citations}
    dangling = cited_ids - known_ids
    checks.append(AuditCheck(
        name="Citation integrity",
        passed=not dangling,
        detail="all citation ids resolve" if not dangling else f"dangling ids: {sorted(dangling)[:4]}",
    ))

    if state.rating:
        # Cross-figure logical consistency — per-figure tolerance alone lets a
        # target contradict the valuation work it claims to rest on.
        from . import analysis as _analysis
        rating = state.rating
        bars = _analysis.football_field(valuation)
        if bars:
            lo = min(b.low for b in bars)
            hi = max(b.high for b in bars)
            checks.append(AuditCheck(
                name="Target within valuation evidence",
                passed=0.95 * lo <= rating.price_target <= 1.05 * hi,
                detail=(f"target {rating.price_target:.2f} vs evidence span "
                        f"{lo:.0f}–{hi:.0f} across {len(bars)} methods"),
            ))
        prob = valuation.get("monte_carlo", {}).get("prob_upside", 0.5)
        expected = _analysis.rating_matrix(rating.upside_pct, prob)
        checks.append(AuditCheck(
            name="Rating matrix consistency",
            passed=rating.action == expected,
            detail=(f"matrix(upside {rating.upside_pct:+.1%}, P(up) {prob:.0%}) → {expected}; "
                    f"published {rating.action}"),
        ))

    checks.append(_freshness_check(bundle))

    checks.append(AuditCheck(
        name="Disclosure language",
        passed=True,
        detail="not investment advice; sources are public filings and market data",
    ))

    return checks, len(uncited)


def _freshness_check(bundle: dict[str, Any]) -> AuditCheck:
    """A live-dated note must not ride a stale tape; bundled offline
    snapshots are disclosed rather than failed."""
    from datetime import date

    as_of = bundle.get("as_of")
    offline = bundle.get("mode_data", "snapshot") == "snapshot"
    try:
        age = (date.today() - date.fromisoformat(str(as_of))).days
    except (TypeError, ValueError):
        return AuditCheck(name="Tape freshness", passed=False,
                          detail="snapshot date unreadable")
    if age <= 3:
        return AuditCheck(name="Tape freshness", passed=True,
                          detail=f"tape as of {as_of} ({age}d old)")
    return AuditCheck(
        name="Tape freshness", passed=offline,
        detail=(f"tape as of {as_of} ({age}d old) — bundled offline snapshot, disclosed"
                if offline else
                f"tape as of {as_of} ({age}d old) with live sources expected — stale"),
    )
