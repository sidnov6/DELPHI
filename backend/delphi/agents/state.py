"""ResearchState — the typed spine of the debate graph.

Agents make judgments; engines make calculations. Everything an agent
asserts lives here as a Claim with citations; everything the engine
computes lives here as typed numbers. The UI renders this state as it
assembles, event by event.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Phase(str, Enum):
    PLAN = "PLAN"
    PARALLEL_RESEARCH = "PARALLEL_RESEARCH"
    ADVERSARY_ROUND_1 = "ADVERSARY_ROUND_1"
    REBUTTAL = "REBUTTAL"
    ADVERSARY_ROUND_2 = "ADVERSARY_ROUND_2"
    SYNTHESIS = "SYNTHESIS"
    AUDIT = "AUDIT"
    PUBLISH = "PUBLISH"
    REVISE = "REVISE"


class AgentId(str, Enum):
    DIRECTOR = "director"
    FUNDAMENTALS = "fundamentals"
    VALUATION = "valuation"
    SENTIMENT = "sentiment"
    MACRO = "macro"
    ADVERSARY = "adversary"
    AUDITOR = "auditor"


AGENT_LABELS: dict[AgentId, str] = {
    AgentId.DIRECTOR: "Research Director",
    AgentId.FUNDAMENTALS: "Fundamentals Analyst",
    AgentId.VALUATION: "Valuation Analyst",
    AgentId.SENTIMENT: "Sentiment Analyst",
    AgentId.MACRO: "Macro & Industry Analyst",
    AgentId.ADVERSARY: "Adversary",
    AgentId.AUDITOR: "Compliance Auditor",
}


class Citation(BaseModel):
    id: str
    source: str                      # "10-K FY2025 · Item 7", "XBRL us-gaap:Revenues", "FRED DGS10"
    doc_type: str                    # filing | xbrl | market | macro | social | engine
    url: Optional[str] = None
    snippet: Optional[str] = None


class Claim(BaseModel):
    id: str
    agent: AgentId
    text: str
    citation_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.6          # 0..1


class KeyNumber(BaseModel):
    label: str
    value: str                       # pre-formatted for display
    delta: Optional[str] = None      # e.g. "+12.4% y/y"
    tone: Literal["pos", "neg", "neutral"] = "neutral"


class AgentView(BaseModel):
    agent: AgentId
    stance: float = 0.0              # -2 (bearish) .. +2 (bullish)
    summary: str = ""
    claims: list[Claim] = Field(default_factory=list)
    key_numbers: list[KeyNumber] = Field(default_factory=list)


class Objection(BaseModel):
    id: str
    round: int                       # 1 | 2
    target_agent: AgentId
    target_claim_id: Optional[str] = None
    text: str
    weight: float = 8.0              # conviction points at stake if standing


class Rebuttal(BaseModel):
    id: str
    objection_id: str
    agent: AgentId
    text: str
    citation_ids: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    objection_id: str
    status: Literal["refuted", "mitigated", "standing"]
    rationale: str
    penalty_applied: float = 0.0


class ThesisPillar(BaseModel):
    title: str
    text: str
    citation_ids: list[str] = Field(default_factory=list)


class Thesis(BaseModel):
    headline: str
    pillars: list[ThesisPillar] = Field(default_factory=list)
    variant_perception: str = ""     # where we differ from consensus, and why


class Rating(BaseModel):
    action: Literal["OVERWEIGHT", "EQUAL-WEIGHT", "UNDERWEIGHT"]
    price_target: float
    bull_target: float
    bear_target: float
    last_price: float
    upside_pct: float
    horizon_months: int = 12


class ConvictionBreakdown(BaseModel):
    base_agreement: float            # from cross-specialist stance agreement
    objection_penalty: float         # Σ standing objection weights
    citation_penalty: float          # uncited-claim penalty from auditor
    final: float                     # clamped 0..100


class FootballFieldBar(BaseModel):
    method: str                      # "DCF (Gordon)", "EV/EBITDA comps", ...
    low: float
    high: float
    mid: float


class ScenarioCell(BaseModel):
    row: float                       # e.g. WACC value
    col: float                       # e.g. terminal growth value
    value: float                     # implied share price


class MonteCarloSummary(BaseModel):
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    prob_upside: float               # P(value > last price)
    histogram: list[float] = Field(default_factory=list)   # bin counts
    bin_edges: list[float] = Field(default_factory=list)


class MapRegion(BaseModel):
    iso_n3: str                      # numeric ISO 3166-1 (matches world-atlas ids)
    name: str
    revenue_share: float             # 0..1
    revenue_usd_b: Optional[float] = None
    note: Optional[str] = None


class MapArc(BaseModel):
    src: tuple[float, float]         # lon, lat
    dst: tuple[float, float]
    label: str
    kind: Literal["hq", "supply", "demand", "risk"] = "demand"


class GeoExposure(BaseModel):
    regions: list[MapRegion] = Field(default_factory=list)
    arcs: list[MapArc] = Field(default_factory=list)
    hq: Optional[tuple[float, float]] = None
    commentary: str = ""


class RiskItem(BaseModel):
    title: str
    severity: Literal["low", "medium", "high"]
    probability: Literal["low", "medium", "high"]
    text: str
    mitigant: Optional[str] = None


class AuditCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class MarketSnapshot(BaseModel):
    ticker: str
    company: str
    as_of: Optional[str] = None      # tape date — surfaced so staleness is visible
    last_price: float
    currency: str = "USD"
    market_cap_b: Optional[float] = None
    pe_fwd: Optional[float] = None
    ev_ebitda: Optional[float] = None
    week52_low: Optional[float] = None
    week52_high: Optional[float] = None
    price_history: list[float] = Field(default_factory=list)   # ~1y daily closes
    sector: Optional[str] = None


class ResearchNote(BaseModel):
    """The publishable artifact — dual output: machine-readable + rendered."""
    run_id: str
    ticker: str
    company: str
    generated_at: str
    mode: Literal["live", "simulation"]
    snapshot: MarketSnapshot
    rating: Rating
    conviction: ConvictionBreakdown
    thesis: Thesis
    views: list[AgentView]
    objections: list[Objection]
    rebuttals: list[Rebuttal]
    verdicts: list[Verdict]
    football_field: list[FootballFieldBar]
    sensitivity: list[ScenarioCell]
    sensitivity_axes: dict[str, list[float]]    # {"rows": [...waccs], "cols": [...growths]}
    monte_carlo: MonteCarloSummary
    geo: GeoExposure
    risks: list[RiskItem]
    audit: list[AuditCheck]
    citations: list[Citation]
    financial_summary: list[KeyNumber]


class ResearchState(BaseModel):
    """Mutable state threaded through the graph. The UI mirrors this via events."""
    run_id: str
    ticker: str
    company: str = ""
    mode: Literal["live", "simulation"] = "simulation"
    phase: Phase = Phase.PLAN
    plan: list[str] = Field(default_factory=list)
    snapshot: Optional[MarketSnapshot] = None
    views: dict[str, AgentView] = Field(default_factory=dict)
    objections: list[Objection] = Field(default_factory=list)
    rebuttals: list[Rebuttal] = Field(default_factory=list)
    verdicts: list[Verdict] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    thesis: Optional[Thesis] = None
    rating: Optional[Rating] = None
    conviction: Optional[ConvictionBreakdown] = None
    audit: list[AuditCheck] = Field(default_factory=list)
    note: Optional[ResearchNote] = None
    revision_count: int = 0
