/** Left rail (pipeline + roster) and right dossier panels. */
import { memo } from "react";
import type { RunState } from "../lib/store";
import { AGENT_META, PHASE_SEQUENCE, type AgentId } from "../lib/types";
import { ccy, fmtB, fmtPct, fmtPrice, fmtStance, fmtX, stanceTone } from "../lib/format";
import { ConvictionGauge, FootballField, MonteCarloChart, SensitivityHeatmap, Sparkline } from "./charts";
import { GlobalMap } from "./GlobalMap";

const BUSY = new Set(["reading", "thinking", "speaking", "rebutting"]);
const STATUS_LABEL: Record<string, string> = {
  reading: "reading", thinking: "thinking", speaking: "writing",
  rebutting: "rebutting", done: "done", idle: "",
};

export const Rail = memo(function Rail({ s }: { s: RunState }) {
  const phaseIdx = PHASE_SEQUENCE.findIndex((p) => p.id === s.phase);
  const inRevise = s.phase === "REVISE";
  return (
    <aside className="rail">
      <section>
        <h3>Pipeline</h3>
        <div className="phase-list">
          {PHASE_SEQUENCE.map((p, i) => {
            const state = s.done && p.id === "PUBLISH" ? "done"
              : p.id === s.phase ? "active"
              : phaseIdx > i || s.done ? "done" : "pending";
            return (
              <div key={p.id} className="phase-item" data-state={state}>
                <span className="dot" />
                <span>
                  {p.label}
                  {p.id === s.phase && s.phaseDetail && <span className="ph-detail">{s.phaseDetail}</span>}
                </span>
              </div>
            );
          })}
          {inRevise && (
            <div className="phase-item" data-state="active" data-revise="true">
              <span className="dot" />
              <span>Revise<span className="ph-detail">audit failure loops back — once</span></span>
            </div>
          )}
        </div>
      </section>
      <section>
        <h3>The Desk</h3>
        <div className="roster">
          {(Object.keys(AGENT_META) as AgentId[]).map((a) => {
            const meta = AGENT_META[a];
            const status = s.agentStatus[a] ?? "idle";
            const stance = s.agentStance[a];
            return (
              <div key={a} className="agent-row" data-status={status}
                style={{ "--agent-hue": meta.hue } as React.CSSProperties}
                title={s.agentSummary[a] ?? meta.label}>
                <span className="agent-sigil">{meta.short}</span>
                <span className="nm">{meta.label}</span>
                {stance !== undefined ? (
                  <span className="stance-chip" data-tone={stanceTone(stance)}>{fmtStance(stance)}</span>
                ) : (
                  <span className="st">
                    {BUSY.has(status) && <span className="pulse" />}
                    {STATUS_LABEL[status]}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </section>
      {s.plan.length > 0 && (
        <section>
          <h3>Scope</h3>
          <div style={{ padding: "0 20px", display: "flex", flexDirection: "column", gap: 7 }}>
            {s.plan.map((item, i) => (
              <div key={i} style={{ fontSize: 11.5, color: "var(--ink-3)", lineHeight: 1.45, display: "grid", gridTemplateColumns: "16px 1fr", gap: 4 }}>
                <span className="num" style={{ color: "var(--ink-faint)" }}>{i + 1}</span>
                <span>{item}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </aside>
  );
});

export const Dossier = memo(function Dossier({ s }: { s: RunState }) {
  const snap = s.snapshot;
  const sym = ccy(snap?.currency);
  return (
    <aside className="dossier">
      <div className="panel">
        <h4>Tape</h4>
        {snap ? (
          <>
            <div className="snapshot-price">
              <span className="px">{fmtPrice(snap.last_price, sym)}</span>
              {snap.week52_low != null && snap.week52_high != null && (
                <span className="range num">52w {Math.round(snap.week52_low)}–{Math.round(snap.week52_high)}</span>
              )}
            </div>
            <Sparkline data={snap.price_history} />
            <div className="snapshot-stats">
              {snap.market_cap_b != null && <div className="kv"><div className="k">MKT CAP</div><div className="v">{fmtB(snap.market_cap_b, sym)}</div></div>}
              {snap.pe_fwd != null && <div className="kv"><div className="k">P/E FWD</div><div className="v">{fmtX(snap.pe_fwd)}</div></div>}
              {snap.ev_ebitda != null && <div className="kv"><div className="k">EV/EBITDA</div><div className="v">{fmtX(snap.ev_ebitda)}</div></div>}
            </div>
          </>
        ) : <div className="empty">Awaiting market snapshot…</div>}
      </div>

      <div className="panel">
        <h4>Conviction</h4>
        <div className="gauge-wrap">
          <ConvictionGauge breakdown={s.conviction} />
          <div className="gauge-break">
            <div className="row" data-tone="base">
              <span>Base agreement</span>
              <span className="v">{s.conviction ? s.conviction.base_agreement.toFixed(0) : "–"}</span>
            </div>
            <div className="row" data-tone="neg">
              <span>Objections</span>
              <span className="v">{s.conviction ? `−${s.conviction.objection_penalty.toFixed(1)}` : "–"}</span>
            </div>
            <div className="row" data-tone="neg">
              <span>Citation penalty</span>
              <span className="v">{s.conviction ? `−${s.conviction.citation_penalty.toFixed(1)}` : "–"}</span>
            </div>
            {s.rating && (
              <div className="rating-banner" style={{ marginTop: 4 }}>
                <span className="rating-pill" data-action={s.rating.action}>{s.rating.action}</span>
                <span className="tgt">{fmtPrice(s.rating.price_target, sym)}</span>
                <span className={`up ${s.rating.upside_pct >= 0 ? "pos" : "neg"}`}>{fmtPct(s.rating.upside_pct)}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="panel">
        <h4>Global exposure</h4>
        {s.geo ? <GlobalMap geo={s.geo} /> : <div className="empty">The Macro desk is mapping revenue geography…</div>}
      </div>

      <div className="panel">
        <h4>Valuation field</h4>
        {s.footballField.length > 0 && snap ? (
          <FootballField bars={s.footballField} lastPrice={snap.last_price}
            target={s.rating?.price_target} width={360} sym={sym} />
        ) : <div className="empty">Waiting on the engine’s triangulation…</div>}
      </div>

      <div className="panel">
        <h4>Desk reads</h4>
        {Object.keys(s.agentNumbers).length > 0 ? (
          <div className="keynum-grid">
            {(Object.entries(s.agentNumbers) as [AgentId, NonNullable<RunState["agentNumbers"][AgentId]>][]).map(([agent, nums]) => (
              <div key={agent} className="keynum-agent" style={{ "--agent-hue": AGENT_META[agent].hue } as React.CSSProperties}>
                <span className="agent-sigil">{AGENT_META[agent].short}</span>
                <div className="keynum-cells">
                  {nums.map((n, i) => (
                    <div className="kn" key={i}>
                      <div className="l">{n.label}</div>
                      <div className={`v ${n.tone}`}>{n.value}</div>
                      {n.delta && <div className={`d ${n.tone}`}>{n.delta}</div>}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : <div className="empty">Specialists are still reading…</div>}
      </div>

      {s.audit.length > 0 && (
        <div className="panel">
          <h4>Audit</h4>
          <div className="audit-list">
            {s.audit.map((c, i) => (
              <div key={i} className="audit-row" data-pass={c.passed}>
                <span className="tick">{c.passed ? "✓" : "✗"}</span>
                <span><span className="nm">{c.name}</span><span className="dt">{c.detail}</span></span>
              </div>
            ))}
          </div>
        </div>
      )}

      {s.monteCarlo && snap && (
        <div className="panel">
          <h4>Monte Carlo · 2,000 paths</h4>
          <MonteCarloChart mc={s.monteCarlo} lastPrice={snap.last_price} width={360} height={130} sym={sym} />
        </div>
      )}

      {s.sensitivity.length > 0 && s.sensitivityAxes && snap && (
        <div className="panel">
          <h4>WACC × terminal growth</h4>
          <SensitivityHeatmap cells={s.sensitivity} axes={s.sensitivityAxes}
            lastPrice={snap.last_price} width={360} />
        </div>
      )}
    </aside>
  );
});
