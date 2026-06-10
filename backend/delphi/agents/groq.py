"""Live debate mode on Groq — open models over the OpenAI-compatible API.

Same protocol, same audit gate, same deterministic engine; the judgment text
comes from Llama-family models served by Groq. Tool *results* stay
deterministic (the engine computes, events are emitted for the theater) and
the model narrates over them — far more reliable on free-tier rate limits
than streaming function-calls, and honest to the architecture: agents make
judgments, engines make calculations.

No SDK dependency: raw httpx against https://api.groq.com/openai/v1.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from . import analysis, conviction
from .llm import (
    SPECIALIST_BRIEFS, ParsedObjections, ParsedSynthesis, ParsedVerdict,
    ParsedView,
)
from .sim import SimDebate, _pace
from .state import (
    AgentId, AgentView, KeyNumber, Objection, Phase, Rebuttal, Thesis,
    ThesisPillar, Verdict,
)

GROQ_BASE = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

# Preference order, intersected with GET /models at run time — Groq's
# catalog churns, so never hard-fail on a retired model id.
BIG_MODELS = [
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "moonshotai/kimi-k2-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.1-70b-versatile",
]
SMALL_MODELS = [
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "gemma2-9b-it",
]


def _slim_digest(bundle: dict[str, Any], v: dict[str, Any]) -> str:
    """Compact fact pack (~1.5k tokens) — free-tier TPM limits are real."""
    fin = bundle["financials"]
    latest, prev = fin[-1], fin[-2]
    mkt = bundle["market"]
    geo = sorted(bundle["geo_revenue"], key=lambda r: -r["revenue_share"])[:5]
    d, mc = v["dcf"], v["monte_carlo"]
    rat = v["ratios"]
    slim = {
        "company": bundle["company"], "ticker": bundle["ticker"], "sector": bundle["sector"],
        "price": mkt["last_price"], "mkt_cap_b": mkt["market_cap_b"],
        "pe_fwd": mkt.get("pe_fwd"), "beta_raw": mkt.get("beta"),
        "latest_fy": {k: latest.get(k) for k in
                      ("year", "revenue_b", "gross_margin", "op_margin", "net_income_b",
                       "eps", "fcf_b", "capex_b", "cfo_b")},
        "prior_fy": {k: prev.get(k) for k in ("year", "revenue_b", "gross_margin", "op_margin", "eps")},
        "estimates": bundle["estimates"],
        "ownership_signal": bundle["ownership"]["form4_signal"],
        "social": bundle["social"],
        "macro": bundle["macro"],
        "geo_revenue_top": [{"name": g["name"], "share": g["revenue_share"], "note": g.get("note")}
                            for g in geo],
        "engine": {
            "wacc": d["wacc"], "dcf_per_share": d["per_share"],
            "tv_share_of_ev": d["tv_share_of_ev"],
            "dcf_bear": v["dcf_bear"]["per_share"], "dcf_bull": v["dcf_bull"]["per_share"],
            "growth_path": v["assumptions"]["growth_path"],
            "comps_pe_mid": v["comps_pe"]["mid"], "comps_ev_ebitda_mid": v["comps_ev_ebitda"]["mid"],
            "mc_p50": mc["draws_stats"]["p50"], "prob_upside": mc.get("prob_upside"),
            "altman_z": rat["altman"]["z"], "piotroski": rat["piotroski"]["score"],
            "roe": rat["dupont"]["roe"], "street_targets": v["analyst_targets"],
        },
    }
    return json.dumps(slim, default=str)


def _slim_schema(model: type[BaseModel]) -> str:
    """JSON schema with the noise stripped — every prompt token counts here."""
    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(x) for k, x in node.items() if k not in ("title",)}
        if isinstance(node, list):
            return [strip(x) for x in node]
        return node
    return json.dumps(strip(model.model_json_schema()))


class GroqDebate(SimDebate):
    """Same protocol as LiveDebate, spoken by Groq-served open models."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.s.mode = "live"
        self.digest = _slim_digest(self.b, self.v)
        self.client = httpx.AsyncClient(
            base_url=GROQ_BASE,
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        self.model: str | None = os.environ.get("DELPHI_GROQ_MODEL")
        self.parser_model: str | None = os.environ.get("DELPHI_GROQ_MODEL_PARSER")
        self._llm_sem = asyncio.Semaphore(1)     # serialize: free-tier TPM is the constraint

    async def run(self) -> None:
        try:
            await self._resolve_models()
            await super().run()
        finally:
            await self.client.aclose()

    async def _resolve_models(self) -> None:
        if self.model and self.parser_model:
            return
        available: set[str] = set()
        try:
            r = await self.client.get("/models")
            r.raise_for_status()
            available = {m["id"] for m in r.json().get("data", [])}
        except Exception:
            pass                                   # fall through to first preference
        if not self.model:
            self.model = next((m for m in BIG_MODELS if m in available), BIG_MODELS[0])
        if not self.parser_model:
            self.parser_model = next((m for m in SMALL_MODELS if m in available), self.model)

    # ---------------- HTTP plumbing ----------------

    async def _chat(self, payload: dict[str, Any], stream: bool = False) -> httpx.Response:
        delay = 3.0
        body = ""
        for attempt in range(6):
            req = self.client.build_request("POST", "/chat/completions", json=payload)
            resp = await self.client.send(req, stream=stream)
            if resp.status_code == 200:
                return resp
            body = (await resp.aread()).decode(errors="replace")[:400]
            await resp.aclose()
            if resp.status_code in (429, 500, 502, 503) and attempt < 5:
                # TPM windows reset on the minute — honor Groq's own hint.
                hint = re.search(r"try again in ([0-9.]+)s", body)
                if hint:
                    wait = float(hint.group(1)) + 1.0
                else:
                    try:                      # Retry-After may be an HTTP-date
                        wait = float(resp.headers.get("retry-after", ""))
                    except ValueError:
                        wait = delay
                await asyncio.sleep(min(wait, 65.0))
                delay *= 2
                continue
            raise RuntimeError(f"Groq API {resp.status_code}: {body}")
        raise RuntimeError(f"Groq API: retries exhausted ({body})")

    async def _stream_agent(self, agent: AgentId, system: str, user: str,
                            kind: str = "finding", max_tokens: int = 480,
                            fallback: str = "") -> tuple[str, bool]:
        """Stream one narrative turn to the bus. Returns (text, live).

        live=False means the model was unreachable (free-tier quota, outage)
        and the data-grounded fallback narration was streamed instead — the
        debate degrades gracefully, it never dies on a 429.
        """
        import contextlib

        mid = self._mid(agent)
        started = False
        parts: list[str] = []
        try:
            async with self._llm_sem:
                resp = await self._chat({
                    "model": self.model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "temperature": 0.6,
                    "max_tokens": max_tokens,
                    "stream": True,
                }, stream=True)
                try:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            delta = json.loads(data)["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError, json.JSONDecodeError):
                            continue
                        if not delta:
                            continue
                        if not started:
                            self.e.message_start(agent, mid, kind)
                            started = True
                        self.e.message_delta(mid, delta)
                        parts.append(delta)
                finally:
                    # message_end FIRST — an aclose() failure must never leave
                    # the bubble stuck "streaming" in the UI.
                    if started:
                        self.e.message_end(mid)
                    with contextlib.suppress(Exception):
                        await resp.aclose()
        except Exception:
            pass
        if parts:
            # A partially-streamed message is still the message on the record —
            # don't contradict it with a second fallback bubble.
            return "".join(parts), True
        if fallback:
            await self._say(agent, fallback, kind)
        return fallback, False

    async def _parse(self, schema: type[BaseModel], prompt: str) -> BaseModel | None:
        """JSON-mode structured extraction, one retry on validation failure."""
        schema_doc = _slim_schema(schema)
        messages = [
            {"role": "system",
             "content": ("You are a precise extraction engine. Reply with one JSON object "
                         f"that validates against this JSON schema, nothing else:\n{schema_doc}")},
            {"role": "user", "content": prompt},
        ]
        for _ in range(2):
            try:
                async with self._llm_sem:
                    resp = await self._chat({
                        "model": self.parser_model,
                        "messages": messages,
                        "temperature": 0,
                        "max_tokens": 700,
                        "response_format": {"type": "json_object"},
                    })
            except Exception:
                return None                       # caller falls back deterministically
            try:
                raw = resp.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError):
                return None                       # malformed 200 — same contract
            try:
                return schema.model_validate_json(raw)
            except ValidationError as exc:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user",
                                 "content": f"That failed validation: {exc.errors()[:3]}. "
                                            f"Reply with corrected JSON only."})
        return None

    def _resolve_cites(self, keys: list[str]) -> list[str]:
        return [self.c[k].id for k in keys if k in self.c]

    def _registry_doc(self) -> str:
        return "\n".join(f"- {key}: {cit.source}" for key, cit in self.c.items())

    # ---------------- overridden phases ----------------

    async def _plan(self) -> None:
        e = self.e
        e.phase_changed(Phase.PLAN, "Director scopes the engagement")
        e.agent_status(AgentId.DIRECTOR, "thinking")
        await self._stream_agent(
            AgentId.DIRECTOR,
            system=("You are the Research Director of DELPHI, a multi-agent equity research desk. "
                    "Brief, commanding, specific — 3 or 4 sentences of plain prose, no lists, no headers. "
                    "Scope the engagement, name the four workstreams (fundamentals, valuation, sentiment, "
                    "macro), and note that the Adversary and a compliance audit gate publication."),
            user=f"Open coverage on {self.b['company']} ({self.s.ticker}). Key facts: {self.digest[:2200]}",
            kind="direction", max_tokens=320,
            fallback=(f"Initiating coverage build on {self.b['company']} ({self.s.ticker}): four parallel "
                      f"workstreams — fundamentals, valuation, sentiment and macro — against the latest "
                      f"document set. The Adversary holds objection rights after first findings, and "
                      f"nothing reaches the note without surviving the compliance audit."))
        plan = [
            f"Index the {self.s.ticker} document set (10-K, 10-Q, 8-K, DEF 14A)",
            "Fundamentals: growth durability, margin bridge, quality scores",
            "Valuation: DCF + comps + scenario surface (engine-computed)",
            "Sentiment: positioning, insider tape, social skew",
            "Macro: rates, cycle, geographic exposure map",
            "Adversarial review — max 2 objection rounds",
            "Synthesis → conviction → audit → publish",
        ]
        self.s.plan = plan
        e.plan_ready(plan)
        e.agent_status(AgentId.DIRECTOR, "idle")

    # Deterministic tool theater per agent: engine truths the model narrates over.
    def _tool_lines(self, agent: AgentId) -> list[tuple[str, str, str]]:
        b, v = self.b, self.v
        latest = b["financials"][-1]
        d, mc = v["dcf"], v["monte_carlo"]
        geo = sorted(b["geo_revenue"], key=lambda r: -r["revenue_share"])
        if agent == AgentId.FUNDAMENTALS:
            return [
                ("edgar.fetch", f'ticker="{self.s.ticker}", forms=["10-K","10-Q"]',
                 f"{len(b.get('filings', []))} filings retrieved, section-aware chunks indexed"),
                ("facts.query", 'metrics=["revenue","ebit","fcf","margins"], periods=4',
                 f"FY{latest['year'][-4:]}: rev {self.sym}{latest['revenue_b']:.1f}B, op margin {latest['op_margin']:.1%}"),
            ]
        if agent == AgentId.VALUATION:
            return [
                ("engine.run_dcf",
                 f"g1={v['assumptions']['growth_path'][0]:.0%}, tg={v['assumptions']['terminal_growth']:.1%}",
                 f"{self.sym}{d['per_share']:.2f}/sh · EV {self.sym}{d['ev']:.0f}B · TV {d['tv_share_of_ev']:.0%} of EV"),
                ("engine.monte_carlo", "n=2000, seed=42",
                 f"p50 {self.sym}{mc['draws_stats']['p50']:.0f}, P(upside) {mc.get('prob_upside', 0.5):.0%}"),
            ]
        if agent == AgentId.SENTIMENT:
            soc = b["social"]
            return [
                ("social.stream", f'symbol="{self.s.ticker}", window="30d"',
                 f"{soc['reddit_mentions_30d']:,} Reddit mentions · {soc['stocktwits_sentiment']:.0%} bullish skew"),
                ("edgar.form4", 'window="6m"', b["ownership"]["form4_signal"]),
            ]
        mac = b["macro"]
        return [
            ("fred.series", 'ids=["DGS10","CPIAUCSL","FEDFUNDS"]',
             f"10y {mac['rf_10y']:.2%} · CPI {mac['cpi_yoy']:.1%} y/y · FF {mac['fed_funds']:.2%}"),
            ("filings.segments", 'item="geographic revenue"',
             f"{len(geo)} disclosed regions · top: {geo[0]['name']} at {geo[0]['revenue_share']:.0%}"),
        ]

    async def _parallel_research(self) -> None:
        self.e.phase_changed(Phase.PARALLEL_RESEARCH, "Four specialists fan out")
        for a in SPECIALIST_BRIEFS:
            self.s.views[a.value] = AgentView(agent=a)
        await asyncio.gather(*(self._specialist(a) for a in SPECIALIST_BRIEFS))
        cells, axes = analysis.sensitivity_cells(self.v)
        self.e.valuation_update(
            football_field=analysis.football_field(self.v),
            sensitivity=cells, sensitivity_axes=axes,
            monte_carlo=analysis.monte_carlo_summary(self.v))
        self.e.geo_exposure(analysis.geo_exposure(self.b))

    def _fallback_finding(self, agent: AgentId) -> str:
        """Data-grounded narration if the model is unreachable — never silence."""
        b, v = self.b, self.v
        fin = b["financials"]
        latest, prev = fin[-1], fin[-2]
        if agent == AgentId.FUNDAMENTALS:
            rev_g = latest["revenue_b"] / prev["revenue_b"] - 1
            pio = v["ratios"]["piotroski"]
            return (f"Top line grew {rev_g:+.1%} to {self.sym}{latest['revenue_b']:.1f}B at a "
                    f"{latest['op_margin']:.1%} operating margin, with Piotroski {pio['score']}/9 and "
                    f"Altman Z {v['ratios']['altman']['z']:.2f}. Free cash flow of {self.sym}{latest['fcf_b']:.1f}B "
                    f"funds the capex cycle internally.")
        if agent == AgentId.VALUATION:
            d = v["dcf"]
            up = d["per_share"] / v["last_price"] - 1
            return (f"Base DCF lands at {self.sym}{d['per_share']:.2f} against the {self.sym}{v['last_price']:.2f} tape "
                    f"({up:+.1%}) at a {d['wacc']:.1%} WACC, terminal value {d['tv_share_of_ev']:.0%} of EV. "
                    f"The Monte Carlo puts {v['monte_carlo'].get('prob_upside', 0.5):.0%} of paths above "
                    f"the current price.")
        if agent == AgentId.SENTIMENT:
            soc = b["social"]
            return (f"Positioning reads {soc['stocktwits_sentiment']:.0%} bullish with short interest at "
                    f"{soc['short_interest_pct']:.1%} of float; the insider tape shows "
                    f"{b['ownership']['form4_signal']}.")
        mac = b["macro"]
        geo = max(b["geo_revenue"], key=lambda r: r["revenue_share"])
        return (f"Rates backdrop workable — 10y {mac['rf_10y']:.2%}, CPI {mac['cpi_yoy']:.1%}. "
                f"Geography is the swing factor: {geo['name']} carries {geo['revenue_share']:.0%} "
                f"of revenue.")

    def _fallback_view(self, agent: AgentId, view: AgentView) -> None:
        """Deterministic stance + cited claims when structured parsing is down."""
        b, v = self.b, self.v
        fin = b["financials"]
        if agent == AgentId.FUNDAMENTALS:
            rev_g = fin[-1]["revenue_b"] / fin[-2]["revenue_b"] - 1
            view.stance = max(-2, min(2, rev_g * 4 + (0.5 if v["ratios"]["piotroski"]["score"] >= 6 else -0.5)))
            view.summary = f"Growth {rev_g:+.0%} with quality screens at {v['ratios']['piotroski']['score']}/9"
            self._claim(agent, f"Revenue grew {rev_g:+.1%} y/y to {self.sym}{fin[-1]['revenue_b']:.1f}B",
                        self._cite("xbrl", "10k"), 0.85)
        elif agent == AgentId.VALUATION:
            up = v["dcf"]["per_share"] / v["last_price"] - 1
            view.stance = max(-2, min(2, up * 6))
            view.summary = f"Engine triangulates {up:+.0%} vs the tape"
            self._claim(agent, f"DCF fair value {self.sym}{v['dcf']['per_share']:.2f}/share at WACC {v['dcf']['wacc']:.1%}",
                        self._cite("engine"), 0.85)
        elif agent == AgentId.SENTIMENT:
            bullish = b["social"]["stocktwits_sentiment"]
            view.stance = max(-2, min(2, (bullish - 0.6) * 2))
            view.summary = f"Positioning {bullish:.0%} bullish — tailwind, not edge"
            self._claim(agent, f"Retail skew {bullish:.0%} bullish, short interest {b['social']['short_interest_pct']:.1%}",
                        self._cite("social"), 0.7)
        else:
            geo = max(b["geo_revenue"], key=lambda r: r["revenue_share"])
            view.stance = 0.3
            view.summary = f"Macro neutral; {geo['name']} {geo['revenue_share']:.0%} is the swing factor"
            self._claim(agent, f"{geo['name']} concentration at {geo['revenue_share']:.0%} of revenue",
                        self._cite("segments"), 0.8)

    async def _specialist(self, agent: AgentId) -> None:
        e = self.e
        e.agent_status(agent, "reading")
        for tool, args, result in self._tool_lines(agent):
            await self._tool(agent, tool, args, result, think=0.5)
        e.agent_status(agent, "thinking")
        text, live = await self._stream_agent(
            agent,
            system=(SPECIALIST_BRIEFS[agent] +
                    " Write 4-6 sentences of confident desk prose. Every figure must come from the "
                    "fact digest — never invent numbers. No headers, no bullet points, no preamble."),
            user=f"Fact digest for {self.b['company']} ({self.s.ticker}):\n{self.digest}",
            kind="finding", fallback=self._fallback_finding(agent))

        parsed = None
        if live:
            parsed = await self._parse(ParsedView, (
                f"Extract the analyst view from this research finding.\n\nFINDING:\n{text}\n\n"
                f"CITATION REGISTRY (use these keys in citation_keys):\n{self._registry_doc()}\n\n"
                "Pick 2-4 numeric claims faithful to the finding, each with the registry keys that "
                "genuinely back it (filings/xbrl for financials, engine for model outputs, social/form4 "
                "for positioning, fred for macro, segments for geography)."))

        view = self.s.views[agent.value]
        if isinstance(parsed, ParsedView):
            view.stance = parsed.stance
            view.summary = parsed.summary
            for pc in parsed.claims:
                self._claim(agent, pc.text, self._resolve_cites(pc.citation_keys), pc.confidence)
            view.key_numbers = [KeyNumber(**kn.model_dump()) for kn in parsed.key_numbers]
        else:
            self._fallback_view(agent, view)
        e.key_numbers(agent, view.key_numbers)
        e.view_ready(agent, view.stance, view.summary)
        e.agent_status(agent, "done")

    async def _adversary_round(self, rnd: int) -> None:
        e = self.e
        phase = Phase.ADVERSARY_ROUND_1 if rnd == 1 else Phase.ADVERSARY_ROUND_2
        e.phase_changed(phase, "Objections filed" if rnd == 1 else "Standing objections pressed")
        e.agent_status(AgentId.ADVERSARY, "thinking")

        views_doc = "\n\n".join(
            f"[{v.agent.value}] stance={v.stance:+.1f} — {v.summary}\n" +
            "\n".join(f"  claim {c.id}: {c.text}" for c in v.claims)
            for v in self.s.views.values())

        if rnd == 1:
            text, live = await self._stream_agent(
                AgentId.ADVERSARY,
                system=("You are the Adversary — the institutional bear-case agent. Find what breaks "
                        "the thesis; don't be reflexively negative. File exactly 3 sharp objections "
                        "against the weakest claims, each referencing actual numbers. Number them 1-3, "
                        "plain prose."),
                user=f"Specialist findings:\n{views_doc}\n\nEngine facts: {self.digest[:2000]}",
                kind="objection", max_tokens=700,
                fallback=("I've read all four workstreams. Three objections follow, weighted by what "
                          "they should cost the desk's conviction if they stand."))
            parsed = None
            if live:
                parsed = await self._parse(ParsedObjections, (
                    f"Extract the objections from this adversarial review:\n{text}\n\n"
                    "For each: target_agent (fundamentals|valuation|sentiment|macro), the complete "
                    "objection text, and weight 3-15 (conviction points at stake)."))
            objections = parsed.objections if isinstance(parsed, ParsedObjections) else []
            if not objections:                      # never let the debate die silent
                self._rules = self._objection_rules()
                for i, r in enumerate(self._rules[:3], 1):
                    o = Objection(id=f"O{i}", round=1, target_agent=r["target"],
                                  target_claim_id=self._claim_for(r["target"]),
                                  text=r["text"], weight=r["weight"])
                    self.s.objections.append(o)
                    e.objection_filed(o)
            else:
                for i, po in enumerate(objections, 1):
                    o = Objection(id=f"O{i}", round=1, target_agent=AgentId(po.target_agent),
                                  target_claim_id=self._claim_for(AgentId(po.target_agent)),
                                  text=po.text, weight=round(po.weight, 1))
                    self.s.objections.append(o)
                    e.objection_filed(o)
                    await asyncio.sleep(_pace(0.3))
        else:
            standing = [vd for vd in self.s.verdicts if vd.status == "standing"]
            summary = ("No objections survived rebuttal."
                       if not standing else
                       f"{len(standing)} objection(s) still standing: " + "; ".join(
                           next(o.text for o in self.s.objections if o.id == vd.objection_id)[:120]
                           for vd in standing))
            await self._stream_agent(
                AgentId.ADVERSARY,
                system=("You are the Adversary closing round two — 2 or 3 sentences. If objections "
                        "stand, press the strongest and state it stays on the risk register at full "
                        "weight. If none stand, concede cleanly: evidence won."),
                user=summary, kind="objection", max_tokens=220,
                fallback=(summary + " It stays on the risk register at full weight — that's the discipline."
                          if standing else
                          "The rebuttals held — engine reruns and primary-source cites. Withdrawn."))
        e.agent_status(AgentId.ADVERSARY, "done")

    async def _rebuttals(self) -> None:
        e = self.e
        e.phase_changed(Phase.REBUTTAL, "Specialists respond with evidence")
        bear = self.v["dcf_bear"]
        for i, o in enumerate(self.s.objections, 1):
            agent = o.target_agent
            e.agent_status(agent, "rebutting")
            evidence = ""
            if agent == AgentId.VALUATION:
                await self._tool(agent, "engine.run_dcf",
                                 "growth ×0.6, margin stress, tg=2.5% (bear rerun)",
                                 f"bear case {self.sym}{bear['per_share']:.2f}/sh", 0.6)
                evidence = (f"\nFresh engine rerun you may cite: bear-case DCF prints "
                            f"{self.sym}{bear['per_share']:.2f} against the {self.sym}{self.v['last_price']:.2f} tape.")
            text, live = await self._stream_agent(
                agent,
                system=(SPECIALIST_BRIEFS[agent] +
                        " The Adversary objected to your work. Rebut in 2-4 sentences with evidence. "
                        "Concede what is true; quantify what can be bounded. Never bluster."),
                user=f"OBJECTION: {o.text}\n\nYour fact digest: {self.digest[:2000]}{evidence}",
                kind="rebuttal", max_tokens=320,
                fallback=(f"The risk is real and it is bounded: the engine's bear case prints "
                          f"{self.sym}{bear['per_share']:.2f} against the {self.sym}{self.v['last_price']:.2f} tape — "
                          f"that is the floor we underwrite, priced in the note rather than waved away."))
            r = Rebuttal(id=f"R{i}", objection_id=o.id, agent=agent, text=text,
                         citation_ids=self._cite("engine"))
            self.s.rebuttals.append(r)
            e.rebuttal_filed(r)

            pv = await self._parse(ParsedVerdict, (
                f"You are a neutral debate judge.\nOBJECTION: {o.text}\nREBUTTAL: {text}\n\n"
                "Verdict: 'refuted' if the rebuttal disproves the premise with evidence; 'mitigated' "
                "if it bounds the risk credibly; 'standing' if the core exposure remains. "
                "One-sentence rationale.")) if live else None
            status = pv.status if isinstance(pv, ParsedVerdict) else "mitigated"
            rationale = pv.rationale if isinstance(pv, ParsedVerdict) else \
                "Risk quantified and bounded by the engine's bear case; partial weight applies."
            vd = Verdict(objection_id=o.id, status=status, rationale=rationale,
                         penalty_applied=o.weight if status == "standing"
                         else (o.weight * 0.35 if status == "mitigated" else 0.0))
            self.s.verdicts.append(vd)
            e.verdict_rendered(vd)
            e.agent_status(agent, "done")

    async def _synthesis(self) -> None:
        e, s = self.e, self.s
        e.phase_changed(Phase.SYNTHESIS, "Director assembles thesis + conviction")
        e.agent_status(AgentId.DIRECTOR, "thinking")

        rating = self._build_rating()
        s.rating = rating
        views = list(s.views.values())
        uncited = sum(1 for vw in views for c in vw.claims if not c.citation_ids)
        conv = conviction.score(views, s.objections, s.verdicts, uncited)
        s.conviction = conv

        street_mean = self.v["analyst_targets"]["mean"]
        street_doc = f"{self.sym}{street_mean:.0f}" if street_mean is not None else "unavailable (no coverage)"

        debate_doc = "\n".join(
            f"O: {o.text[:150]} → {next((vd.status for vd in s.verdicts if vd.objection_id == o.id), '?')}"
            for o in s.objections)
        text, live = await self._stream_agent(
            AgentId.DIRECTOR,
            system=("You are the Research Director synthesizing the debate — 4-6 sentences of plain "
                    "prose. State the call, why the engine's target differs from the street (the "
                    "variant perception), and how surviving objections are priced. Reference the "
                    "conviction breakdown explicitly: the number is a formula, not a feeling."),
            user=(f"Rating: {rating.action}, target {self.sym}{rating.price_target:.2f} vs {self.sym}{rating.last_price:.2f} "
                  f"({rating.upside_pct:+.1%}). Conviction {conv.final:.0f} = base {conv.base_agreement:.0f} "
                  f"− objections {conv.objection_penalty:.0f} − citations {conv.citation_penalty:.0f}.\n"
                  f"Street mean target: {street_doc}.\n"
                  f"Debate outcomes:\n{debate_doc}\n\nStances: "
                  + ", ".join(f"{v.agent.value} {v.stance:+.1f}" for v in views)),
            kind="direction", max_tokens=450,
            fallback=(f"Synthesis: {rating.action} with a {self.sym}{rating.price_target:.2f} target against "
                      f"{self.sym}{rating.last_price:.2f} ({rating.upside_pct:+.1%}). Conviction {conv.final:.0f} "
                      f"is the formula — {conv.base_agreement:.0f} base agreement minus "
                      f"{conv.objection_penalty:.0f} for surviving objections minus "
                      f"{conv.citation_penalty:.0f} in citation penalties. The street sits at "
                      f"{self.sym}{self.v['analyst_targets']['mean']:.0f}; the engine prices the cash flows."))

        parsed = await self._parse(ParsedSynthesis, (
            f"Extract the thesis from this synthesis:\n{text}\n\n"
            "headline: one line with rating + target. Exactly 3 pillar_titles and 3 pillar_texts "
            "(short, specific). variant_perception: where and why this view differs from consensus.")) if live else None
        if isinstance(parsed, ParsedSynthesis):
            pillars = [ThesisPillar(title=t, text=x, citation_ids=self._cite("engine", "xbrl"))
                       for t, x in zip(parsed.pillar_titles, parsed.pillar_texts)]
            thesis = Thesis(headline=parsed.headline, pillars=pillars,
                            variant_perception=parsed.variant_perception)
        else:
            thesis = Thesis(
                headline=(f"{self.b['company']}: {rating.action.title().replace('-', ' ')} — "
                          f"{self.sym}{rating.price_target:.0f} target, conviction {conv.final:.0f}/100"),
                pillars=[ThesisPillar(title="Synthesis on file", text=text[:200],
                                      citation_ids=self._cite("engine"))],
                variant_perception=f"Engine target {self.sym}{rating.price_target:.0f} vs street {street_doc}.")
        s.thesis = thesis
        e.thesis_ready(thesis)
        e.rating_ready(rating)
        e.conviction_update(conv)
        e.agent_status(AgentId.DIRECTOR, "done")

    async def _revise(self) -> None:
        e, s = self.e, self.s
        e.phase_changed(Phase.REVISE, "Audit failure loops back — once")
        removed = 0
        for view in s.views.values():
            kept = [c for c in view.claims if c.citation_ids]
            removed += len(view.claims) - len(kept)
            view.claims = kept
        await self._stream_agent(
            AgentId.DIRECTOR,
            system="You are the Research Director — 2 sentences: acknowledge the audit failure and state the fix.",
            user=f"The Auditor struck {removed} uncited claim(s). They are removed; conviction re-scores without them.",
            kind="direction", max_tokens=160,
            fallback=(f"Auditor's right — {removed} uncited claim(s) struck from the record and conviction "
                      f"re-scored without them. The note only carries what survives."))
        conv = conviction.score(list(s.views.values()), s.objections, s.verdicts, 0)
        s.conviction = conv
        e.conviction_update(conv)

    def _publish(self) -> None:
        super()._publish()
        if self.s.note:
            self.s.note.mode = "live"
