"""Macro series from FRED's keyless CSV endpoint.

One GET pulls DGS10 (10y treasury), CPIAUCSL (CPI level), and FEDFUNDS.
We derive rf_10y, cpi_yoy (12-month CPI change), and fed_funds. Returns
a partial macro dict (whatever parsed cleanly) or None.
"""

from __future__ import annotations

from .base import MacroProvider

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10,CPIAUCSL,FEDFUNDS"


class FredMacro(MacroProvider):
    name = "fred_macro"

    def fetch(self, ticker: str) -> dict | None:  # ticker unused; macro is global
        try:
            import httpx

            resp = httpx.get(FRED_CSV_URL, timeout=10.0, follow_redirects=True)
            resp.raise_for_status()
            # FRED now ships multi-series downloads as a ZIP archive.
            if resp.content[:2] == b"PK":
                import io
                import zipfile

                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                    if not csv_names:
                        return None
                    text = zf.read(csv_names[0]).decode("utf-8", errors="replace")
            else:
                text = resp.text
            return self._parse(text)
        except Exception:
            return None

    @staticmethod
    def _parse(csv_text: str) -> dict | None:
        try:
            lines = [ln.strip() for ln in csv_text.strip().splitlines() if ln.strip()]
            if len(lines) < 2:
                return None
            header = [h.strip().upper() for h in lines[0].split(",")]
            cols: dict[str, list[float | None]] = {name: [] for name in header[1:]}
            for line in lines[1:]:
                parts = line.split(",")
                for name, raw in zip(header[1:], parts[1:]):
                    raw = raw.strip()
                    try:
                        cols[name].append(float(raw))
                    except ValueError:
                        cols[name].append(None)  # FRED encodes missing as "."

            def latest(series: list[float | None]) -> float | None:
                for v in reversed(series):
                    if v is not None:
                        return v
                return None

            out: dict = {}

            dgs10 = latest(cols.get("DGS10", []))
            if dgs10 is not None:
                out["rf_10y"] = round(dgs10 / 100.0, 4)

            fedfunds = latest(cols.get("FEDFUNDS", []))
            if fedfunds is not None:
                out["fed_funds"] = round(fedfunds / 100.0, 4)

            cpi = [v for v in cols.get("CPIAUCSL", []) if v is not None]
            if len(cpi) >= 13 and cpi[-13]:
                out["cpi_yoy"] = round(cpi[-1] / cpi[-13] - 1.0, 4)

            return out or None
        except Exception:
            return None
