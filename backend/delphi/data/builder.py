"""Dynamic research-bundle builder for any US- or European-listed company.

Produces the exact fixture schema (see fixtures/NVDA.json) from keyless
live sources: yfinance for market/financials/estimates/ownership, FRED
for macro, StockTwits for the social tape, EDGAR for US filings.

Currency policy: everything in the finished bundle is expressed in ONE
currency — the quote currency of the listing. GBp (pence) quotes are
normalized to GBP, and financial statements reported in a different
currency (e.g. Shell: USD statements, GBp quote) are converted at the
latest available FX rate. ``CoverageError`` (a ValueError) is raised with
a human-readable reason when a name genuinely can't be covered.
"""

from __future__ import annotations

import datetime as _dt
import math

from .cache import DataCache

BUNDLE_SOURCE = "built_bundle"
BUNDLE_TTL_HOURS = 12.0

MACRO_FALLBACK = {"rf_10y": 0.042, "cpi_yoy": 0.026, "fed_funds": 0.039}
ERP = 0.045


class CoverageError(ValueError):
    """Raised when a ticker cannot be covered dynamically (with the reason)."""


# ------------------------------------------------------------------ statics

# ISO 3166-1 numeric codes (zero-padded, matching world-atlas topojson ids).
COUNTRY_ISO_N3: dict[str, str] = {
    "United States": "840",
    "United Kingdom": "826",
    "Germany": "276",
    "France": "250",
    "Netherlands": "528",
    "Switzerland": "756",
    "Sweden": "752",
    "Denmark": "208",
    "Norway": "578",
    "Finland": "246",
    "Italy": "380",
    "Spain": "724",
    "Portugal": "620",
    "Belgium": "056",
    "Austria": "040",
    "Ireland": "372",
    "Poland": "616",
    "Greece": "300",
    "Czechia": "203",
    "Czech Republic": "203",
    "Hungary": "348",
    "Luxembourg": "442",
    "Iceland": "352",
    "Romania": "642",
    "Turkey": "792",
    "Cyprus": "196",
    "Malta": "470",
    "Slovakia": "703",
    "Slovenia": "705",
    "Croatia": "191",
    "Estonia": "233",
    "Latvia": "428",
    "Lithuania": "440",
    "Bulgaria": "100",
    "Monaco": "492",
    "Liechtenstein": "438",
    "China": "156",
    "Hong Kong": "344",
    "Japan": "392",
    "South Korea": "410",
    "Korea": "410",
    "Taiwan": "158",
    "India": "356",
    "Brazil": "076",
    "Canada": "124",
    "Australia": "036",
    "Singapore": "702",
}

# Country -> [lon, lat] HQ centroid for the map's HQ pulse.
COUNTRY_CENTROIDS: dict[str, list[float]] = {
    "United States": [-98.5, 39.8],
    "United Kingdom": [-1.5, 52.5],
    "Germany": [10.0, 51.2],
    "France": [2.5, 46.6],
    "Netherlands": [5.3, 52.1],
    "Switzerland": [8.2, 46.8],
    "Sweden": [15.0, 62.0],
    "Denmark": [9.5, 56.0],
    "Norway": [8.5, 61.0],
    "Finland": [26.0, 64.0],
    "Italy": [12.5, 42.8],
    "Spain": [-3.7, 40.3],
    "Portugal": [-8.0, 39.6],
    "Belgium": [4.5, 50.6],
    "Austria": [14.1, 47.6],
    "Ireland": [-8.0, 53.2],
    "Poland": [19.3, 52.1],
    "Greece": [22.0, 39.0],
    "Czechia": [15.5, 49.8],
    "Czech Republic": [15.5, 49.8],
    "Hungary": [19.4, 47.2],
    "Luxembourg": [6.1, 49.8],
    "Iceland": [-18.6, 64.9],
    "Romania": [25.0, 45.9],
    "Turkey": [35.2, 39.0],
    "Cyprus": [33.2, 35.1],
    "Malta": [14.4, 35.9],
    "Slovakia": [19.7, 48.7],
    "Slovenia": [14.8, 46.1],
    "Croatia": [15.9, 45.2],
    "Estonia": [25.0, 58.7],
    "Latvia": [24.9, 56.9],
    "Lithuania": [23.9, 55.3],
    "Bulgaria": [25.5, 42.7],
    "Monaco": [7.42, 43.73],
    "Liechtenstein": [9.55, 47.16],
    "China": [104.2, 35.9],
    "Hong Kong": [114.2, 22.3],
    "Japan": [138.2, 36.2],
    "South Korea": [127.8, 36.5],
    "Korea": [127.8, 36.5],
    "Taiwan": [121.0, 23.7],
    "India": [78.9, 20.6],
    "Brazil": [-51.9, -14.2],
    "Canada": [-106.3, 56.1],
    "Australia": [133.7, -25.3],
    "Singapore": [103.8, 1.35],
}

# Synthetic "sector reference comps" — 2025-era sector medians at the p25 /
# median / p75 / growth-leader points. Used because true peer screens need a
# paid screener; these anchor the comps engine with sane sector multiples.
def _ref_peers(prefix: str, label: str, rows: list[tuple]) -> list[dict]:
    names = ["p25", "median", "p75", "growth leader"]
    return [
        {
            "ticker": f"{prefix}-REF-{i + 1}",
            "name": f"{label} sector reference ({names[i]})",
            "pe_fwd": pe,
            "ev_ebitda": ee,
            "ev_sales": es,
            "growth": g,
        }
        for i, (pe, ee, es, g) in enumerate(rows)
    ]


SECTOR_COMPS: dict[str, list[dict]] = {
    "Technology": _ref_peers("TECH", "Technology", [
        (20.0, 13.0, 4.0, 0.06), (26.0, 17.0, 6.0, 0.10),
        (34.0, 22.0, 9.0, 0.15), (45.0, 30.0, 13.0, 0.25)]),
    "Semiconductors": _ref_peers("SEMI", "Semiconductors", [
        (14.0, 9.0, 3.0, 0.05), (20.0, 14.0, 5.0, 0.12),
        (28.0, 20.0, 8.0, 0.20), (38.0, 28.0, 14.0, 0.30)]),
    "Communication Services": _ref_peers("COMM", "Communication Services", [
        (12.0, 7.0, 2.0, 0.02), (17.0, 9.0, 3.0, 0.06),
        (23.0, 13.0, 5.0, 0.10), (30.0, 18.0, 8.0, 0.18)]),
    "Consumer Cyclical": _ref_peers("CCYC", "Consumer Cyclical", [
        (12.0, 8.0, 1.0, 0.02), (18.0, 11.0, 1.8, 0.05),
        (25.0, 15.0, 3.0, 0.10), (35.0, 20.0, 5.0, 0.18)]),
    "Consumer Defensive": _ref_peers("CDEF", "Consumer Defensive", [
        (14.0, 10.0, 1.5, 0.01), (18.0, 13.0, 2.2, 0.03),
        (22.0, 16.0, 3.2, 0.05), (27.0, 20.0, 4.5, 0.08)]),
    "Healthcare": _ref_peers("HLTH", "Healthcare", [
        (13.0, 9.0, 2.0, 0.03), (17.0, 12.0, 3.5, 0.06),
        (22.0, 16.0, 5.5, 0.10), (30.0, 22.0, 9.0, 0.15)]),
    "Financial Services": _ref_peers("FIN", "Financial Services", [
        (9.0, 8.0, 2.0, 0.02), (12.0, 10.0, 3.0, 0.05),
        (15.0, 13.0, 4.5, 0.08), (20.0, 16.0, 6.0, 0.12)]),
    "Industrials": _ref_peers("INDU", "Industrials", [
        (14.0, 9.0, 1.2, 0.02), (18.0, 12.0, 2.0, 0.05),
        (23.0, 15.0, 3.0, 0.08), (29.0, 19.0, 4.5, 0.12)]),
    "Energy": _ref_peers("ENRG", "Energy", [
        (7.0, 3.5, 0.7, 0.00), (10.0, 5.0, 1.1, 0.02),
        (13.0, 6.5, 1.8, 0.05), (17.0, 9.0, 2.8, 0.10)]),
    "Utilities": _ref_peers("UTIL", "Utilities", [
        (13.0, 9.0, 2.5, 0.02), (16.0, 11.0, 3.2, 0.04),
        (19.0, 13.0, 4.0, 0.06), (23.0, 15.0, 5.0, 0.08)]),
    "Real Estate": _ref_peers("REAL", "Real Estate", [
        (12.0, 12.0, 4.0, 0.01), (16.0, 15.0, 6.0, 0.03),
        (22.0, 18.0, 8.0, 0.05), (30.0, 22.0, 11.0, 0.08)]),
    "Basic Materials": _ref_peers("MATL", "Basic Materials", [
        (9.0, 5.0, 1.0, 0.00), (13.0, 7.0, 1.6, 0.03),
        (17.0, 9.0, 2.4, 0.06), (22.0, 12.0, 3.5, 0.10)]),
}

DEFAULT_SECTOR = "Industrials"

# Financial-statement-derived bundle keys (billions + per-share) that an FX
# conversion must touch. Margins and ratios are currency-free.
_FX_KEYS = (
    "revenue_b", "ebit_b", "net_income_b", "eps", "fcf_b", "da_b", "capex_b",
    "cfo_b", "total_assets_b", "total_liabilities_b", "current_assets_b",
    "current_liabilities_b", "long_term_debt_b", "equity_b",
    "retained_earnings_b", "working_capital_b", "rd_b",
)


# ------------------------------------------------------------ pure helpers


def normalize_quote(price: float | None, currency: str | None) -> tuple[float | None, str]:
    """Normalize a quoted price to a real currency.

    Yahoo quotes LSE listings in pence as "GBp" (some feeds use "GBX");
    both become GBP at price/100. Everything else passes through.
    """
    cur = (currency or "USD").strip()
    if cur in ("GBp", "GBX"):
        return (price / 100.0 if price is not None else None), "GBP"
    return price, cur


def convert_financials(fin: dict, rate: float) -> dict:
    """Convert one financial-year dict into the quote currency at ``rate``.

    Pure: returns a new dict. Touches only currency-denominated keys
    (billions + eps); leaves year and margin ratios alone.
    """
    out = dict(fin)
    for key in _FX_KEYS:
        value = out.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = round(value * rate, 4)
    return out


def _num(value) -> float | None:
    """float() with None/NaN/inf tolerance."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _row(df, names: tuple[str, ...], col) -> float | None:
    """First non-NaN value among candidate row labels at one column."""
    if df is None or getattr(df, "empty", True) or col is None:
        return None
    for name in names:
        if name in df.index:
            try:
                return _num(df.at[name, col])
            except (KeyError, ValueError):
                continue
    return None


def _match_col(df, target):
    """Column of df matching target Timestamp (exact, else same year)."""
    if df is None or getattr(df, "empty", True):
        return None
    cols = list(df.columns)
    if target in cols:
        return target
    for col in cols:
        try:
            if col.year == target.year:
                return col
        except AttributeError:
            continue
    return None


def _bn(value: float | None, rate: float = 1.0) -> float | None:
    return round(value * rate / 1e9, 4) if value is not None else None


# ------------------------------------------------------------ live fetches


def _fetch_fx_rate(fin_currency: str, quote_currency: str) -> float:
    """Latest close of {fin}{quote}=X. Raises CoverageError on failure."""
    if fin_currency == quote_currency:
        return 1.0
    try:
        import yfinance as yf

        hist = yf.Ticker(f"{fin_currency}{quote_currency}=X").history(period="5d")
        rate = _num(hist["Close"].iloc[-1]) if not hist.empty else None
    except Exception:
        rate = None
    if not rate or rate <= 0:
        raise CoverageError(
            f"FX rate {fin_currency}->{quote_currency} unavailable; cannot "
            "express the bundle in a single currency"
        )
    return rate


def _fetch_macro(sector: str) -> dict:
    macro = dict(MACRO_FALLBACK)
    live = None
    try:
        from .providers.fred import FredMacro

        live = FredMacro().fetch("")
        if live is None:
            # FRED's multi-series fredgraph.csv now returns a ZIP of CSVs
            # (daily.csv: DGS10, monthly.csv: CPIAUCSL+FEDFUNDS); the legacy
            # provider can't parse it, so unpack and reuse its CSV parser.
            import io
            import zipfile

            import httpx

            from .providers.fred import FRED_CSV_URL

            resp = httpx.get(FRED_CSV_URL, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            if "zip" in (resp.headers.get("content-type") or ""):
                merged: dict = {}
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    for name in zf.namelist():
                        if not name.lower().endswith(".csv"):
                            continue
                        part = FredMacro._parse(zf.read(name).decode("utf-8", "replace"))
                        if part:
                            merged.update(part)
                live = merged or None
            else:
                live = FredMacro._parse(resp.text)
        if live:
            macro.update({k: v for k, v in live.items() if v is not None})
    except Exception:
        pass
    macro["ism_pmi"] = None
    macro["erp"] = ERP
    macro["sector_signal"] = (
        f"{sector}: dynamic coverage — rates and concentration drive the macro view"
    )
    return macro


def _fetch_social(ticker: str, info: dict) -> dict:
    short_pct = _num(info.get("shortPercentOfFloat"))
    social = {
        "stocktwits_sentiment": 0.55,
        "reddit_mentions_30d": 0,
        "trend_score": 50.0,
        # Percent of float, capped — Yahoo occasionally serves garbage scales.
        "short_interest_pct": min(round(short_pct * 100, 2), 30.0) if short_pct is not None else 1.5,
        "iv_rank": 50.0,
        "summary": "no social tape for this listing — neutral prior",
    }
    try:
        from .providers.sentiment_social import StockTwitsSocial

        live = StockTwitsSocial().fetch(ticker)
        if live:
            social.update({k: v for k, v in live.items() if v is not None})
            # Tiny samples produce 0%/100% skews — clamp to a credible band.
            social["stocktwits_sentiment"] = min(max(
                float(social.get("stocktwits_sentiment", 0.55)), 0.05), 0.95)
    except Exception:
        pass
    return social


def _fetch_filings(ticker: str, is_us: bool) -> list[dict]:
    if not is_us:
        return []
    try:
        from .providers.edgar import EdgarFilings

        payload = EdgarFilings().fetch(ticker)
        if payload and payload.get("filings"):
            return payload["filings"]
    except Exception:
        pass
    return []


# ------------------------------------------------------------ sub-builders


def _build_financials(t, rate: float) -> list[dict]:
    """Up-to-4 annual columns, oldest first, in the QUOTE currency."""
    try:
        inc = t.income_stmt
    except Exception:
        inc = None
    try:
        bs = t.balance_sheet
    except Exception:
        bs = None
    try:
        cf = t.cashflow
    except Exception:
        cf = None

    if inc is None or getattr(inc, "empty", True):
        raise CoverageError("no income statement available from Yahoo")

    cols = sorted(inc.columns)[-4:]  # oldest-first, up to 4 annuals
    years: list[dict] = []
    usable = 0
    for col in cols:
        rev = _row(inc, ("Total Revenue", "Operating Revenue"), col)
        if not rev:
            continue
        ebit = _row(inc, ("Operating Income", "EBIT", "Total Operating Income As Reported"), col)
        ni = _row(inc, ("Net Income", "Net Income Common Stockholders",
                        "Net Income From Continuing Operation Net Minority Interest"), col)
        if ebit is not None:
            usable += 1
        if ni is None:
            ni = ebit * 0.8 if ebit is not None else None
        if ebit is None:
            ebit = ni / 0.8 if ni is not None else rev * 0.10
        if ni is None:
            ni = ebit * 0.8

        gp = _row(inc, ("Gross Profit",), col)
        cogs = _row(inc, ("Cost Of Revenue", "Reconciled Cost Of Revenue"), col)
        op_margin = ebit / rev
        if gp is not None:
            gross_margin = gp / rev
        elif cogs is not None:
            gross_margin = 1.0 - cogs / rev
        else:
            gross_margin = min(op_margin + 0.15, 0.9)

        bs_col = _match_col(bs, col)
        cf_col = _match_col(cf, col)

        cfo = _row(cf, ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"), cf_col)
        capex = _row(cf, ("Capital Expenditure", "Capital Expenditure Reported"), cf_col)
        capex = abs(capex) if capex is not None else 0.05 * rev
        fcf = _row(cf, ("Free Cash Flow",), cf_col)
        da = _row(cf, ("Depreciation And Amortization", "Depreciation Amortization Depletion",
                       "Depreciation"), cf_col)
        if da is None:
            da = _row(inc, ("Reconciled Depreciation",
                            "Depreciation And Amortization In Income Statement"), col)
        if da is None:
            da = 0.05 * rev
        if cfo is None:
            cfo = ni + da
        if fcf is None:
            fcf = cfo - abs(capex)

        eps = _row(inc, ("Diluted EPS", "Basic EPS"), col)
        if eps is None:
            shares = _row(inc, ("Diluted Average Shares", "Basic Average Shares"), col)
            eps = ni / shares if shares else None

        assets = _row(bs, ("Total Assets",), bs_col)
        equity = _row(bs, ("Stockholders Equity", "Total Equity Gross Minority Interest"), bs_col)
        liabs = _row(bs, ("Total Liabilities Net Minority Interest",), bs_col)
        if assets is None:
            assets = (equity or 0) + (liabs or 0) or 2.0 * rev
        if liabs is None:
            liabs = assets - equity if equity is not None else 0.5 * assets
        if equity is None:
            equity = assets - liabs
        cur_assets = _row(bs, ("Current Assets",), bs_col)
        cur_liabs = _row(bs, ("Current Liabilities",), bs_col)
        if cur_assets is None:
            cur_assets = 0.3 * assets
        if cur_liabs is None:
            cur_liabs = 0.2 * assets
        ltd = _row(bs, ("Long Term Debt And Capital Lease Obligation", "Long Term Debt"), bs_col)
        if ltd is None:
            total_debt = _row(bs, ("Total Debt",), bs_col)
            short_debt = _row(bs, ("Current Debt And Capital Lease Obligation", "Current Debt"), bs_col) or 0.0
            ltd = max(total_debt - short_debt, 0.0) if total_debt is not None else 0.0
        retained = _row(bs, ("Retained Earnings",), bs_col)
        if retained is None:
            retained = equity * 0.6
        rd = _row(inc, ("Research And Development",), col) or 0.0

        year = {
            "year": f"FY{col.year}",
            "revenue_b": _bn(rev),
            "gross_margin": round(gross_margin, 4),
            "ebit_b": _bn(ebit),
            "op_margin": round(op_margin, 4),
            "net_income_b": _bn(ni),
            "eps": round(eps, 4) if eps is not None else round(ni / 1e9, 4),
            "fcf_b": _bn(fcf),
            "da_b": _bn(da),
            "capex_b": _bn(capex),
            "cfo_b": _bn(cfo),
            "total_assets_b": _bn(assets),
            "total_liabilities_b": _bn(liabs),
            "current_assets_b": _bn(cur_assets),
            "current_liabilities_b": _bn(cur_liabs),
            "long_term_debt_b": _bn(ltd),
            "equity_b": _bn(equity),
            "retained_earnings_b": _bn(retained),
            "working_capital_b": _bn(cur_assets - cur_liabs),
            "rd_b": _bn(rd),
        }
        years.append(convert_financials(year, rate) if rate != 1.0 else year)

    if len(years) < 2 or usable < 2:
        raise CoverageError("insufficient financial history (need 2+ annual years "
                            "with revenue and operating income)")
    return years


def _build_market(t, info: dict, financials: list[dict], rate: float,
                  quote_raw: str) -> tuple[dict, float]:
    """Market section in the quote currency. Returns (market, last_price)."""
    pence = quote_raw in ("GBp", "GBX")
    factor = 0.01 if pence else 1.0

    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
    closes: list[float] = []
    try:
        hist = t.history(period="1y")
        if hist is not None and not hist.empty and "Close" in hist:
            closes = [round(float(c) * factor, 2) for c in hist["Close"].tolist() if _num(c)]
            closes = closes[-252:]
    except Exception:
        pass
    if price is not None:
        price *= factor
    elif closes:
        price = closes[-1]
    else:
        raise CoverageError("no market price available for this listing")
    price = round(price, 2)

    shares = _num(info.get("sharesOutstanding"))
    if not shares:
        try:
            shares = _num(getattr(t.fast_info, "shares", None))
        except Exception:
            shares = None
    if not shares:
        raise CoverageError("shares outstanding unavailable; cannot size the company")

    market_cap_b = round(price * shares / 1e9, 1)  # recomputed — never trust Yahoo's LSE cap

    latest = financials[-1]
    total_debt = _num(info.get("totalDebt"))
    total_cash = _num(info.get("totalCash"))
    if total_debt is not None and total_cash is not None:
        net_debt_b = round((total_debt - total_cash) * rate / 1e9, 2)
    else:
        # Fallback: balance-sheet LTD minus cash (already quote currency).
        net_debt_b = round(latest["long_term_debt_b"] - 0.5 * latest["current_assets_b"], 2)
        if net_debt_b != net_debt_b:  # NaN guard
            net_debt_b = 0.0

    ebit_b, da_b, rev_b = latest["ebit_b"], latest["da_b"], latest["revenue_b"]
    ev_b = market_cap_b + net_debt_b
    pe_fwd = _num(info.get("forwardPE"))
    ev_ebitda = _num(info.get("enterpriseToEbitda"))
    if ev_ebitda is None and (ebit_b + da_b) > 0:
        ev_ebitda = round(ev_b / (ebit_b + da_b), 2)
    ev_sales = _num(info.get("enterpriseToRevenue"))
    if ev_sales is None and rev_b > 0:
        ev_sales = round(ev_b / rev_b, 2)

    low = _num(info.get("fiftyTwoWeekLow"))
    high = _num(info.get("fiftyTwoWeekHigh"))
    week52_low = round(low * factor, 2) if low is not None else (round(min(closes), 2) if closes else price)
    week52_high = round(high * factor, 2) if high is not None else (round(max(closes), 2) if closes else price)

    market = {
        "last_price": price,
        "market_cap_b": market_cap_b,
        "shares_out_b": round(shares / 1e9, 4),
        "net_debt_b": net_debt_b,
        "beta": _num(info.get("beta")) or 1.0,
        "pe_fwd": round(pe_fwd, 2) if pe_fwd is not None else None,
        "ev_ebitda": round(ev_ebitda, 2) if ev_ebitda is not None else None,
        "ev_sales": round(ev_sales, 2) if ev_sales is not None else None,
        "week52_low": week52_low,
        "week52_high": week52_high,
        "price_history": closes or [price],
    }
    return market, price


def _build_estimates(t, info: dict, financials: list[dict], price: float,
                     rate: float, quote_currency: str, fin_currency: str,
                     quote_raw: str) -> dict:
    latest = financials[-1]

    # Growth: consensus next-FY revenue growth, else faded trailing CAGR.
    growth = None
    try:
        rev_est = t.revenue_estimate
        if rev_est is not None and not rev_est.empty and "+1y" in rev_est.index:
            growth = _num(rev_est.at["+1y", "growth"])
    except Exception:
        pass
    if growth is None:
        revs = [f["revenue_b"] for f in financials if f.get("revenue_b")]
        if len(revs) >= 3 and revs[-3] > 0:
            cagr = (revs[-1] / revs[-3]) ** 0.5 - 1.0
        elif len(revs) >= 2 and revs[-2] > 0:
            cagr = revs[-1] / revs[-2] - 1.0
        else:
            cagr = 0.04
        growth = max(-0.10, min(0.40, cagr * 0.8))
    growth = round(growth, 4)

    # EPS next FY: consensus avg, converted into the quote currency.
    eps_next = None
    try:
        eps_est = t.earnings_estimate
        if eps_est is not None and not eps_est.empty and "+1y" in eps_est.index:
            eps_next = _num(eps_est.at["+1y", "avg"])
            est_cur = None
            if "currency" in eps_est.columns:
                est_cur = str(eps_est.at["+1y", "currency"] or "")
            if eps_next is not None and est_cur and est_cur != quote_currency:
                eps_next = eps_next * rate if est_cur == fin_currency else eps_next * _fetch_fx_rate(est_cur, quote_currency)
    except CoverageError:
        eps_next = None
    except Exception:
        eps_next = None
    if eps_next is None:
        eps_next = latest["eps"] * (1.0 + growth)

    rec = info.get("recommendationKey")
    consensus = rec.replace("_", " ").title() if isinstance(rec, str) and rec and rec != "none" else "Hold"

    pence = quote_raw in ("GBp", "GBX")
    pt_factor = 0.01 if pence else 1.0
    pt_mean = _num(info.get("targetMeanPrice"))
    pt_high = _num(info.get("targetHighPrice"))
    pt_low = _num(info.get("targetLowPrice"))
    if pt_mean is None or pt_high is None or pt_low is None:
        pt_mean = pt_high = pt_low = None
    else:
        pt_mean = round(pt_mean * pt_factor, 2)
        pt_high = round(pt_high * pt_factor, 2)
        pt_low = round(pt_low * pt_factor, 2)

    return {
        "rev_growth_next_fy": growth,
        "rev_growth_fy2": round(growth * 0.85, 4),
        "eps_next_fy": round(eps_next, 4),
        "consensus_rating": consensus,
        "n_analysts": int(_num(info.get("numberOfAnalystOpinions")) or 0),
        "pt_mean": pt_mean,
        "pt_high": pt_high,
        "pt_low": pt_low,
    }


def _build_ownership(t, info: dict) -> dict:
    inst = _num(info.get("heldPercentInstitutions"))
    # Fraction 0..1, matching the fixture schema.
    institutional_pct = round(inst, 4) if inst is not None else 0.5

    net_shares = 0
    try:
        it = t.insider_transactions
        if it is not None and not it.empty:
            cutoff = _dt.datetime.now() - _dt.timedelta(days=183)
            for _, row in it.iterrows():
                start = row.get("Start Date")
                try:
                    if start is None or start.to_pydatetime() < cutoff:
                        continue
                except Exception:
                    continue
                text = str(row.get("Text") or "").lower()
                shares = _num(row.get("Shares")) or 0
                if "sale" in text:
                    net_shares -= int(shares)
                elif "purchase" in text or "buy" in text:
                    net_shares += int(shares)
    except Exception:
        net_shares = 0

    top_holders: list[dict] = []
    try:
        ih = t.institutional_holders
        if ih is not None and not ih.empty and "Holder" in ih.columns:
            for _, row in ih.head(5).iterrows():
                pct = _num(row.get("pctHeld"))
                top_holders.append({"name": str(row["Holder"]),
                                    "pct": round(pct, 4) if pct is not None else 0.0})
    except Exception:
        top_holders = []

    if net_shares < 0:
        signal = "net selling, routine"
    elif net_shares > 0:
        signal = "net buying"
    else:
        signal = "no insider tape for this listing"

    return {
        "institutional_pct": institutional_pct,
        "insider_net_shares_6m": net_shares,
        "top_holders": top_holders,
        "form4_signal": signal,
    }


def _pick_peers(info: dict) -> list[dict]:
    industry = str(info.get("industry") or "")
    if "Semiconductor" in industry:
        return SECTOR_COMPS["Semiconductors"]
    sector = str(info.get("sector") or "")
    return SECTOR_COMPS.get(sector, SECTOR_COMPS[DEFAULT_SECTOR])


# ------------------------------------------------------------------- main


def build_bundle(ticker: str, cache: DataCache | None = None) -> dict:
    """Build the full fixture-schema research bundle for any listed name."""
    ticker = ticker.upper().strip()

    if cache is not None:
        cached = cache.get(ticker, BUNDLE_SOURCE)
        if cached:
            return cached

    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as exc:
        raise CoverageError(f"Yahoo lookup failed for {ticker}: {exc}") from exc

    quote_raw = str(info.get("currency") or "USD")
    _, quote_currency = normalize_quote(None, quote_raw)
    fin_currency = str(info.get("financialCurrency") or quote_currency)
    rate = _fetch_fx_rate(fin_currency, quote_currency)  # CoverageError on miss

    financials = _build_financials(t, rate)
    market, price = _build_market(t, info, financials, rate, quote_raw)
    estimates = _build_estimates(t, info, financials, price, rate,
                                 quote_currency, fin_currency, quote_raw)
    ownership = _build_ownership(t, info)

    country = str(info.get("country") or "United States")
    is_us = country == "United States"
    sector = info.get("sector") or "—"
    company = info.get("longName") or info.get("shortName") or ticker
    latest_rev = financials[-1]["revenue_b"]

    bundle = {
        "as_of": _dt.date.today().isoformat(),
        "ticker": ticker,
        "company": company,
        "sector": sector,
        "currency": quote_currency,
        "hq": COUNTRY_CENTROIDS.get(country, [0.0, 0.0]),
        "market": market,
        "financials": financials,
        "estimates": estimates,
        "ownership": ownership,
        "geo_revenue": [
            {
                "iso_n3": COUNTRY_ISO_N3.get(country, "840"),
                "name": country,
                "revenue_share": 1.0,
                "revenue_usd_b": latest_rev,
                "note": ("geographic segmentation not parsed for dynamic "
                         "coverage — domicile shown"),
            }
        ],
        "arcs": [],
        "filings": _fetch_filings(ticker, is_us),
        "social": _fetch_social(ticker, info),
        "macro": _fetch_macro(sector),
        "peers": _pick_peers(info),
        "live_sources": ["yfinance_built", "fred_macro", "sector_reference_comps"],
        "mode_data": "live-built",
    }

    if cache is not None:
        cache.put(ticker, BUNDLE_SOURCE, bundle, ttl_hours=BUNDLE_TTL_HOURS)
    return bundle
