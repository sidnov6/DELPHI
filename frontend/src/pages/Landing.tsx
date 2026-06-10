import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { geoNaturalEarth1, geoPath, geoGraticule10 } from "d3-geo";
import { feature } from "topojson-client";
import type { Topology, GeometryCollection } from "topojson-specification";
import worldData from "world-atlas/countries-110m.json";
import { api } from "../lib/api";

interface TickerInfo {
  ticker: string;
  company: string;
  sector: string;
  exchange?: string;
  country?: string;
  source?: string;
}

const world = worldData as unknown as Topology<{ countries: GeometryCollection }>;
const countries = feature(world, world.objects.countries);
const fallbackUniverse: TickerInfo[] = [
  { ticker: "NVDA", company: "NVIDIA Corporation", sector: "Semiconductors", exchange: "NASDAQ" },
  { ticker: "MSFT", company: "Microsoft Corporation", sector: "Software", exchange: "NASDAQ" },
  { ticker: "AAPL", company: "Apple Inc.", sector: "Hardware", exchange: "NASDAQ" },
  { ticker: "AMZN", company: "Amazon.com, Inc.", sector: "Consumer / Cloud", exchange: "NASDAQ" },
  { ticker: "GOOGL", company: "Alphabet Inc.", sector: "Internet", exchange: "NASDAQ" },
  { ticker: "TSLA", company: "Tesla, Inc.", sector: "Automobiles", exchange: "NASDAQ" },
];

function BackdropMap() {
  const { d, sphere, grat } = useMemo(() => {
    const proj = geoNaturalEarth1().rotate([-10, 0]).fitSize([1400, 700], { type: "Sphere" });
    const p = geoPath(proj);
    return {
      d: countries.features.map((f) => p(f) ?? "").join(" "),
      sphere: p({ type: "Sphere" }) ?? "",
      grat: p(geoGraticule10()) ?? "",
    };
  }, []);
  return (
    <svg className="landing-bg" viewBox="0 0 1400 700" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <path d={sphere} fill="none" stroke="var(--line-soft)" strokeWidth="1" />
      <path d={grat} fill="none" stroke="var(--line-soft)" strokeWidth="0.35" opacity="0.45" />
      <path d={d} fill="oklch(0.19 0.009 70 / 0.6)" stroke="var(--line-soft)" strokeWidth="0.45" />
    </svg>
  );
}

export default function Landing() {
  const nav = useNavigate();
  const [universe, setUniverse] = useState<TickerInfo[]>([]);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const [liveProvider, setLiveProvider] = useState<string | null>(null);
  const [apiOffline, setApiOffline] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(api("/api/tickers")).then((r) => r.json()).then(setUniverse).catch(() => setApiOffline(true));
    fetch(api("/api/health")).then((r) => r.json())
      .then((h) => setLiveProvider(h.live_mode_available ? (h.live_provider ?? "live") : null))
      .catch(() => setApiOffline(true));
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement !== inputRef.current) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const [results, setResults] = useState<TickerInfo[] | null>(null);
  const [searching, setSearching] = useState(false);

  // Universal search: every SEC registrant + European exchanges, debounced.
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setResults(null); setSearching(false); return; }
    setSearching(true);
    const ctl = new AbortController();
    const t = setTimeout(() => {
      fetch(api(`/api/search?q=${encodeURIComponent(q)}`), { signal: ctl.signal })
        .then((r) => r.json())
        .then((d) => { setResults(d); setSearching(false); })
        .catch(() => { if (!ctl.signal.aborted) setSearching(false); });
    }, 220);
    return () => { ctl.abort(); clearTimeout(t); };
  }, [query]);

  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    const base = universe.length ? universe : fallbackUniverse;
    if (!q) return base;
    if (results) return results;
    return base.filter((t) =>
      t.ticker.includes(q) || t.company.toUpperCase().includes(q));
  }, [query, universe, results]);

  useEffect(() => setActive(0), [query]);

  const launch = async (ticker: string) => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fetch(api("/api/runs"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker }),
      });
      if (!r.ok) throw new Error((await r.json()).detail ?? "failed");
      const { run_id, ticker: tk } = await r.json();
      nav(`/run/${run_id}?t=${tk}`);
    } catch {
      setApiOffline(true);
      setBusy(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, matches.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter" && matches[active]) launch(matches[active].ticker);
  };

  return (
    <div className="landing">
      <BackdropMap />
      <header className="landing-top">
        <span className="wordmark">DELPHI</span>
        <span className="meta">MULTI-AGENT EQUITY RESEARCH</span>
      </header>

      <main className="landing-center">
        <h1 className="landing-title">DELPH<span className="om">I</span></h1>
        <p className="landing-sub">
          Seven agents argue over every name — four specialists, an adversary with objection
          rights, an auditor with a veto. Only what survives gets published.
        </p>

        <div className="omnibox">
          <div className="omnibox-input">
            <span style={{ color: "var(--saffron)" }}>›</span>
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Search any US or European listed company"
              spellCheck={false}
              autoFocus
              disabled={busy}
            />
            <span className="slash">/</span>
          </div>
          <div className="omnibox-list">
            {matches.length === 0 && (
              <div className="omnibox-empty">
                {searching
                  ? "Searching US registrants and European exchanges…"
                  : `No US or European listing matches “${query}”.`}
              </div>
            )}
            {matches.map((t, i) => (
              <button key={`${t.ticker}-${i}`} className="omnibox-item" data-active={i === active}
                onMouseEnter={() => setActive(i)} onClick={() => launch(t.ticker)}>
                <span className="tk">{t.ticker}</span>
                <span className="co">{t.company}</span>
                <span className="sec">
                  {[t.exchange, t.sector].filter(Boolean).join(" · ") || t.country || "—"}
                </span>
              </button>
            ))}
            {searching && matches.length > 0 && (
              <div className="omnibox-empty" style={{ padding: "8px 18px", fontSize: 11 }}>searching…</div>
            )}
            {apiOffline && (
              <div className="omnibox-empty" style={{ padding: "8px 18px", fontSize: 11 }}>
                Frontend deployed. Connect the FastAPI backend for live search and debates.
              </div>
            )}
          </div>
        </div>
      </main>

      <footer className="landing-foot">
        <span>EDGAR · XBRL · yfinance · FRED · StockTwits — all free sources, cached</span>
        <span className="modes">
          <span style={{ color: liveProvider ? "var(--bull)" : undefined }}>
            ● LIVE {liveProvider ? `ARMED · ${liveProvider.toUpperCase()}` : "OFF"}
          </span>
          <span style={{ color: "var(--saffron)" }}>● SIMULATION READY</span>
        </span>
      </footer>
    </div>
  );
}
