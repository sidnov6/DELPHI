/** The exposure map — where in the world this P&L is actually earned.
 *  Choropleth by disclosed revenue share; great-circle arcs for supply,
 *  demand and risk dependencies; pulsing HQ. Built on d3-geo + world-atlas. */
import { useMemo, useRef, useState } from "react";
import { geoNaturalEarth1, geoPath, geoGraticule10 } from "d3-geo";
import { feature } from "topojson-client";
import type { Topology, GeometryCollection } from "topojson-specification";
import worldData from "world-atlas/countries-110m.json";
import type { GeoExposure, MapArc, MapRegion } from "../lib/types";

const world = worldData as unknown as Topology<{ countries: GeometryCollection<{ name: string }> }>;
const countries = feature(world, world.objects.countries);

const ARC_COLOR: Record<MapArc["kind"], string> = {
  supply: "var(--a-valuation)",
  demand: "var(--bull)",
  risk: "var(--bear)",
  hq: "var(--saffron)",
};

const W = 720, H = 366;

export function GlobalMap({ geo, detailed = false }: { geo: GeoExposure; detailed?: boolean }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{ x: number; y: number; region: MapRegion } | null>(null);

  const { path, projection } = useMemo(() => {
    const projection = geoNaturalEarth1().rotate([-10, 0]).fitSize([W, H], { type: "Sphere" });
    return { path: geoPath(projection), projection };
  }, []);

  const regionByIso = useMemo(
    () => new Map(geo.regions.map((r) => [r.iso_n3.padStart(3, "0"), r])),
    [geo.regions],
  );
  const maxShare = useMemo(
    () => Math.max(0.08, ...geo.regions.map((r) => r.revenue_share)),
    [geo.regions],
  );

  const graticule = useMemo(() => path(geoGraticule10()), [path]);
  const sphere = useMemo(() => path({ type: "Sphere" }), [path]);

  const arcs = useMemo(() =>
    geo.arcs.map((a, i) => ({
      ...a,
      d: path({ type: "LineString", coordinates: [a.src, a.dst] }) ?? "",
      key: i,
      srcXY: projection(a.src),
      dstXY: projection(a.dst),
    })), [geo.arcs, path, projection]);

  const hqXY = geo.hq ? projection(geo.hq) : null;

  const onMove = (e: React.MouseEvent, region: MapRegion | undefined) => {
    if (!region || !wrapRef.current) { setTip(null); return; }
    const rect = wrapRef.current.getBoundingClientRect();
    setTip({ x: e.clientX - rect.left + 12, y: e.clientY - rect.top + 12, region });
  };

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <svg className="chart-svg" width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }}>
        <defs>
          <radialGradient id="ocean-glow" cx="50%" cy="42%" r="65%">
            <stop offset="0%" stopColor="oklch(0.22 0.02 70 / 0.55)" />
            <stop offset="100%" stopColor="transparent" />
          </radialGradient>
        </defs>

        {sphere && <path d={sphere} fill="url(#ocean-glow)" stroke="var(--line-soft)" strokeWidth="1" />}
        {graticule && <path d={graticule} fill="none" stroke="var(--line-soft)" strokeWidth="0.4" opacity="0.5" />}

        {countries.features.map((f, i) => {
          const region = regionByIso.get(String(f.id).padStart(3, "0"));
          const intensity = region ? 18 + (region.revenue_share / maxShare) * 64 : 0;
          return (
            <path
              key={`${f.id ?? "t"}-${i}`}
              d={path(f) ?? ""}
              fill={region
                ? `color-mix(in oklch, var(--saffron) ${intensity}%, var(--surface))`
                : "var(--raised)"}
              stroke={region ? "var(--saffron-line)" : "var(--line-soft)"}
              strokeWidth={region ? 0.7 : 0.4}
              style={{ transition: "fill 400ms var(--ease-out)", cursor: region ? "pointer" : "default" }}
              onMouseMove={(e) => onMove(e, region)}
              onMouseLeave={() => setTip(null)}
            />
          );
        })}

        {/* flow arcs */}
        <g fill="none">
          {arcs.map((a) => (
            <g key={a.key}>
              <path d={a.d} stroke={ARC_COLOR[a.kind]} strokeWidth="1.6" opacity="0.85"
                strokeLinecap="round" strokeDasharray="3 7"
                style={{ animation: "arc-flow 1.4s linear infinite" }} />
              <path d={a.d} stroke={ARC_COLOR[a.kind]} strokeWidth="4" opacity="0.10" strokeLinecap="round" />
              {a.srcXY && <circle cx={a.srcXY[0]} cy={a.srcXY[1]} r="2.2" fill={ARC_COLOR[a.kind]} opacity="0.9" />}
              {a.dstXY && <circle cx={a.dstXY[0]} cy={a.dstXY[1]} r="2.2" fill={ARC_COLOR[a.kind]} opacity="0.9" />}
            </g>
          ))}
        </g>

        {/* HQ pulse */}
        {hqXY && (
          <g>
            <circle cx={hqXY[0]} cy={hqXY[1]} r="3.2" fill="var(--saffron)" />
            <circle cx={hqXY[0]} cy={hqXY[1]} r="3.2" fill="none" stroke="var(--saffron)" strokeWidth="1.4">
              <animate attributeName="r" values="3.2;11" dur="2.2s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.8;0" dur="2.2s" repeatCount="indefinite" />
            </circle>
          </g>
        )}

        <style>{`@keyframes arc-flow { to { stroke-dashoffset: -10; } }`}</style>
      </svg>

      {tip && (
        <div className="map-tip" style={{ left: tip.x, top: tip.y }}>
          <div className="nm">
            <span>{tip.region.name}</span>
            <span className="sh">{(tip.region.revenue_share * 100).toFixed(0)}%</span>
          </div>
          {tip.region.revenue_usd_b != null && (
            <div className="num" style={{ fontSize: 11, color: "var(--ink-2)" }}>
              ${tip.region.revenue_usd_b.toFixed(1)}B revenue
            </div>
          )}
          {tip.region.note && <div className="note">{tip.region.note}</div>}
        </div>
      )}

      <div className="map-legend">
        <span><span className="sw" style={{ background: "var(--saffron)" }} />revenue share</span>
        <span><span className="sw" style={{ background: ARC_COLOR.supply }} />supply</span>
        <span><span className="sw" style={{ background: ARC_COLOR.demand }} />demand</span>
        <span><span className="sw" style={{ background: ARC_COLOR.risk }} />risk</span>
      </div>

      {detailed && geo.regions.length > 0 && (
        <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8 }}>
          {[...geo.regions].sort((a, b) => b.revenue_share - a.revenue_share).map((r) => (
            <div key={r.iso_n3} className="kv" style={{ padding: "8px 10px", background: "var(--surface)", borderRadius: 8, border: "1px solid var(--line-soft)" }}>
              <div className="k">{r.name}</div>
              <div className="v" style={{ color: "var(--ink)" }}>
                {(r.revenue_share * 100).toFixed(0)}%
                {r.revenue_usd_b != null && <span style={{ color: "var(--ink-3)", marginLeft: 6 }}>${r.revenue_usd_b.toFixed(0)}B</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
