"""Simulation debate engine — the keyless demo mode.

Not canned text: every figure is read from the deterministic engine run and the
data bundle, objections fire from rule triggers on the actual numbers, and
verdicts depend on the data — so NVDA argues about terminal value share while
TSLA argues about margin compression. Streams through the same EventBus the
live Anthropic mode uses; the UI cannot tell the difference.
"""
from __future__ import annotations

import asyncio
import os
import random
from typing import Any

from . import analysis, conviction
from .auditor import run_audit
from .events import Emitter
from .state import (
    AgentId, AgentView, AuditCheck, Citation, Claim, KeyNumber, Objection,
    Phase, Rating, Rebuttal, ResearchState, Thesis, ThesisPillar, Verdict,
)

# 1.0 ≈ a 45s debate. Raise to fast-forward (tests use 60), lower to savor.
SPEED = float(os.environ.get("DELPHI_SIM_SPEED", "1.0")) * 0.72

CCY_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "CHF": "CHF ", "JPY": "¥",
              "SEK": "kr ", "NOK": "kr ", "DKK": "kr ", "CAD": "C$", "AUD": "A$", "HKD": "HK$"}


def _pace(seconds: float) -> float:
    return seconds / max(SPEED, 0.05)


class SimDebate:
    def __init__(self, state: ResearchState, bundle: dict[str, Any],
                 valuation: dict[str, Any], emit: Emitter) -> None:
        self.s = state
        self.b = bundle
        self.v = valuation
        self.e = emit
        self.rng = random.Random(hash(state.ticker) & 0xFFFF)
        code = bundle.get("currency", "USD")
        self.sym = CCY_SYMBOL.get(code, f"{code} ")
        self._msg_seq = 0
        self._claim_seq = 0
        self.c = self._build_citations()

    # ---------------- infrastructure ----------------

    def _mid(self, agent: AgentId) -> str:
        self._msg_seq += 1
        return f"{agent.value}-m{self._msg_seq}"

    async def _say(self, agent: AgentId, text: str, kind: str = "finding") -> None:
        mid = self._mid(agent)
        self.e.message_start(agent, mid, kind)
        words = text.split(" ")
        i = 0
        while i < len(words):
            step = self.rng.randint(2, 4)
            chunk = " ".join(words[i:i + step])
            self.e.message_delta(mid, chunk + (" " if i + step < len(words) else ""))
            i += step
            await asyncio.sleep(_pace(self.rng.uniform(0.035, 0.075)))
        self.e.message_end(mid)

    async def _tool(self, agent: AgentId, tool: str, args: str, result: str,
                    think: float = 0.7) -> None:
        cid = self._mid(agent)
        self.e.tool_call(agent, cid, tool, args)
        await asyncio.sleep(_pace(self.rng.uniform(0.45, think + 0.45)))
        self.e.tool_result(cid, result)
        await asyncio.sleep(_pace(0.18))

    def _claim(self, agent: AgentId, text: str, cites: list[str],
               confidence: float = 0.75) -> Claim:
        self._claim_seq += 1
        c = Claim(id=f"K{self._claim_seq}", agent=agent, text=text,
                  citation_ids=cites, confidence=confidence)
        self.s.views[agent.value].claims.append(c)
        self.e.claim_filed(c)
        return c

    def _build_citations(self) -> dict[str, Citation]:
        reg: dict[str, Citation] = {}
        idx = 0

        def add(key: str, source: str, doc_type: str, url: str | None = None,
                snippet: str | None = None) -> None:
            nonlocal idx
            idx += 1
            reg[key] = Citation(id=f"C{idx}", source=source, doc_type=doc_type,
                                url=url, snippet=snippet)

        for f in self.b.get("filings", []):
            key = f["doc_type"].lower().replace("-", "")
            if key not in reg:
                snip = next(iter(f.get("snippets", {}).values()), None)
                add(key, f"{f['doc_type']} · {f['title']} ({f['date']})", "filing",
                    f.get("url"), snip)
        add("xbrl", "XBRL fact store · us-gaap standardized financials, last 4 FY", "xbrl")
        add("market", f"Market data · yfinance snapshot, as of {self.b.get('as_of', 'latest')}", "market")
        add("estimates", f"Consensus · {self.b['estimates']['n_analysts']} sell-side analysts", "market")
        add("fred", "FRED · DGS10, CPIAUCSL, FEDFUNDS series", "macro",
            "https://fred.stlouisfed.org/series/DGS10")
        add("social", "StockTwits message sentiment + Reddit mention velocity", "social")
        add("segments", "10-K segment disclosure · revenue by geography", "filing")
        add("form4", "SEC Form 4 · insider transactions, trailing 6 months", "filing")
        add("engine", "DELPHI engine · DCF, comps, Monte Carlo (deterministic, pytest-covered)", "engine")
        for c in reg.values():
            self.s.citations.append(c)
        return reg

    def _cite(self, *keys: str) -> list[str]:
        return [self.c[k].id for k in keys if k in self.c]

    # ---------------- run ----------------

    async def run(self) -> None:
        b, v, s, e = self.b, self.v, self.s, self.e

        e.run_started(s.run_id, s.ticker, b["company"], s.mode)
        for cit in s.citations:
            e.citation_added(cit)
        e.market_snapshot(analysis.market_snapshot(b))

        await self._plan()
        await self._parallel_research()
        await self._adversary_round(1)
        await self._rebuttals()
        await self._adversary_round(2)
        await self._synthesis()
        published = await self._audit_and_publish()
        if not published:
            await self._revise()
            await self._audit_and_publish(final=True)
        e.run_complete()

    # ---------------- phases ----------------

    async def _plan(self) -> None:
        b, e = self.b, self.e
        e.phase_changed(Phase.PLAN, "Director scopes the engagement")
        e.agent_status(AgentId.DIRECTOR, "thinking")
        await asyncio.sleep(_pace(0.8))
        await self._say(
            AgentId.DIRECTOR,
            f"Initiating coverage build on {b['company']} ({self.s.ticker}). I'm scoping four parallel "
            f"workstreams against the latest document set — annual and quarterly filings, the XBRL fact "
            f"store, consensus, positioning data and the macro tape. The Adversary holds objection rights "
            f"after first findings; nothing reaches the note without surviving that and a compliance audit.",
            kind="direction")
        plan = [
            f"Pull and index the {self.s.ticker} document set (10-K, 10-Q, 8-K, DEF 14A)",
            "Fundamentals: growth durability, margin bridge, quality scores",
            "Valuation: DCF with CAPM WACC, peer comps, scenario surface",
            "Sentiment: positioning, insider tape, options and social skew",
            "Macro: rates, cycle posture, geographic exposure map",
            "Adversarial review — up to 2 objection rounds with rebuttals",
            "Synthesis → conviction scoring → compliance audit → publish",
        ]
        self.s.plan = plan
        e.plan_ready(plan)
        e.agent_status(AgentId.DIRECTOR, "idle")
        await asyncio.sleep(_pace(0.5))

    async def _parallel_research(self) -> None:
        self.e.phase_changed(Phase.PARALLEL_RESEARCH, "Four specialists fan out")
        for a in (AgentId.FUNDAMENTALS, AgentId.VALUATION, AgentId.SENTIMENT, AgentId.MACRO):
            self.s.views[a.value] = AgentView(agent=a)
        await asyncio.gather(
            self._fundamentals(), self._valuation(),
            self._sentiment(), self._macro(),
        )

    async def _fundamentals(self) -> None:
        a = AgentId.FUNDAMENTALS
        b, v, e = self.b, self.v, self.e
        fin = b["financials"]
        latest, prev = fin[-1], fin[-2]
        rev_g = latest["revenue_b"] / prev["revenue_b"] - 1
        gm_pp = (latest["gross_margin"] - prev["gross_margin"]) * 100
        pio = v["ratios"]["piotroski"]
        alt = v["ratios"]["altman"]
        roe = v["ratios"]["dupont"]["roe"]

        e.agent_status(a, "reading")
        await self._tool(a, "edgar.fetch", f'ticker="{self.s.ticker}", forms=["10-K","10-Q"]',
                         f"{len(b.get('filings', [4]))} filings retrieved, section-aware chunks indexed")
        await self._tool(a, "facts.query", 'metrics=["revenue","ebit","fcf","margins"], periods=4',
                         f"FY{latest['year'][-4:]}: rev {self.sym}{latest['revenue_b']:.1f}B, op margin {latest['op_margin']:.1%}")
        e.agent_status(a, "speaking")
        await self._say(a,
            f"Top line grew {rev_g:+.1%} to {self.sym}{latest['revenue_b']:.1f}B with gross margin "
            f"{'expanding' if gm_pp >= 0 else 'compressing'} {abs(gm_pp):.1f}pp to {latest['gross_margin']:.1%}. "
            f"The quality screens are {'clean' if pio['score'] >= 6 else 'mixed'}: Piotroski {pio['score']}/9, "
            f"Altman Z at {alt['z']:.2f} ({alt['zone']}), DuPont ROE of {roe:.1%}. "
            f"Free cash flow of {self.sym}{latest['fcf_b']:.1f}B funds the capex cycle internally — "
            f"{self.sym}{latest['capex_b']:.1f}B against {self.sym}{latest['cfo_b']:.1f}B operating cash.")

        self._claim(a, f"Revenue grew {rev_g:+.1%} y/y to {self.sym}{latest['revenue_b']:.1f}B with operating margin at {latest['op_margin']:.1%}",
                    self._cite("xbrl", "10k"), 0.9)
        self._claim(a, f"Balance-sheet quality is {alt['zone']}: Altman Z {alt['z']:.2f}, Piotroski {pio['score']}/9",
                    self._cite("xbrl", "engine"), 0.85)
        self._claim(a, f"FCF of {self.sym}{latest['fcf_b']:.1f}B covers capex of {self.sym}{latest['capex_b']:.1f}B without leverage",
                    self._cite("xbrl"), 0.8)

        stance = 1.0
        stance += 0.5 if rev_g > 0.15 else (-0.5 if rev_g < 0.02 else 0)
        stance += 0.3 if pio["score"] >= 6 else -0.4
        stance += 0.2 if gm_pp >= 0 else -0.5
        stance = max(-2, min(2, stance))
        view = self.s.views[a.value]
        view.stance = round(stance, 2)
        view.summary = (f"{'Durable' if stance > 0.8 else 'Decent but watch margins'} — "
                        f"growth {rev_g:+.0%}, quality scores {'support' if pio['score'] >= 6 else 'temper'} the case")
        view.key_numbers = [
            KeyNumber(label="Rev growth", value=f"{rev_g:+.1%}", tone="pos" if rev_g > 0 else "neg"),
            KeyNumber(label="Gross margin", value=f"{latest['gross_margin']:.1%}",
                      delta=f"{gm_pp:+.1f}pp", tone="pos" if gm_pp >= 0 else "neg"),
            KeyNumber(label="Piotroski", value=f"{pio['score']}/9", tone="pos" if pio['score'] >= 6 else "neutral"),
        ]
        e.key_numbers(a, view.key_numbers)
        e.view_ready(a, view.stance, view.summary)
        e.agent_status(a, "done")

    async def _valuation(self) -> None:
        a = AgentId.VALUATION
        b, v, e = self.b, self.v, self.e
        d = v["dcf"]
        asm = v["assumptions"]
        mc = v["monte_carlo"]
        last = v["last_price"]
        upside = d["per_share"] / last - 1

        e.agent_status(a, "thinking")
        await self._tool(a, "engine.wacc", f"rf={asm['rf']:.3f}, beta={asm['beta']:.2f}, erp={asm['erp']:.3f}",
                         f"WACC {d['wacc']:.2%} via CAPM")
        await self._tool(a, "engine.run_dcf",
                         f"g1={asm['growth_path'][0]:.0%}, margin={asm['ebit_margin_path'][0]:.0%}, tg={asm['terminal_growth']:.1%}",
                         f"{self.sym}{d['per_share']:.2f}/sh · EV {self.sym}{d['ev']:.0f}B · TV {d['tv_share_of_ev']:.0%} of EV", 1.0)
        await self._tool(a, "engine.run_comps", f"peers={[p['ticker'] for p in b['peers']][:4]}",
                         f"fwd P/E implies {self.sym}{v['comps_pe']['low']:.0f}–{self.sym}{v['comps_pe']['high']:.0f}")
        await self._tool(a, "engine.monte_carlo", "n=2000, seed=42",
                         f"p50 {self.sym}{mc['draws_stats']['p50']:.0f}, P(upside) {mc.get('prob_upside', 0.5):.0%}", 1.2)
        e.agent_status(a, "speaking")
        await self._say(a,
            f"Base DCF lands at {self.sym}{d['per_share']:.2f} against the {self.sym}{last:.2f} tape — {upside:+.1%}. "
            f"That discounts {asm['growth_path'][0]:.0%} growth fading to {asm['growth_path'][-1]:.0%} over {len(asm['growth_path'])} years "
            f"at a {d['wacc']:.1%} WACC, terminal growth {asm['terminal_growth']:.1%}. Terminal value carries "
            f"{d['tv_share_of_ev']:.0%} of enterprise value, which I'll flag before the Adversary does. "
            f"Comps triangulate {self.sym}{v['comps_pe']['low']:.0f}–{self.sym}{v['comps_pe']['high']:.0f} on forward earnings; "
            f"the Monte Carlo puts {mc.get('prob_upside', 0.5):.0%} of 2,000 paths above the current price.")

        self._claim(a, f"DCF fair value {self.sym}{d['per_share']:.2f}/share, {upside:+.1%} vs market, at WACC {d['wacc']:.1%}",
                    self._cite("engine", "xbrl"), 0.8)
        self._claim(a, f"Terminal value is {d['tv_share_of_ev']:.0%} of EV under Gordon growth at {asm['terminal_growth']:.1%}",
                    self._cite("engine"), 0.9)
        self._claim(a, f"Monte Carlo (n=2,000): {mc.get('prob_upside', 0.5):.0%} probability of upside, p50 {self.sym}{mc['draws_stats']['p50']:.0f}",
                    self._cite("engine"), 0.85)

        stance = max(-2, min(2, upside * 6))
        view = self.s.views[a.value]
        view.stance = round(stance, 2)
        view.summary = f"Engine triangulates {'above' if upside > 0 else 'below'} the tape — DCF {upside:+.0%}, comps corroborate"
        view.key_numbers = [
            KeyNumber(label="DCF / share", value=f"{self.sym}{d['per_share']:.2f}",
                      delta=f"{upside:+.1%} vs px", tone="pos" if upside > 0 else "neg"),
            KeyNumber(label="WACC", value=f"{d['wacc']:.1%}", tone="neutral"),
            KeyNumber(label="P(upside)", value=f"{mc.get('prob_upside', 0.5):.0%}",
                      tone="pos" if mc.get("prob_upside", 0.5) > 0.5 else "neg"),
        ]
        e.key_numbers(a, view.key_numbers)
        e.valuation_update(
            football_field=analysis.football_field(v),
            sensitivity=analysis.sensitivity_cells(v)[0],
            sensitivity_axes=analysis.sensitivity_cells(v)[1],
            monte_carlo=analysis.monte_carlo_summary(v),
        )
        e.view_ready(a, view.stance, view.summary)
        e.agent_status(a, "done")

    async def _sentiment(self) -> None:
        a = AgentId.SENTIMENT
        b, e = self.b, self.e
        soc = b["social"]
        own = b["ownership"]
        bullish = soc["stocktwits_sentiment"]
        short = soc["short_interest_pct"]
        insider = own["insider_net_shares_6m"]

        e.agent_status(a, "reading")
        await self._tool(a, "social.stream", f'symbol="{self.s.ticker}", window="30d"',
                         f"{soc['reddit_mentions_30d']:,} Reddit mentions · {bullish:.0%} bullish skew on StockTwits")
        await self._tool(a, "edgar.form4", 'window="6m"',
                         f"net insider {'selling' if insider < 0 else 'buying'}: {abs(insider):,.0f} shares — {own['form4_signal']}")
        e.agent_status(a, "speaking")
        await self._say(a,
            f"Positioning is {'crowded' if bullish > 0.72 else 'constructive' if bullish > 0.55 else 'skeptical'}: "
            f"{bullish:.0%} of StockTwits flow reads bullish, Reddit velocity at {soc['reddit_mentions_30d']:,} mentions "
            f"over 30 days, short interest just {short:.1%} of float. The insider tape shows {own['form4_signal']} — "
            f"I read that as {'routine 10b5-1 noise' if insider < 0 else 'a quiet vote of confidence'}. "
            f"Implied vol rank at {soc['iv_rank']:.0f} says the options market "
            f"{'is already paying up for movement' if soc['iv_rank'] > 60 else 'is not pricing a shock'}.")

        self._claim(a, f"Retail skew {bullish:.0%} bullish with short interest at {short:.1%} of float",
                    self._cite("social"), 0.7)
        self._claim(a, f"Insiders: {own['form4_signal']} over trailing 6 months", self._cite("form4"), 0.75)
        # Deliberately uncited — the Auditor will catch this and force a REVISE loop.
        self._claim(a, "Dealer gamma positioning implies dips get bought into quarter-end", [], 0.5)

        stance = 0.4 + (bullish - 0.6) * 2 - (0.6 if bullish > 0.8 else 0) + (0.3 if insider > 0 else -0.1)
        stance = max(-2, min(2, stance))
        view = self.s.views[a.value]
        view.stance = round(stance, 2)
        view.summary = f"{'Crowded but supported' if bullish > 0.7 else 'Constructive'} — sentiment is a tailwind, not an edge"
        view.key_numbers = [
            KeyNumber(label="Bullish skew", value=f"{bullish:.0%}", tone="pos" if bullish > 0.55 else "neg"),
            KeyNumber(label="Short interest", value=f"{short:.1%}", tone="neutral"),
            KeyNumber(label="IV rank", value=f"{soc['iv_rank']:.0f}", tone="neutral"),
        ]
        e.key_numbers(a, view.key_numbers)
        e.view_ready(a, view.stance, view.summary)
        e.agent_status(a, "done")

    async def _macro(self) -> None:
        a = AgentId.MACRO
        b, e = self.b, self.e
        mac = b["macro"]
        geo = sorted(b["geo_revenue"], key=lambda r: -r["revenue_share"])
        top = geo[0]
        intl = sum(r["revenue_share"] for r in geo if r["iso_n3"] != "840")
        ism = mac.get("ism_pmi")
        # Dynamic coverage only knows the domicile — don't dress it up as
        # segment disclosure.
        domicile_only = len(geo) == 1 and top["revenue_share"] >= 0.99

        e.agent_status(a, "reading")
        await self._tool(a, "fred.series", 'ids=["DGS10","CPIAUCSL","FEDFUNDS"]',
                         f"10y {mac['rf_10y']:.2%} · CPI {mac['cpi_yoy']:.1%} y/y · FF {mac['fed_funds']:.2%}")
        await self._tool(a, "filings.segments", 'item="geographic revenue"',
                         "segment disclosure not parsed — domicile shown" if domicile_only else
                         f"{len(geo)} disclosed regions · top: {top['name']} at {top['revenue_share']:.0%}")
        e.agent_status(a, "speaking")
        ism_clause = (f"and ISM at {ism:.0f} {'(expansion)' if ism > 50 else '(contraction)'}. "
                      if ism is not None else "with no cycle shock on the tape. ")
        geo_story = (
            f"Geographic segmentation isn't parsed for this listing yet, so treat the exposure map as "
            f"indicative: domicile is {top['name']}, and the macro read runs through its rates and policy."
            if domicile_only else
            f"The geographic footprint is the real macro story here: {top['name']} is "
            f"{top['revenue_share']:.0%} of revenue and {intl:.0%} books outside the US. I've mapped "
            f"{len(b['arcs'])} supply and demand dependencies — the exposure map shows where policy "
            f"can reach this P&L.")
        await self._say(a,
            f"The discount-rate backdrop is workable — 10-year at {mac['rf_10y']:.2%}, inflation {mac['cpi_yoy']:.1%} "
            f"{ism_clause}"
            f"Sector read: {mac['sector_signal']} {geo_story}")

        if domicile_only:
            self._claim(a, f"Domiciled in {top['name']}; geographic segment disclosure pending parse",
                        self._cite("segments", "market"), 0.6)
        else:
            self._claim(a, f"{top['name']} concentration at {top['revenue_share']:.0%} of revenue; international mix {intl:.0%}",
                        self._cite("segments", "10k"), 0.85)
        self._claim(a, f"Rates backdrop: 10y {mac['rf_10y']:.2%}, CPI {mac['cpi_yoy']:.1%} — no WACC shock priced",
                    self._cite("fred"), 0.8)

        stance = 0.3
        if ism is not None:
            stance += 0.4 if ism > 50 else -0.5
        if top["revenue_share"] > 0.42 and top["iso_n3"] != "840" and not domicile_only:
            stance -= 0.5
        stance = max(-2, min(2, stance))
        view = self.s.views[a.value]
        view.stance = round(stance, 2)
        view.summary = (f"Macro neutral; domicile {top['name']}, rates are the lever" if domicile_only else
                        f"Macro neutral-to-supportive; geography is the swing factor ({top['name']} {top['revenue_share']:.0%})")
        view.key_numbers = [
            KeyNumber(label="10y yield", value=f"{mac['rf_10y']:.2%}", tone="neutral"),
            KeyNumber(label="Top region", value=f"{top['revenue_share']:.0%}",
                      delta=top["name"], tone="neg" if top["revenue_share"] > 0.42 and not domicile_only else "neutral"),
            (KeyNumber(label="ISM PMI", value=f"{ism:.0f}", tone="pos" if ism > 50 else "neg")
             if ism is not None else
             KeyNumber(label="Fed funds", value=f"{mac['fed_funds']:.2%}", tone="neutral")),
        ]
        e.key_numbers(a, view.key_numbers)
        e.geo_exposure(analysis.geo_exposure(b))
        e.view_ready(a, view.stance, view.summary)
        e.agent_status(a, "done")

    # ---------------- adversary ----------------

    def _objection_rules(self) -> list[dict[str, Any]]:
        """Rule-triggered objections, ranked by weight. Data decides which fire."""
        b, v = self.b, self.v
        d, asm, mc = v["dcf"], v["assumptions"], v["monte_carlo"]
        geo = sorted(b["geo_revenue"], key=lambda r: -r["revenue_share"])
        top = geo[0]
        soc = b["social"]
        fin = b["financials"]
        upside = d["per_share"] / v["last_price"] - 1
        rules: list[dict[str, Any]] = []

        if d["tv_share_of_ev"] > 0.62:
            rules.append(dict(
                key="tv", target=AgentId.VALUATION, weight=round(6 + d["tv_share_of_ev"] * 10, 1),
                text=(f"Your {self.sym}{d['per_share']:.2f} fair value rests on a terminal value that is "
                      f"{d['tv_share_of_ev']:.0%} of enterprise value. That isn't a valuation, it's a "
                      f"belief about year six onward. Shave terminal growth 50bps and the case thins fast — "
                      f"show me the sensitivity, not the point estimate."),
                standing=d["tv_share_of_ev"] > 0.80))
        n_analysts = b["estimates"].get("n_analysts") or 0
        if abs(upside) > 0.18:
            coverage = (f"one of the most-covered names on the tape ({n_analysts} analysts)"
                        if n_analysts else "a listing with no street coverage to lean on")
            rules.append(dict(
                key="market", target=AgentId.VALUATION, weight=8.0,
                text=(f"You're claiming a {upside:+.0%} mispricing on {coverage}. "
                      f"What do you know that the market doesn't? "
                      f"Without a stated variant perception this is just optimistic inputs."),
                standing=abs(upside) > 0.30 and mc.get("prob_upside", 0.5) < 0.35))
        domicile_only = len(geo) == 1 and geo[0]["revenue_share"] >= 0.99
        intl = [g for g in geo if g["iso_n3"] != "840"] if not domicile_only else []
        top_intl = max(intl, key=lambda r: r["revenue_share"]) if intl else None
        if top_intl and top_intl["revenue_share"] > 0.18:
            rules.append(dict(
                key="geo", target=AgentId.MACRO, weight=round(4 + top_intl["revenue_share"] * 14, 1),
                text=(f"{top_intl['revenue_share']:.0%} of revenue routes through {top_intl['name']}"
                      f"{' — a jurisdiction one export-control headline away from repricing' if top_intl['iso_n3'] in ('156', '158', '702') else ''}. "
                      f"{top_intl.get('note') or 'Concentration is the risk the multiple ignores.'} "
                      f"What's the earnings hit in a hard-decoupling scenario?"),
                standing=top_intl["revenue_share"] > 0.32 and top_intl["iso_n3"] in ("156", "158", "702", "356", "704")))
        g_hist = fin[-1]["revenue_b"] / fin[-2]["revenue_b"] - 1
        if asm["growth_path"][0] > g_hist + 0.08:
            rules.append(dict(
                key="growth", target=AgentId.FUNDAMENTALS, weight=7.5,
                text=(f"Consensus has {asm['growth_path'][0]:.0%} growth next year against {g_hist:.0%} just printed. "
                      f"You're underwriting acceleration at scale. Name the capacity, the backlog, or the price — "
                      f"otherwise the estimate is vibes."),
                standing=asm["growth_path"][0] > g_hist + 0.20))
        if fin[-1]["op_margin"] < fin[-2]["op_margin"] - 0.01:
            compression = (fin[-2]["op_margin"] - fin[-1]["op_margin"]) * 100
            rules.append(dict(
                key="margin", target=AgentId.FUNDAMENTALS, weight=8.5,
                text=(f"Operating margin compressed {compression:.1f}pp "
                      f"to {fin[-1]['op_margin']:.1%} and your model holds it flat-to-up. Competition doesn't "
                      f"pause because the DCF needs it to."),
                standing=compression > 2.0))
        if soc["stocktwits_sentiment"] > 0.72:
            rules.append(dict(
                key="crowding", target=AgentId.SENTIMENT, weight=6.0,
                text=(f"{soc['stocktwits_sentiment']:.0%} bullish skew and {soc['short_interest_pct']:.1%} short interest "
                      f"means everyone who wants this story owns it. Sentiment isn't a tailwind at these levels — "
                      f"it's a vacuum under the price if the narrative wobbles."),
                standing=soc["stocktwits_sentiment"] > 0.85))
        if mc.get("prob_upside", 0.5) < 0.45:
            rules.append(dict(
                key="mc", target=AgentId.VALUATION, weight=7.0,
                text=(f"Your own Monte Carlo puts just {mc['prob_upside']:.0%} of paths above the current price. "
                      f"The engine is telling you the risk-reward is balanced at best — why doesn't the rating say so?"),
                standing=mc.get("prob_upside", 0.5) < 0.35))

        rules.sort(key=lambda r: -r["weight"])
        return rules

    async def _adversary_round(self, rnd: int) -> None:
        e = self.e
        phase = Phase.ADVERSARY_ROUND_1 if rnd == 1 else Phase.ADVERSARY_ROUND_2
        e.phase_changed(phase, "Objections filed" if rnd == 1 else "Standing objections pressed")
        e.agent_status(AgentId.ADVERSARY, "thinking")
        await asyncio.sleep(_pace(1.0))

        if rnd == 1:
            self._rules = self._objection_rules()
            picks = self._rules[:3]
            await self._say(AgentId.ADVERSARY,
                "I've read all four workstreams. The job here isn't to be bearish, it's to find what breaks "
                "the thesis. Three objections, weighted by how much conviction they should cost if they stand.",
                kind="objection")
            for i, r in enumerate(picks, 1):
                o = Objection(id=f"O{i}", round=1, target_agent=r["target"],
                              target_claim_id=self._claim_for(r["target"]),
                              text=r["text"], weight=r["weight"])
                self.s.objections.append(o)
                e.objection_filed(o)
                await asyncio.sleep(_pace(self.rng.uniform(1.0, 1.6)))
        else:
            standing = [vd for vd in self.s.verdicts if vd.status == "standing"]
            if standing:
                obj = next(o for o in self.s.objections if o.id == standing[0].objection_id)
                await self._say(AgentId.ADVERSARY,
                    f"One objection survives rebuttal and I'm pressing it: {obj.text.split('.')[0].lower()}. "
                    f"The rebuttal mitigated the edges but the core exposure stands. It stays on the risk "
                    f"register and it costs conviction — that's the discipline.", kind="objection")
            else:
                await self._say(AgentId.ADVERSARY,
                    "The rebuttals held — engine reruns and primary-source cites, not adjectives. "
                    "I have nothing further that would survive audit. Withdrawn.", kind="objection")
        e.agent_status(AgentId.ADVERSARY, "done")

    def _claim_for(self, agent: AgentId) -> str | None:
        view = self.s.views.get(agent.value)
        return view.claims[0].id if view and view.claims else None

    async def _rebuttals(self) -> None:
        e = self.e
        e.phase_changed(Phase.REBUTTAL, "Specialists respond with evidence")
        for i, o in enumerate(self.s.objections, 1):
            agent = o.target_agent
            e.agent_status(agent, "rebutting")
            rule = self._rules[i - 1]
            reb_text, cites = await self._rebut(agent, rule)
            r = Rebuttal(id=f"R{i}", objection_id=o.id, agent=agent,
                         text=reb_text, citation_ids=cites)
            self.s.rebuttals.append(r)
            e.rebuttal_filed(r)
            await asyncio.sleep(_pace(0.5))

            status = "standing" if rule["standing"] else ("mitigated" if rule["weight"] > 6.5 else "refuted")
            vd = Verdict(
                objection_id=o.id, status=status,
                rationale={
                    "refuted": "Rebuttal evidence directly contradicts the objection's premise.",
                    "mitigated": "Quantified and bounded; residual risk priced into the bear case.",
                    "standing": "Rebuttal narrows but does not neutralize the exposure; weight applies.",
                }[status],
                penalty_applied=o.weight if status == "standing" else (o.weight * 0.35 if status == "mitigated" else 0.0),
            )
            self.s.verdicts.append(vd)
            e.verdict_rendered(vd)
            e.agent_status(agent, "done")
            await asyncio.sleep(_pace(0.4))

    async def _rebut(self, agent: AgentId, rule: dict[str, Any]) -> tuple[str, list[str]]:
        v, b = self.v, self.b
        key = rule["key"]
        if key in ("tv", "market", "mc"):
            bear = v["dcf_bear"]
            shock_bps = min(0.04, v["assumptions"]["ebit_margin_path"][0] * 0.35) * 10000
            await self._tool(agent, "engine.run_dcf",
                             f"growth ×0.6, margin −{shock_bps:.0f}bps, tg=2.5% (bear rerun)",
                             f"bear case {self.sym}{bear['per_share']:.2f}/sh", 1.0)
            street = v["analyst_targets"]["mean"]
            variant_clause = (f"And the variant perception is stated: consensus mean target is {self.sym}{street:.0f}; "
                              f"our edge is the margin bridge, not the multiple."
                              if street is not None else
                              "With no street tape on this listing, the engine's range IS the variant "
                              "perception — and it's published with its assumptions.")
            txt = (f"Fair challenge — so I reran it instead of arguing. Stress the model to {bear['per_share'] / v['last_price'] - 1:+.0%} "
                   f"vs the tape: growth cut 40%, margins down {shock_bps:.0f}bps, terminal growth at 2.5%. Bear case prints "
                   f"{self.sym}{bear['per_share']:.2f}. The sensitivity grid is in the note — the thesis doesn't need the "
                   f"terminal year to be heroic, it needs it to be ordinary. {variant_clause}")
            return txt, self._cite("engine")
        if key == "geo":
            intl = [g for g in b["geo_revenue"] if g["iso_n3"] != "840"]
            top = max(intl or b["geo_revenue"], key=lambda r: r["revenue_share"])
            await self._tool(agent, "scenario.geo_shock", f"region={top['name']!r}, revenue_haircut=40%",
                             f"EPS impact ≈ −{top['revenue_share'] * 0.4 * 100:.0f}% in year one")
            txt = (f"Quantified: a 40% disruption to {top['name']} flows is roughly a "
                   f"{top['revenue_share'] * 0.4:.0%} revenue hit before mitigation — severe, not terminal. "
                   f"{top.get('note') or ''} Re-routing and pricing recapture historically claw back a third "
                   f"within four quarters. It belongs on the risk register at full weight, priced in the bear case.")
            return txt, self._cite("segments", "engine")
        if key in ("growth", "margin"):
            fin = b["financials"]
            txt = (f"The acceleration isn't asserted, it's contracted: management guidance and the demand "
                   f"disclosures in the latest filings back the {v['assumptions']['growth_path'][0]:.0%} print, "
                   f"and the four-year XBRL series shows the trajectory — {self.sym}{fin[-3]['revenue_b']:.0f}B → "
                   f"{self.sym}{fin[-2]['revenue_b']:.0f}B → {self.sym}{fin[-1]['revenue_b']:.0f}B. If the margin walk stalls, "
                   f"the bear DCF at {self.sym}{v['dcf_bear']['per_share']:.2f} is the floor we underwrite, not a surprise.")
            return txt, self._cite("10k", "xbrl", "estimates")
        # crowding
        soc = b["social"]
        txt = (f"Crowding is real and I won't argue it away — that's why my stance is moderated, not maximal. "
               f"But the spot checks cut against a blow-off: short interest {soc['short_interest_pct']:.1%} "
               f"means no squeeze fuel either way, IV rank {soc['iv_rank']:.0f} isn't euphoric, and the insider "
               f"tape is {b['ownership']['form4_signal']} — not the distribution pattern you see at tops.")
        return txt, self._cite("social", "form4")

    # ---------------- synthesis / audit ----------------

    def _build_rating(self) -> Rating:
        v = self.v
        d = v["dcf"]
        engine = (0.5 * d["per_share"]
                  + 0.3 * (v["comps_pe"]["mid"] + v["comps_ev_ebitda"]["mid"]) / 2
                  + 0.2 * v["monte_carlo"]["draws_stats"]["p50"])
        street = v["analyst_targets"]
        # Engine purity meets desk reality: anchor 35% to consensus so a
        # story-stock divergence prints as a differentiated call, not a typo.
        # Dynamic coverage may have no street tape — then the engine stands alone.
        if analysis.street_available(v):
            blended = 0.65 * engine + 0.35 * street["mean"]
            bull_raw = 0.65 * v["dcf_bull"]["per_share"] + 0.35 * street["high"]
            bear_raw = 0.65 * v["dcf_bear"]["per_share"] + 0.35 * street["low"]
        else:
            blended = engine
            bull_raw = v["dcf_bull"]["per_share"]
            bear_raw = v["dcf_bear"]["per_share"]
        last = v["last_price"]
        upside = blended / last - 1
        action = "OVERWEIGHT" if upside > 0.12 else ("UNDERWEIGHT" if upside < -0.08 else "EQUAL-WEIGHT")
        bull = max(bull_raw, blended)
        bear = min(max(bear_raw, 0.1 * last), blended)
        return Rating(action=action, price_target=round(blended, 2),
                      bull_target=round(bull, 2), bear_target=round(bear, 2),
                      last_price=last, upside_pct=round(upside, 4))

    async def _synthesis(self) -> None:
        e, s, v, b = self.e, self.s, self.v, self.b
        e.phase_changed(Phase.SYNTHESIS, "Director assembles thesis + conviction")
        e.agent_status(AgentId.DIRECTOR, "thinking")
        await asyncio.sleep(_pace(1.2))

        rating = self._build_rating()
        s.rating = rating
        views = list(s.views.values())
        uncited = sum(1 for vw in views for c in vw.claims if not c.citation_ids)
        conv = conviction.score(views, s.objections, s.verdicts, uncited)
        s.conviction = conv

        standing_n = sum(1 for vd in s.verdicts if vd.status == "standing")
        street_mean = v["analyst_targets"]["mean"]
        anchor_clause = (f"anchored 35% to the street's {self.sym}{street_mean:.0f} consensus, "
                         if street_mean is not None else
                         "with no street consensus to anchor — the engine stands alone, ")
        await self._say(AgentId.DIRECTOR,
            f"Synthesis. Four workstreams, {len(s.objections)} objections, {standing_n} still standing after rebuttal. "
            f"Blending the engine's DCF, comps and Monte Carlo median, {anchor_clause}gives a "
            f"{self.sym}{rating.price_target:.2f} target against {self.sym}{rating.last_price:.2f} — {rating.upside_pct:+.1%}. "
            f"That's {rating.action} with conviction {conv.final:.0f}: {conv.base_agreement:.0f} from "
            f"cross-desk agreement, minus {conv.objection_penalty:.0f} for surviving objections, minus "
            f"{conv.citation_penalty:.0f} in citation penalties. The number is the formula — no vibes.",
            kind="direction")

        intl_regions = [g for g in b["geo_revenue"] if g["iso_n3"] != "840"]
        top_geo = max(intl_regions or b["geo_revenue"], key=lambda r: r["revenue_share"])
        domicile_only = len(b["geo_revenue"]) == 1 and b["geo_revenue"][0]["revenue_share"] >= 0.99
        geo_clause = (f"{top_geo['name']} domicile (segment disclosure pending)" if domicile_only
                      else f"{top_geo['name']} concentration")
        street_lede = (f"Street consensus sits at {self.sym}{street_mean:.0f}; our {self.sym}{rating.price_target:.0f} differs"
                       if street_mean is not None else
                       f"No street consensus exists for this listing; the engine's {self.sym}{rating.price_target:.0f} stands alone")
        variant = (f"{street_lede} because the "
                   f"engine prices the margin bridge and terminal economics explicitly rather than rolling forward "
                   f"the multiple. The debate surfaced where that breaks: "
                   f"{'terminal-value dependence and ' if v['dcf']['tv_share_of_ev'] > 0.62 else ''}"
                   f"{geo_clause} — both are sized in the bear case, not waved away.")

        pillars = []
        fin = b["financials"][-1]
        fund = s.views[AgentId.FUNDAMENTALS.value]
        val = s.views[AgentId.VALUATION.value]
        pillars.append(ThesisPillar(
            title="The business earns its growth",
            text=fund.claims[0].text + f"; quality screens ({fund.key_numbers[2].value} Piotroski) say the print is real.",
            citation_ids=fund.claims[0].citation_ids))
        pillars.append(ThesisPillar(
            title="The engine, not the narrative, sets the target",
            text=val.claims[0].text + "; comps and 2,000 Monte Carlo paths corroborate the range.",
            citation_ids=val.claims[0].citation_ids))
        pillars.append(ThesisPillar(
            title="Risk is sized, not ignored",
            text=(f"Standing risks ({standing_n}) are priced in the {self.sym}{rating.bear_target:.0f} bear case — "
                  f"{top_geo['name']} exposure and terminal assumptions are the watch items."),
            citation_ids=self._cite("engine", "segments")))

        thesis = Thesis(
            headline=(f"{b['company']}: {rating.action.title().replace('-', ' ')} — "
                      f"{self.sym}{rating.price_target:.0f} target, conviction {conv.final:.0f}/100"),
            pillars=pillars, variant_perception=variant)
        s.thesis = thesis

        e.thesis_ready(thesis)
        e.rating_ready(rating)
        e.conviction_update(conv)
        e.agent_status(AgentId.DIRECTOR, "done")

    async def _audit_and_publish(self, final: bool = False) -> bool:
        e, s = self.e, self.s
        e.phase_changed(Phase.AUDIT, "Compliance gate")
        e.agent_status(AgentId.AUDITOR, "thinking")
        await self._tool(AgentId.AUDITOR, "audit.verify_numbers", "claims=*, tolerance=6%",
                         "cross-checking every stated figure against the fact store", 0.8)

        checks, uncited = run_audit(s, self.b, self.v)
        s.audit = checks
        for ch in checks:
            e.audit_check(ch)
            await asyncio.sleep(_pace(0.45))

        passed = all(c.passed for c in checks)
        if passed:
            await self._say(AgentId.AUDITOR,
                "All gates green. Citations resolve, figures reconcile to the engine and the filings, "
                "the rating is consistent with the conviction math. Cleared for publication.", kind="audit")
            e.agent_status(AgentId.AUDITOR, "done")
            e.phase_changed(Phase.PUBLISH, "Research note published")
            self._publish()
            return True

        if final:
            # One revision loop is the contract; residual exceptions publish
            # on the record rather than silently blocking.
            failed = [c.name for c in checks if not c.passed]
            await self._say(AgentId.AUDITOR,
                f"Revision accepted. {len(failed)} check(s) remain flagged ({', '.join(failed)}) and are "
                f"published as exceptions in the audit trail — the reader sees exactly what didn't "
                f"reconcile. Cleared with exceptions.", kind="audit")
            e.agent_status(AgentId.AUDITOR, "done")
            e.phase_changed(Phase.PUBLISH, "Published with audit exceptions")
            self._publish()
            return True

        await self._say(AgentId.AUDITOR,
            f"Hold. {sum(1 for c in checks if not c.passed)} check(s) failed — there are {uncited} claim(s) "
            f"on the record without citations. Nothing uncited survives to print. Returning to the Director "
            f"for revision.", kind="audit")
        e.agent_status(AgentId.AUDITOR, "done")
        return False

    async def _revise(self) -> None:
        e, s = self.e, self.s
        e.phase_changed(Phase.REVISE, "Audit failure loops back — once")
        e.agent_status(AgentId.DIRECTOR, "thinking")
        await asyncio.sleep(_pace(0.8))

        removed = 0
        for view in s.views.values():
            kept = []
            for c in view.claims:
                if c.citation_ids:
                    kept.append(c)
                else:
                    removed += 1
            view.claims = kept
        await self._say(AgentId.DIRECTOR,
            f"Auditor's right. {removed} uncited claim struck from the record — the gamma-positioning color "
            f"was desk chatter, not evidence. Conviction is re-scored without it. This loop is the point of "
            f"the architecture: the note only carries what survives.", kind="direction")

        conv = conviction.score(list(s.views.values()), s.objections, s.verdicts, 0)
        s.conviction = conv
        e.conviction_update(conv)
        e.agent_status(AgentId.DIRECTOR, "done")

    def _publish(self) -> None:
        from datetime import datetime, timezone

        from .state import ResearchNote
        s, v, b = self.s, self.v, self.b
        if s.thesis and s.rating and s.conviction:
            # Headline carries the post-revision conviction, not the draft's.
            s.thesis.headline = (
                f"{b['company']}: {s.rating.action.title().replace('-', ' ')} — "
                f"{self.sym}{s.rating.price_target:.0f} target, conviction {s.conviction.final:.0f}/100")
        cells, axes = analysis.sensitivity_cells(v)
        note = ResearchNote(
            run_id=s.run_id, ticker=s.ticker, company=b["company"],
            generated_at=datetime.now(timezone.utc).isoformat(),
            mode="simulation",
            snapshot=analysis.market_snapshot(b),
            rating=s.rating, conviction=s.conviction, thesis=s.thesis,
            views=list(s.views.values()),
            objections=s.objections, rebuttals=s.rebuttals, verdicts=s.verdicts,
            football_field=analysis.football_field(v),
            sensitivity=cells, sensitivity_axes=axes,
            monte_carlo=analysis.monte_carlo_summary(v),
            geo=analysis.geo_exposure(b),
            risks=self._risk_register(),
            audit=s.audit, citations=s.citations,
            financial_summary=analysis.financial_summary(b, v),
        )
        s.note = note
        self.e.note_published(note)

    def _risk_register(self) -> list:
        from .state import RiskItem
        items: list[RiskItem] = []
        verdict_by_obj = {vd.objection_id: vd for vd in self.s.verdicts}
        for o in self.s.objections:
            vd = verdict_by_obj.get(o.id)
            sev = "high" if (vd and vd.status == "standing") else ("medium" if vd and vd.status == "mitigated" else "low")
            reb = next((r for r in self.s.rebuttals if r.objection_id == o.id), None)
            items.append(RiskItem(
                title=o.text.split(".")[0][:90],
                severity=sev,
                probability="medium" if sev != "low" else "low",
                text=o.text,
                mitigant=reb.text.split(".")[0] + "." if reb else None,
            ))
        return items
