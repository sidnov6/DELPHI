/** Custom SVG charts. No chart library — every pixel on the design system. */
import { useMemo } from "react";
import type { ConvictionBreakdown, FootballFieldBar, MonteCarloSummary, ScenarioCell } from "../lib/types";
import { fmtPrice } from "../lib/format";

/* ── price sparkline ─────────────────────────────────────────── */

export function Sparkline({ data, width = 332, height = 56 }:
  { data: number[]; width?: number; height?: number }) {
  const path = useMemo(() => {
    if (data.length < 2) return { line: "", area: "", up: true, lastY: 0 };
    const min = Math.min(...data), max = Math.max(...data);
    const span = max - min || 1;
    const x = (i: number) => (i / (data.length - 1)) * width;
    const y = (v: number) => height - 4 - ((v - min) / span) * (height - 10);
    const pts = data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    return {
      line: `M${pts.join("L")}`,
      area: `M${pts.join("L")}L${width},${height}L0,${height}Z`,
      up: data[data.length - 1] >= data[0],
      lastY: y(data[data.length - 1]),
    };
  }, [data, width, height]);

  if (!path.line) return null;
  const tone = path.up ? "var(--bull)" : "var(--bear)";
  return (
    <svg className="chart-svg" width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: "block" }}>
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={tone} stopOpacity="0.22" />
          <stop offset="100%" stopColor={tone} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={path.area} fill="url(#spark-fill)" />
      <path d={path.line} fill="none" stroke={tone} strokeWidth="1.4" strokeLinejoin="round" />
      <circle cx={width} cy={path.lastY} r="2.4" fill={tone} />
    </svg>
  );
}

/* ── conviction gauge ────────────────────────────────────────── */

export function ConvictionGauge({ breakdown, size = 124 }:
  { breakdown: ConvictionBreakdown | null; size?: number }) {
  const value = breakdown?.final ?? 0;
  const r = size / 2 - 9;
  const c = 2 * Math.PI * r;
  const sweep = 0.78;                      // 280° arc
  const arcLen = c * sweep;
  const filled = arcLen * (value / 100);
  const rot = 90 + (360 * (1 - sweep)) / 2;
  const tone = value >= 65 ? "var(--bull)" : value >= 40 ? "var(--saffron)" : "var(--bear)";
  const band = breakdown == null ? "CONVICTION"
    : value >= 70 ? "HIGH CONVICTION" : value >= 40 ? "MODERATE" : value >= 20 ? "LOW" : "SPECULATIVE";
  return (
    <svg className="chart-svg" width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <g transform={`rotate(${rot} ${size / 2} ${size / 2})`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--overlay)"
          strokeWidth="7" strokeDasharray={`${arcLen} ${c}`} strokeLinecap="round" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={tone}
          strokeWidth="7" strokeDasharray={`${filled} ${c}`} strokeLinecap="round"
          style={{ transition: "stroke-dasharray 600ms var(--ease-in-out), stroke 300ms ease" }} />
      </g>
      <text x="50%" y="47%" textAnchor="middle" dominantBaseline="central"
        style={{ fontSize: size * 0.26, fill: "var(--ink)", fontFamily: "var(--mono)", letterSpacing: "-0.02em" }}>
        {breakdown ? Math.round(value) : "–"}
      </text>
      <text x="50%" y="66%" textAnchor="middle"
        style={{ fontSize: 8.5, fill: "var(--ink-3)", letterSpacing: "0.18em" }}>
        {band}
      </text>
    </svg>
  );
}

/* ── football field ──────────────────────────────────────────── */

export function FootballField({ bars, lastPrice, target, width = 700, sym = "$" }:
  { bars: FootballFieldBar[]; lastPrice: number; target?: number | null; width?: number; sym?: string }) {
  const rowH = 34, padT = 8, padB = 26, labelW = 168, padR = 16;
  const height = bars.length * rowH + padT + padB;
  const lo = Math.min(...bars.map((b) => b.low), lastPrice) * 0.94;
  const hi = Math.max(...bars.map((b) => b.high), lastPrice, target ?? 0) * 1.05;
  const x = (v: number) => labelW + ((v - lo) / (hi - lo)) * (width - labelW - padR);

  const ticks = useMemo(() => {
    const n = 5, out: number[] = [];
    for (let i = 0; i <= n; i++) out.push(lo + ((hi - lo) * i) / n);
    return out;
  }, [lo, hi]);

  return (
    <svg className="chart-svg" width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: "block" }}>
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={x(t)} y1={padT} x2={x(t)} y2={height - padB} stroke="var(--line-soft)" strokeWidth="1" />
          <text x={x(t)} y={height - 10} textAnchor="middle" style={{ fontSize: 9 }}>{sym}{Math.round(t)}</text>
        </g>
      ))}
      {bars.map((b, i) => {
        const cy = padT + i * rowH + rowH / 2;
        return (
          <g key={b.method}>
            <text className="ff-row-label" x={0} y={cy + 3} style={{ fill: "var(--ink-2)" }}>{b.method}</text>
            <line x1={x(b.low)} y1={cy} x2={x(b.high)} y2={cy}
              stroke="color-mix(in oklch, var(--saffron) 40%, var(--overlay))" strokeWidth="8" strokeLinecap="round" />
            <line x1={x(b.mid)} y1={cy - 7} x2={x(b.mid)} y2={cy + 7} stroke="var(--saffron)" strokeWidth="2.4" />
            <text className="ff-val" x={x(b.high) + 6} y={cy + 3} style={{ fill: "var(--ink-3)" }}>
              {Math.round(b.low)}–{Math.round(b.high)}
            </text>
          </g>
        );
      })}
      {/* market price line */}
      <line x1={x(lastPrice)} y1={padT} x2={x(lastPrice)} y2={height - padB}
        stroke="var(--ink)" strokeWidth="1.3" strokeDasharray="4 4" />
      <text x={x(lastPrice)} y={padT + 1} textAnchor="middle"
        style={{ fontSize: 9, fill: "var(--ink)" }} dy="-1">PX {fmtPrice(lastPrice, sym)}</text>
      {target != null && (
        <>
          <line x1={x(target)} y1={padT} x2={x(target)} y2={height - padB}
            stroke="var(--saffron)" strokeWidth="1.3" />
          <text x={x(target)} y={height - padB + 11} textAnchor="middle"
            style={{ fontSize: 9, fill: "var(--saffron)" }}>PT {fmtPrice(target, sym)}</text>
        </>
      )}
    </svg>
  );
}

/* ── sensitivity heatmap ─────────────────────────────────────── */

export function SensitivityHeatmap({ cells, axes, lastPrice, width = 700 }:
  { cells: ScenarioCell[]; axes: { rows: number[]; cols: number[] }; lastPrice: number; width?: number }) {
  const { rows, cols } = axes;
  const labelW = 64, padT = 24, padB = 8, padR = 8;
  const cw = (width - labelW - padR) / cols.length;
  const ch = 30;
  const height = padT + rows.length * ch + padB;

  const byKey = new Map(cells.map((c) => [`${c.row}:${c.col}`, c.value]));

  const color = (v: number) => {
    const rel = v / lastPrice - 1;                     // vs market
    const t = Math.max(-0.5, Math.min(0.5, rel)) / 0.5;
    return t >= 0
      ? `color-mix(in oklch, var(--bull) ${12 + t * 55}%, var(--surface))`
      : `color-mix(in oklch, var(--bear) ${12 + -t * 55}%, var(--surface))`;
  };

  return (
    <svg className="chart-svg" width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: "block" }}>
      <text x={0} y={12} style={{ fontSize: 9, letterSpacing: "0.1em" }}>WACC ↓</text>
      <text x={width - padR} y={12} textAnchor="end" style={{ fontSize: 9, letterSpacing: "0.1em" }}>
        TERMINAL GROWTH →
      </text>
      {cols.map((cv, j) => (
        <text key={j} x={labelW + j * cw + cw / 2} y={padT - 4} textAnchor="middle" style={{ fontSize: 9 }}>
          {(cv * 100).toFixed(1)}%
        </text>
      ))}
      {rows.map((rv, i) => (
        <g key={i}>
          <text x={labelW - 8} y={padT + i * ch + ch / 2 + 3} textAnchor="end" style={{ fontSize: 9 }}>
            {(rv * 100).toFixed(1)}%
          </text>
          {cols.map((cv, j) => {
            const v = byKey.get(`${rv}:${cv}`);
            const cxp = labelW + j * cw, cyp = padT + i * ch;
            if (v == null || v <= 0) {
              return <rect key={j} className="heat-cell" x={cxp + 1} y={cyp + 1} width={cw - 2} height={ch - 2}
                rx="4" fill="var(--bg-deep)" />;
            }
            const isBase = i === Math.floor(rows.length / 2) && j === Math.floor(cols.length / 2);
            return (
              <g key={j}>
                <rect className="heat-cell" x={cxp + 1} y={cyp + 1} width={cw - 2} height={ch - 2}
                  rx="4" fill={color(v)}
                  stroke={isBase ? "var(--saffron)" : "none"} strokeWidth={isBase ? 1.4 : 0} />
                <text x={cxp + cw / 2} y={cyp + ch / 2 + 3.5} textAnchor="middle"
                  style={{ fontSize: 10, fill: "var(--ink)" }}>
                  {Math.round(v)}
                </text>
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}

/* ── monte carlo histogram ───────────────────────────────────── */

export function MonteCarloChart({ mc, lastPrice, width = 700, height = 180, sym = "$" }:
  { mc: MonteCarloSummary; lastPrice: number; width?: number; height?: number; sym?: string }) {
  const padL = 8, padR = 8, padB = 24, padT = 14;
  const { histogram, bin_edges } = mc;
  if (!histogram.length || bin_edges.length < 2) return null;
  const maxN = Math.max(...histogram);
  const lo = bin_edges[0], hi = bin_edges[bin_edges.length - 1];
  const x = (v: number) => padL + ((v - lo) / (hi - lo)) * (width - padL - padR);
  const y = (n: number) => padT + (1 - n / maxN) * (height - padT - padB);

  return (
    <svg className="chart-svg" width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: "block" }}>
      {histogram.map((n, i) => {
        const x0 = x(bin_edges[i]), x1 = x(bin_edges[i + 1]);
        const mid = (bin_edges[i] + bin_edges[i + 1]) / 2;
        const above = mid >= lastPrice;
        return (
          <rect key={i} x={x0 + 1} y={y(n)} width={Math.max(1, x1 - x0 - 2)} height={height - padB - y(n)}
            rx="2" fill={above ? "var(--bull)" : "var(--bear)"} opacity={0.28 + 0.5 * (n / maxN)} />
        );
      })}
      <line x1={x(lastPrice)} y1={padT - 6} x2={x(lastPrice)} y2={height - padB}
        stroke="var(--ink)" strokeWidth="1.3" strokeDasharray="4 4" />
      <text x={x(lastPrice) + 5} y={padT} style={{ fontSize: 9, fill: "var(--ink)" }}>
        PX {fmtPrice(lastPrice, sym)}
      </text>
      <line x1={x(mc.p50)} y1={padT} x2={x(mc.p50)} y2={height - padB} stroke="var(--saffron)" strokeWidth="1.2" />
      <text x={x(mc.p50) + 5} y={padT + 11} style={{ fontSize: 9, fill: "var(--saffron)" }}>
        p50 {fmtPrice(mc.p50, sym)}
      </text>
      {[["p5", mc.p5], ["p95", mc.p95]].map(([lbl, v]) => (
        <text key={lbl as string} x={x(v as number)} y={height - 8} textAnchor="middle"
          style={{ fontSize: 9 }}>{lbl as string} {sym}{Math.round(v as number)}</text>
      ))}
      <text x={width - padR} y={padT} textAnchor="end" style={{ fontSize: 9.5, fill: "var(--ink-2)" }}>
        P(upside) {(mc.prob_upside * 100).toFixed(0)}% · n=2,000
      </text>
    </svg>
  );
}
