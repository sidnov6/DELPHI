/** Mirrors backend/delphi/agents/state.py + events.py. Keep in lockstep. */

export type AgentId =
  | "director" | "fundamentals" | "valuation" | "sentiment"
  | "macro" | "adversary" | "auditor";

export type PhaseId =
  | "PLAN" | "PARALLEL_RESEARCH" | "ADVERSARY_ROUND_1" | "REBUTTAL"
  | "ADVERSARY_ROUND_2" | "SYNTHESIS" | "AUDIT" | "PUBLISH" | "REVISE";

export type AgentStatus = "idle" | "reading" | "thinking" | "speaking" | "rebutting" | "done";

export interface Citation {
  id: string;
  source: string;
  doc_type: string;
  url?: string | null;
  snippet?: string | null;
}

export interface Claim {
  id: string;
  agent: AgentId;
  text: string;
  citation_ids: string[];
  confidence: number;
}

export interface KeyNumber {
  label: string;
  value: string;
  delta?: string | null;
  tone: "pos" | "neg" | "neutral";
}

export interface Objection {
  id: string;
  round: number;
  target_agent: AgentId;
  target_claim_id?: string | null;
  text: string;
  weight: number;
}

export interface Rebuttal {
  id: string;
  objection_id: string;
  agent: AgentId;
  text: string;
  citation_ids: string[];
}

export interface Verdict {
  objection_id: string;
  status: "refuted" | "mitigated" | "standing";
  rationale: string;
  penalty_applied: number;
}

export interface ThesisPillar { title: string; text: string; citation_ids: string[]; }
export interface Thesis { headline: string; pillars: ThesisPillar[]; variant_perception: string; }

export interface Rating {
  action: "OVERWEIGHT" | "EQUAL-WEIGHT" | "UNDERWEIGHT";
  price_target: number;
  bull_target: number;
  bear_target: number;
  last_price: number;
  upside_pct: number;
  horizon_months: number;
}

export interface ConvictionBreakdown {
  base_agreement: number;
  objection_penalty: number;
  citation_penalty: number;
  final: number;
}

export interface FootballFieldBar { method: string; low: number; high: number; mid: number; }
export interface ScenarioCell { row: number; col: number; value: number; }

export interface MonteCarloSummary {
  p5: number; p25: number; p50: number; p75: number; p95: number;
  prob_upside: number;
  histogram: number[];
  bin_edges: number[];
}

export interface MapRegion {
  iso_n3: string;
  name: string;
  revenue_share: number;
  revenue_usd_b?: number | null;
  note?: string | null;
}

export interface MapArc {
  src: [number, number];
  dst: [number, number];
  label: string;
  kind: "hq" | "supply" | "demand" | "risk";
}

export interface GeoExposure {
  regions: MapRegion[];
  arcs: MapArc[];
  hq?: [number, number] | null;
  commentary: string;
}

export interface RiskItem {
  title: string;
  severity: "low" | "medium" | "high";
  probability: "low" | "medium" | "high";
  text: string;
  mitigant?: string | null;
}

export interface AuditCheck { name: string; passed: boolean; detail: string; }

export interface MarketSnapshot {
  ticker: string;
  company: string;
  last_price: number;
  currency: string;
  market_cap_b?: number | null;
  pe_fwd?: number | null;
  ev_ebitda?: number | null;
  week52_low?: number | null;
  week52_high?: number | null;
  price_history: number[];
  sector?: string | null;
}

export interface AgentViewT {
  agent: AgentId;
  stance: number;
  summary: string;
  claims: Claim[];
  key_numbers: KeyNumber[];
}

export interface ResearchNote {
  run_id: string;
  ticker: string;
  company: string;
  generated_at: string;
  mode: "live" | "simulation";
  snapshot: MarketSnapshot;
  rating: Rating;
  conviction: ConvictionBreakdown;
  thesis: Thesis;
  views: AgentViewT[];
  objections: Objection[];
  rebuttals: Rebuttal[];
  verdicts: Verdict[];
  football_field: FootballFieldBar[];
  sensitivity: ScenarioCell[];
  sensitivity_axes: { rows: number[]; cols: number[] };
  monte_carlo: MonteCarloSummary;
  geo: GeoExposure;
  risks: RiskItem[];
  audit: AuditCheck[];
  citations: Citation[];
  financial_summary: KeyNumber[];
}

/* ---------------- feed model (built from SSE events) ---------------- */

export interface FeedMessage {
  type: "message";
  id: string;
  agent: AgentId;
  kind: string;          // finding | direction | objection | rebuttal | audit
  text: string;
  streaming: boolean;
}

export interface FeedToolCall {
  type: "tool";
  id: string;
  agent: AgentId;
  tool: string;
  args: string;
  result?: string;
}

export interface FeedObjection { type: "objection"; objection: Objection; }
export interface FeedRebuttal { type: "rebuttal"; rebuttal: Rebuttal; }
export interface FeedVerdict { type: "verdict"; verdict: Verdict; }
export interface FeedPhase { type: "phase"; phase: PhaseId; detail: string; }
export interface FeedClaim { type: "claim"; claim: Claim; }

export type FeedItem =
  | FeedMessage | FeedToolCall | FeedObjection | FeedRebuttal
  | FeedVerdict | FeedPhase | FeedClaim;

export const AGENT_META: Record<AgentId, { label: string; short: string; hue: string }> = {
  director:     { label: "Research Director",        short: "DIR", hue: "var(--a-director)" },
  fundamentals: { label: "Fundamentals Analyst",     short: "FUN", hue: "var(--a-fundamentals)" },
  valuation:    { label: "Valuation Analyst",        short: "VAL", hue: "var(--a-valuation)" },
  sentiment:    { label: "Sentiment Analyst",        short: "SEN", hue: "var(--a-sentiment)" },
  macro:        { label: "Macro & Industry Analyst", short: "MAC", hue: "var(--a-macro)" },
  adversary:    { label: "Adversary",                short: "ADV", hue: "var(--a-adversary)" },
  auditor:      { label: "Compliance Auditor",       short: "AUD", hue: "var(--a-auditor)" },
};

export const PHASE_SEQUENCE: { id: PhaseId; label: string }[] = [
  { id: "PLAN", label: "Plan" },
  { id: "PARALLEL_RESEARCH", label: "Parallel research" },
  { id: "ADVERSARY_ROUND_1", label: "Adversary · round 1" },
  { id: "REBUTTAL", label: "Rebuttal" },
  { id: "ADVERSARY_ROUND_2", label: "Adversary · round 2" },
  { id: "SYNTHESIS", label: "Synthesis" },
  { id: "AUDIT", label: "Audit" },
  { id: "PUBLISH", label: "Publish" },
];
