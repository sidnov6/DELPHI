# DELPHI — Multi-Agent Equity Research

Seven agents argue over every name — four specialists, an adversary with objection
rights, an auditor with a veto. Only what survives gets published.

DELPHI replicates the workflow of a sell-side equity research team: a Research
Director scopes the engagement, four specialists (Fundamentals, Valuation,
Sentiment, Macro) research in parallel against real document sets, an Adversary
files weighted objections, specialists rebut with engine reruns and primary-source
citations, and a Compliance Auditor gates publication — citation enforcement,
numeric verification against the fact store, one revision loop. The output is a
dual research note: machine-readable JSON and a rendered editorial page with a
football field, scenario surface, Monte Carlo distribution, global exposure map,
debate transcript and risk register.

> *Agents make judgments; engines make calculations. The boundary between the two
> is the architecture.*

## The debate protocol

```
PLAN → PARALLEL_RESEARCH → [fund, val, sent, macro complete]
     → ADVERSARY_ROUND_1 (objections filed)
     → REBUTTAL          (specialists respond, may re-query tools)
     → ADVERSARY_ROUND_2 (press standing objections, max 2 rounds)
     → SYNTHESIS         (Director: thesis + conviction scoring)
     → AUDIT             (Compliance agent)
     → PUBLISH | REVISE  (audit failure loops back once)
```

Conviction is a transparent formula, not a vibe:

```
conviction = base(agreement across specialists)
           − Σ(standing objection weights)
           − citation_penalty
```

## Quick start

```bash
# backend (Python 3.11+)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
DELPHI_OFFLINE=1 .venv/bin/python -m uvicorn delphi.api.main:app --port 8000

# frontend (Node 20+) — second terminal
cd frontend
npm install
npm run dev          # → http://localhost:5173
```

Open the app and search **any US- or European-listed company** — every SEC
registrant plus the European exchanges (LSE, Euronext, XETRA, SIX, Nasdaq
Nordic, …) via keyless Yahoo/EDGAR sourcing, with bundles built live and cached:
financials FX-converted into the quote currency (GBp pence handled), domicile
geography honestly labeled where segment disclosure isn't parsed, and
sector-reference comps where no street tape exists. Six featured names (NVDA,
TSLA, MSFT, AAPL, AMZN, GOOGL) ship as rich offline fixtures with full
geographic segmentation. A full debate runs ~45 seconds in simulation mode.

Note the boundary: coverage means *publicly traded* companies — a privately
registered GmbH has no public financials or market price, so there is nothing
to value or debate. With `DELPHI_OFFLINE=1`, coverage is the 6 fixtures only.

### Modes

| Mode | Trigger | What happens |
|---|---|---|
| **Simulation** (default) | no API key | Data-grounded personas: every figure comes from the deterministic engine run; objections fire from rule triggers on the actual numbers, so NVDA argues about terminal-value dependence while TSLA argues about margin compression. Works fully offline. |
| **Live · Anthropic** | `ANTHROPIC_API_KEY` set | Real Claude agents over the same protocol — Opus (`claude-opus-4-8`) for the Director and Adversary, Sonnet (`claude-sonnet-4-6`) for specialists with engine tools, Haiku for structured parsing. Override via `DELPHI_MODEL_DIRECTOR` / `DELPHI_MODEL_SPECIALIST` / `DELPHI_MODEL_PARSER`. |
| **Live · Groq** | `GROQ_API_KEY` set | Open models (Llama 3.3 70B narrating, Llama 3.1 8B parsing — auto-selected from Groq's catalog, override via `DELPHI_GROQ_MODEL` / `DELPHI_GROQ_MODEL_PARSER`). Calls are serialized and 429s honored for free-tier TPM limits; if a call can't get through, that turn degrades to data-grounded narration so the debate always completes. Anthropic wins if both keys are set. |

Keys load from `backend/.env` (gitignored) or the environment. Other knobs:
`DELPHI_OFFLINE=1` (skip live data providers entirely), `DELPHI_SIM_SPEED=2`
(faster debate; tests use 80).

### CLI

```bash
cd backend
DELPHI_OFFLINE=1 .venv/bin/python -m delphi.cli run NVDA   # debate on stderr, note JSON on stdout
```

### Tests

```bash
cd backend && .venv/bin/python -m pytest tests/ -q          # engine + data layer, 68 tests
```

## Architecture

```
backend/delphi/
├── data/
│   ├── providers/            # Adapter pattern — one file per source
│   │   ├── base.py           # Provider ABCs ("at a bank, you'd drop the
│   │   │                     #  Refinitiv adapter behind the same interface")
│   │   ├── market.py         # yfinance wrapper
│   │   ├── edgar.py          # SEC submissions API (keyless, real CIKs)
│   │   ├── fred.py           # keyless fredgraph CSV (DGS10/CPI/FF)
│   │   ├── sentiment_social.py  # StockTwits public API
│   │   └── estimates.py      # consensus snapshot adapter
│   ├── fixtures/             # 6 rich offline snapshots — the demo guarantee
│   ├── cache.py              # sqlite TTL cache keyed (ticker, source)
│   └── bundle.py             # fixture base + live deep-merge
├── engine/                   # Deterministic — zero LLM, pytest-covered
│   ├── dcf.py                # FCF build, CAPM WACC, Gordon + exit-multiple TV
│   ├── comps.py              # peer multiples, winsorization, implied ranges
│   ├── ratios.py             # DuPont, Altman Z, Piotroski F, CCC
│   └── scenarios.py          # sensitivity grids, tornado, Monte Carlo
├── agents/
│   ├── state.py              # ResearchState — the typed spine
│   ├── events.py             # SSE wire protocol + async fan-out bus
│   ├── analysis.py           # bundle → engine artifacts (the judgment/calc seam)
│   ├── conviction.py         # the transparent scoring formula
│   ├── auditor.py            # citation enforcement + numeric verification
│   ├── sim.py                # simulation personas (keyless demo mode)
│   ├── llm.py                # live Claude agents (streaming + tool use)
│   └── graph.py              # debate state machine, run lifecycle
├── api/main.py               # FastAPI: POST /api/runs, SSE events, report JSON
└── cli.py                    # delphi run NVDA

frontend/src/
├── styles.css                # the design system — OKLCH tokens, oracle theme
├── lib/                      # types (event mirror), SSE store, formatters
├── components/
│   ├── feed.tsx              # debate theater: streams, tool calls, threads
│   ├── panels.tsx            # pipeline rail, agent roster, dossier
│   ├── charts.tsx            # football field, heatmap, Monte Carlo, gauge
│   └── GlobalMap.tsx         # d3-geo choropleth + animated flow arcs
└── pages/                    # Landing, RunView (theater), NoteView (editorial)
```

### Data constraint: 100% free

EDGAR, XBRL facts, yfinance, FRED CSV, StockTwits — every source is free or
free-tier, with sqlite caching. The bundled fixtures (dated snapshots, Jan 2026)
guarantee the system works fully offline; live providers enrich when reachable
and fall back silently.

DELPHI · Part of the Finance × AI agentic portfolio: PRAETOR · ARGUS · CERBERUS · CADUCEUS · AEOLUS · DELPHI
