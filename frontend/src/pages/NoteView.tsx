/** The published research note — the editorial register. */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { ResearchNote, Verdict } from "../lib/types";
import { AGENT_META } from "../lib/types";
import { api } from "../lib/api";
import { ccy, fmtPct, fmtPrice } from "../lib/format";
import { FootballField, MonteCarloChart, SensitivityHeatmap } from "../components/charts";
import { GlobalMap } from "../components/GlobalMap";

export default function NoteView() {
  const { runId = "" } = useParams();
  const [note, setNote] = useState<ResearchNote | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [pending, setPending] = useState(false);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;
    const load = () => {
      fetch(api(`/api/runs/${runId}/report`))
        .then(async (r) => {
          if (r.status === 409) {
            // Note not published yet — the run is still in session. Poll;
            // never re-trigger or error a run that's simply mid-debate.
            if (!cancelled) { setPending(true); timer = setTimeout(load, 3000); }
            return null;
          }
          if (!r.ok) throw new Error((await r.json()).detail);
          return r.json();
        })
        .then((d) => { if (d && !cancelled) { setPending(false); setNote(d); } })
        .catch((e) => { if (!cancelled) setErr(String(e.message ?? e)); });
    };
    load();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [runId]);

  if (err) return <div className="note-page"><div className="fail-banner">{err} — <Link to="/">back to the desk</Link></div></div>;
  if (pending && !note) {
    return (
      <div className="note-page">
        <div className="note-mast">
          <Link to="/" className="wordmark">DELPHI</Link>
          <span className="meta">INSTITUTIONAL EQUITY RESEARCH</span>
        </div>
        <p style={{ marginTop: 40, color: "var(--ink-2)", fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 17 }}>
          The desk is still in session — this page will update the moment the note clears audit.
        </p>
        <p style={{ marginTop: 14 }}>
          <Link className="btn-ghost" to={`/run/${runId}`}>WATCH THE DEBATE →</Link>
        </p>
      </div>
    );
  }
  if (!note) return <div className="note-page"><p className="empty" style={{ color: "var(--ink-3)", fontFamily: "var(--serif)", fontStyle: "italic" }}>Setting the note…</p></div>;

  const verdictFor = new Map<string, Verdict>(note.verdicts.map((v) => [v.objection_id, v]));
  const date = new Date(note.generated_at);
  const sym = ccy(note.snapshot.currency);
  let sectionIdx = 0;
  const idx = () => String(++sectionIdx).padStart(2, "0");

  return (
    <div className="note-page">
      <div className="note-mast">
        <Link to="/" className="wordmark">DELPHI</Link>
        <span className="meta">
          INSTITUTIONAL EQUITY RESEARCH · {date.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }).toUpperCase()}
          {" · "}{note.mode.toUpperCase()}
        </span>
      </div>

      <div className="note-rating-row">
        <span className="rating-pill" data-action={note.rating.action}>{note.rating.action}</span>
        <span className="num" style={{ fontSize: 13, color: "var(--ink-2)" }}>
          {note.ticker} · {note.company}
        </span>
        <div className="pxes">
          <div className="kv"><div className="k">PRICE</div><div className="v">{fmtPrice(note.rating.last_price, sym)}</div></div>
          <div className="kv"><div className="k">TARGET</div><div className="v" style={{ color: "var(--saffron)" }}>{fmtPrice(note.rating.price_target, sym)}</div></div>
          <div className="kv"><div className="k">UPSIDE</div>
            <div className={`v ${note.rating.upside_pct >= 0 ? "pos" : "neg"}`}>{fmtPct(note.rating.upside_pct)}</div></div>
          <div className="kv"><div className="k">BULL / BEAR</div>
            <div className="v">{Math.round(note.rating.bull_target)} / {Math.round(note.rating.bear_target)}</div></div>
          <div className="kv"><div className="k">CONVICTION</div><div className="v">{Math.round(note.conviction.final)}<span style={{ color: "var(--ink-3)" }}>/100</span></div></div>
        </div>
      </div>

      <h1 className="note-headline">{note.thesis.headline}</h1>

      <div className="note-variant">
        <span className="vp-label">VARIANT PERCEPTION</span>
        {note.thesis.variant_perception}
      </div>

      <section className="note-section">
        <h2><span className="idx">{idx()}</span>Thesis pillars</h2>
        <div className="pillars">
          {note.thesis.pillars.map((p, i) => (
            <div className="pillar" key={i}>
              <h3>{p.title}</h3>
              <p>{p.text}</p>
              <div className="cites">{p.citation_ids.join(" · ")}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="note-section">
        <h2><span className="idx">{idx()}</span>Where the value sits</h2>
        <FootballField bars={note.football_field} lastPrice={note.rating.last_price} target={note.rating.price_target} sym={sym} />
      </section>

      <section className="note-section">
        <h2><span className="idx">{idx()}</span>Global exposure</h2>
        <GlobalMap geo={note.geo} detailed />
        {note.geo.commentary && (
          <p style={{ marginTop: 12, color: "var(--ink-3)", fontSize: 13, fontStyle: "italic", fontFamily: "var(--serif)" }}>
            {note.geo.commentary}
          </p>
        )}
      </section>

      <section className="note-section">
        <h2><span className="idx">{idx()}</span>The debate, on the record</h2>
        <div className="debate-log">
          {note.objections.map((o) => {
            const reb = note.rebuttals.find((r) => r.objection_id === o.id);
            const vd = verdictFor.get(o.id);
            return (
              <div className="debate-entry" key={o.id}>
                <div className="obj">
                  <span className="lbl">OBJECTION {o.id} · vs {AGENT_META[o.target_agent].label.toUpperCase()} · −{o.weight.toFixed(1)} PTS AT STAKE</span>
                  <p>{o.text}</p>
                </div>
                {reb && (
                  <div className="reb">
                    <span className="lbl">{AGENT_META[reb.agent].label.toUpperCase()} REBUTS</span>
                    <p>{reb.text}</p>
                  </div>
                )}
                {vd && (
                  <div className="vd">
                    <span className="verdict-badge" data-status={vd.status}>{vd.status}</span>
                    <span>{vd.rationale}</span>
                    {vd.penalty_applied > 0 && (
                      <span className="num" style={{ marginLeft: "auto", color: "var(--bear)" }}>
                        −{vd.penalty_applied.toFixed(1)} conviction
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <section className="note-section">
        <h2><span className="idx">{idx()}</span>Scenario surface</h2>
        <SensitivityHeatmap cells={note.sensitivity} axes={note.sensitivity_axes} lastPrice={note.rating.last_price} />
        <div style={{ height: 26 }} />
        <MonteCarloChart mc={note.monte_carlo} lastPrice={note.rating.last_price} sym={sym} />
      </section>

      <section className="note-section">
        <h2><span className="idx">{idx()}</span>Financial summary</h2>
        <div className="fin-summary">
          {note.financial_summary.map((n, i) => (
            <div className="cell" key={i}>
              <div className="l">{n.label}</div>
              <div className="v">{n.value}</div>
              {n.delta && <div className={`d ${n.tone}`}>{n.delta}</div>}
            </div>
          ))}
        </div>
      </section>

      <section className="note-section">
        <h2><span className="idx">{idx()}</span>Risk register</h2>
        <table className="risk-table">
          <thead>
            <tr><th>RISK</th><th>SEVERITY</th><th>DETAIL & MITIGANT</th></tr>
          </thead>
          <tbody>
            {note.risks.map((r, i) => (
              <tr key={i}>
                <td className="t">{r.title}</td>
                <td><span className="sev" data-s={r.severity}>{r.severity.toUpperCase()}</span></td>
                <td>
                  {r.text}
                  {r.mitigant && <span style={{ display: "block", marginTop: 6, color: "var(--ink-3)", fontSize: 12 }}>Mitigant — {r.mitigant}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="note-section">
        <h2><span className="idx">{idx()}</span>Audit trail</h2>
        <div className="audit-list">
          {note.audit.map((c, i) => (
            <div key={i} className="audit-row" data-pass={c.passed}>
              <span className="tick">{c.passed ? "✓" : "✗"}</span>
              <span><span className="nm">{c.name}</span><span className="dt">{c.detail}</span></span>
            </div>
          ))}
        </div>
      </section>

      <section className="note-section">
        <h2><span className="idx">{idx()}</span>Sources</h2>
        <div className="citation-list">
          {note.citations.map((c) => (
            <div className="citation-item" key={c.id}>
              <span className="cid">{c.id}</span>
              <span>
                {c.url ? <a href={c.url} target="_blank" rel="noreferrer">{c.source}</a> : c.source}
                {c.snippet && <span style={{ display: "block", color: "var(--ink-faint)", fontSize: 11, marginTop: 2 }}>“{c.snippet}”</span>}
              </span>
            </div>
          ))}
        </div>
      </section>

      <p className="note-disclaimer">
        Generated by DELPHI, a multi-agent research system, in {note.mode} mode on {date.toUTCString()}.
        Figures derive from public filings, free market-data sources and a deterministic valuation engine;
        the debate transcript above is the full provenance of every judgment. This document is a
        demonstration of agentic research workflow and is not investment advice.
      </p>
    </div>
  );
}
