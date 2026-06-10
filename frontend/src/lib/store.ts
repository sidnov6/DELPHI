/** SSE consumer + run state reducer. One store per run, framework-agnostic. */
import type {
  AgentId, AgentStatus, AuditCheck, Citation, ConvictionBreakdown, FeedItem,
  FootballFieldBar, GeoExposure, KeyNumber, MarketSnapshot, MonteCarloSummary,
  PhaseId, Rating, ScenarioCell, Thesis,
} from "./types";

export interface RunState {
  runId: string;
  ticker: string;
  company: string;
  mode: "live" | "simulation" | null;
  phase: PhaseId | null;
  phaseDetail: string;
  plan: string[];
  feed: FeedItem[];
  agentStatus: Partial<Record<AgentId, AgentStatus>>;
  agentStance: Partial<Record<AgentId, number>>;
  agentSummary: Partial<Record<AgentId, string>>;
  agentNumbers: Partial<Record<AgentId, KeyNumber[]>>;
  snapshot: MarketSnapshot | null;
  citations: Citation[];
  footballField: FootballFieldBar[];
  sensitivity: ScenarioCell[];
  sensitivityAxes: { rows: number[]; cols: number[] } | null;
  monteCarlo: MonteCarloSummary | null;
  geo: GeoExposure | null;
  conviction: ConvictionBreakdown | null;
  thesis: Thesis | null;
  rating: Rating | null;
  audit: AuditCheck[];
  published: boolean;
  failed: string | null;
  done: boolean;
}

export function initialRunState(runId: string, ticker: string): RunState {
  return {
    runId, ticker, company: "", mode: null, phase: null, phaseDetail: "",
    plan: [], feed: [], agentStatus: {}, agentStance: {}, agentSummary: {},
    agentNumbers: {}, snapshot: null, citations: [], footballField: [],
    sensitivity: [], sensitivityAxes: null, monteCarlo: null, geo: null,
    conviction: null, thesis: null, rating: null, audit: [],
    published: false, failed: null, done: false,
  };
}

type Listener = () => void;

export class RunStore {
  state: RunState;
  private listeners = new Set<Listener>();
  private es: EventSource | null = null;
  private msgIndex = new Map<string, number>();   // message id → feed index

  constructor(runId: string, ticker: string) {
    this.state = initialRunState(runId, ticker);
  }

  subscribe = (fn: Listener): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  getSnapshot = (): RunState => this.state;

  private commit(partial: Partial<RunState>) {
    this.state = { ...this.state, ...partial };
    this.listeners.forEach((fn) => fn());
  }

  private push(item: FeedItem, rest: Partial<RunState> = {}) {
    this.commit({ feed: [...this.state.feed, item], ...rest });
  }

  connect() {
    const es = new EventSource(`/api/runs/${this.state.runId}/events`);
    this.es = es;
    const on = (type: string, fn: (d: any) => void) =>
      es.addEventListener(type, (ev) => fn(JSON.parse((ev as MessageEvent).data)));

    on("run_started", (d) => this.commit({ company: d.company, mode: d.mode }));
    on("phase_changed", (d) => {
      if (this.state.phase === d.phase) {
        // Same phase re-announced (e.g. sourcing → director's PLAN):
        // refresh the detail, don't stack a duplicate divider.
        this.commit({ phaseDetail: d.detail });
        return;
      }
      this.push({ type: "phase", phase: d.phase, detail: d.detail },
        { phase: d.phase, phaseDetail: d.detail, published: d.phase === "PUBLISH" || this.state.published });
    });
    on("plan_ready", (d) => this.commit({ plan: d.items }));
    on("agent_status", (d) =>
      this.commit({ agentStatus: { ...this.state.agentStatus, [d.agent]: d.status } }));

    on("message_start", (d) => {
      this.msgIndex.set(d.id, this.state.feed.length);
      this.push({ type: "message", id: d.id, agent: d.agent, kind: d.kind, text: "", streaming: true });
    });
    on("message_delta", (d) => {
      const i = this.msgIndex.get(d.id);
      if (i === undefined) return;
      const feed = this.state.feed.slice();
      const m = feed[i];
      if (m.type !== "message") return;
      feed[i] = { ...m, text: m.text + d.text };
      this.commit({ feed });
    });
    on("message_end", (d) => {
      const i = this.msgIndex.get(d.id);
      if (i === undefined) return;
      const feed = this.state.feed.slice();
      const m = feed[i];
      if (m.type !== "message") return;
      feed[i] = { ...m, streaming: false };
      this.commit({ feed });
    });

    on("tool_call", (d) => {
      this.msgIndex.set(`tool:${d.id}`, this.state.feed.length);
      this.push({ type: "tool", id: d.id, agent: d.agent, tool: d.tool, args: d.args });
    });
    on("tool_result", (d) => {
      const i = this.msgIndex.get(`tool:${d.id}`);
      if (i === undefined) return;
      const feed = this.state.feed.slice();
      const t = feed[i];
      if (t.type !== "tool") return;
      feed[i] = { ...t, result: d.summary };
      this.commit({ feed });
    });

    on("market_snapshot", (d) => this.commit({ snapshot: d }));
    on("citation_added", (d) => this.commit({ citations: [...this.state.citations, d] }));
    on("claim_filed", (d) => this.push({ type: "claim", claim: d }));
    on("key_numbers", (d) =>
      this.commit({ agentNumbers: { ...this.state.agentNumbers, [d.agent]: d.numbers } }));
    on("view_ready", (d) =>
      this.commit({
        agentStance: { ...this.state.agentStance, [d.agent]: d.stance },
        agentSummary: { ...this.state.agentSummary, [d.agent]: d.summary },
      }));

    on("objection_filed", (d) => this.push({ type: "objection", objection: d }));
    on("rebuttal_filed", (d) => this.push({ type: "rebuttal", rebuttal: d }));
    on("verdict_rendered", (d) => this.push({ type: "verdict", verdict: d }));

    on("valuation_update", (d) =>
      this.commit({
        footballField: d.football_field ?? this.state.footballField,
        sensitivity: d.sensitivity ?? this.state.sensitivity,
        sensitivityAxes: d.sensitivity_axes ?? this.state.sensitivityAxes,
        monteCarlo: d.monte_carlo ?? this.state.monteCarlo,
      }));
    on("geo_exposure", (d) => this.commit({ geo: d }));
    on("conviction_update", (d) => this.commit({ conviction: d }));
    on("thesis_ready", (d) => this.commit({ thesis: d }));
    on("rating_ready", (d) => this.commit({ rating: d }));
    on("audit_check", (d) => this.commit({ audit: [...this.state.audit, d] }));

    on("note_published", () => this.commit({ published: true }));
    on("run_failed", (d) => this.commit({ failed: d.error, done: true }));
    on("run_complete", () => { this.commit({ done: true }); es.close(); });

    es.onerror = () => {
      if (this.state.done) es.close();
    };
  }

  dispose() {
    this.es?.close();
    this.listeners.clear();
  }
}
