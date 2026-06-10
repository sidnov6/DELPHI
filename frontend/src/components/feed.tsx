/** The debate theater — streaming messages, visible tool calls,
 *  objection → rebuttal → verdict threads. */
import { memo, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import type {
  FeedItem, FeedMessage, FeedObjection, FeedPhase, FeedRebuttal,
  FeedToolCall, FeedVerdict, FeedClaim,
} from "../lib/types";
import { AGENT_META } from "../lib/types";

const PHASE_LABEL: Record<string, string> = {
  PLAN: "PLAN",
  PARALLEL_RESEARCH: "PARALLEL RESEARCH",
  ADVERSARY_ROUND_1: "ADVERSARY · ROUND 1",
  REBUTTAL: "REBUTTAL",
  ADVERSARY_ROUND_2: "ADVERSARY · ROUND 2",
  SYNTHESIS: "SYNTHESIS",
  AUDIT: "AUDIT",
  PUBLISH: "PUBLISH",
  REVISE: "REVISE",
};

const Message = memo(function Message({ m }: { m: FeedMessage }) {
  const meta = AGENT_META[m.agent];
  return (
    <div className="msg" data-kind={m.kind} style={{ "--agent-hue": meta.hue } as React.CSSProperties}>
      <div className="avatar">{meta.short}</div>
      <div className="body">
        <div className="who">
          <span className="nm">{meta.label}</span>
          <span className="kind">{m.kind}</span>
        </div>
        <p className="text">
          {m.text}
          {m.streaming && <span className="caret" />}
        </p>
      </div>
    </div>
  );
}, (a, b) => a.m.text === b.m.text && a.m.streaming === b.m.streaming);

const ToolLine = memo(function ToolLine({ t }: { t: FeedToolCall }) {
  const meta = AGENT_META[t.agent];
  return (
    <div className="tool-line" style={{ "--agent-hue": meta.hue } as React.CSSProperties}>
      <span className="fn">{t.tool}</span>
      <span>({t.args})</span>
      {t.result && <span className="res">{t.result}</span>}
    </div>
  );
}, (a, b) => a.t.result === b.t.result);

const ClaimLine = memo(function ClaimLine({ c }: { c: FeedClaim }) {
  const meta = AGENT_META[c.claim.agent];
  const has = c.claim.citation_ids.length > 0;
  return (
    <div className="claim-line" style={{ "--agent-hue": meta.hue } as React.CSSProperties}>
      <span className="cid">{c.claim.id}</span>
      <span>{c.claim.text}</span>
      <span className={`cites${has ? "" : " missing"}`}>
        {has ? c.claim.citation_ids.join(" ") : "uncited"}
      </span>
    </div>
  );
});

const ObjectionCard = memo(function ObjectionCard({ o }: { o: FeedObjection }) {
  const target = AGENT_META[o.objection.target_agent];
  return (
    <div className="objection-card">
      <div className="head">
        <span className="oid">OBJECTION {o.objection.id}</span>
        <span className="target">vs {target.label}</span>
        <span className="weight">−{o.objection.weight.toFixed(1)} pts at stake</span>
      </div>
      <p className="text">{o.objection.text}</p>
    </div>
  );
});

const RebuttalCard = memo(function RebuttalCard({ r }: { r: FeedRebuttal }) {
  const meta = AGENT_META[r.rebuttal.agent];
  return (
    <div className="rebuttal-card" style={{ "--agent-hue": meta.hue } as React.CSSProperties}>
      <div className="head">
        <span className="nm">{meta.label}</span>
        <span className="lbl">REBUTS {r.rebuttal.objection_id}</span>
      </div>
      <p className="text">{r.rebuttal.text}</p>
    </div>
  );
});

const VerdictLine = memo(function VerdictLine({ v }: { v: FeedVerdict }) {
  return (
    <div className="verdict-line">
      <span className="verdict-badge" data-status={v.verdict.status}>{v.verdict.status}</span>
      <span>{v.verdict.rationale}</span>
      {v.verdict.penalty_applied > 0 && (
        <span className="num" style={{ color: "var(--bear)", fontSize: 11, flexShrink: 0 }}>
          −{v.verdict.penalty_applied.toFixed(1)}
        </span>
      )}
    </div>
  );
});

const PhaseDivider = memo(function PhaseDivider({ p }: { p: FeedPhase }) {
  return (
    <div className="feed-phase">
      <span className="ph">{PHASE_LABEL[p.phase] ?? p.phase}</span>
      <span className="rule" />
      {p.detail && <span className="dt">{p.detail}</span>}
    </div>
  );
});

function renderItem(item: FeedItem, i: number) {
  switch (item.type) {
    case "phase": return <PhaseDivider key={`p${i}`} p={item} />;
    case "message": return <Message key={item.id} m={item} />;
    case "tool": return <ToolLine key={`t${item.id}`} t={item} />;
    case "claim": return <ClaimLine key={item.claim.id} c={item} />;
    case "objection": return <ObjectionCard key={item.objection.id} o={item} />;
    case "rebuttal": return <RebuttalCard key={item.rebuttal.id} r={item} />;
    case "verdict": return <VerdictLine key={`v${i}`} v={item} />;
  }
}

export function DebateFeed({ feed, published, runId, failed }:
  { feed: FeedItem[]; published: boolean; runId: string; failed: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [feed]);

  return (
    <div className="feed" ref={ref}>
      <div className="feed-inner">
        {feed.map(renderItem)}
        {failed && <div className="fail-banner">Run failed — {failed}</div>}
        {published && (
          <Link className="note-cta" to={`/run/${runId}/note`}>
            <div>
              <div className="t">The research note is published</div>
              <div className="s">Rating, football field, debate log — every claim cited to source</div>
            </div>
            <span className="arrow">→</span>
          </Link>
        )}
      </div>
    </div>
  );
}
