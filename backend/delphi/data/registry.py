"""Company search & resolution across fixtures, SEC registrants, and Yahoo.

Three keyless sources, merged and deduped by ticker:

1. The bundled fixtures (always first — instant, offline, fully covered).
2. The SEC full registrant map (~10k US names) — substring/prefix matched
   and ranked ticker-exact > ticker-prefix > company-name match.
3. Yahoo Finance search — the only source that surfaces non-US listings
   (ASML.AS, SAP.DE, MC.PA, NESN.SW, SHEL.L, ...) with exchange metadata.

Every source is wrapped in try/except: if the network is gone we still
return whatever the fixtures can answer.
"""

from __future__ import annotations

import time

from .bundle import available_tickers
from .cache import DataCache

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = "DELPHI Research delphi@example.com"
YAHOO_SEARCH_URL = (
    "https://query2.finance.yahoo.com/v1/finance/search"
    "?q={query}&quotesCount=10&newsCount=0"
)
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Yahoo exchange code -> (display name, country). Covers the major US and
# European venues plus the rest-of-world codes Yahoo commonly returns.
EXCHANGE_COUNTRY: dict[str, tuple[str, str]] = {
    "NMS": ("NASDAQ", "United States"),
    "NGM": ("NASDAQ", "United States"),
    "NCM": ("NASDAQ", "United States"),
    "NYQ": ("NYSE", "United States"),
    "ASE": ("NYSE American", "United States"),
    "PCX": ("NYSE Arca", "United States"),
    "BTS": ("Cboe BZX", "United States"),
    "PNK": ("OTC Markets", "United States"),
    "OQB": ("OTCQB", "United States"),
    "OQX": ("OTCQX", "United States"),
    "LSE": ("London Stock Exchange", "United Kingdom"),
    "IOB": ("LSE Intl Order Book", "United Kingdom"),
    "GER": ("XETRA", "Germany"),
    "FRA": ("Frankfurt", "Germany"),
    "BER": ("Berlin", "Germany"),
    "STU": ("Stuttgart", "Germany"),
    "MUN": ("Munich", "Germany"),
    "DUS": ("Dusseldorf", "Germany"),
    "HAM": ("Hamburg", "Germany"),
    "PAR": ("Euronext Paris", "France"),
    "AMS": ("Euronext Amsterdam", "Netherlands"),
    "BRU": ("Euronext Brussels", "Belgium"),
    "LIS": ("Euronext Lisbon", "Portugal"),
    "MIL": ("Borsa Italiana", "Italy"),
    "MCE": ("Bolsa de Madrid", "Spain"),
    "EBS": ("SIX Swiss Exchange", "Switzerland"),
    "VTX": ("SIX Swiss Exchange", "Switzerland"),
    "STO": ("Nasdaq Stockholm", "Sweden"),
    "CPH": ("Nasdaq Copenhagen", "Denmark"),
    "HEL": ("Nasdaq Helsinki", "Finland"),
    "OSL": ("Oslo Bors", "Norway"),
    "ISE": ("Euronext Dublin", "Ireland"),
    "DUB": ("Euronext Dublin", "Ireland"),
    "VIE": ("Vienna Stock Exchange", "Austria"),
    "WSE": ("Warsaw Stock Exchange", "Poland"),
    "ATH": ("Athens Stock Exchange", "Greece"),
    "PRA": ("Prague Stock Exchange", "Czechia"),
    "BUD": ("Budapest Stock Exchange", "Hungary"),
    "IST": ("Borsa Istanbul", "Turkey"),
    "TOR": ("Toronto Stock Exchange", "Canada"),
    "VAN": ("TSX Venture", "Canada"),
    "JPX": ("Tokyo Stock Exchange", "Japan"),
    "TYO": ("Tokyo Stock Exchange", "Japan"),
    "HKG": ("Hong Kong Stock Exchange", "Hong Kong"),
    "SHH": ("Shanghai Stock Exchange", "China"),
    "SHZ": ("Shenzhen Stock Exchange", "China"),
    "KSC": ("Korea Exchange", "South Korea"),
    "KOE": ("KOSDAQ", "South Korea"),
    "TAI": ("Taiwan Stock Exchange", "Taiwan"),
    "BSE": ("Bombay Stock Exchange", "India"),
    "NSI": ("National Stock Exchange of India", "India"),
    "SAO": ("B3 Sao Paulo", "Brazil"),
    "ASX": ("Australian Securities Exchange", "Australia"),
    "SES": ("Singapore Exchange", "Singapore"),
}

_SEC_TTL_SECONDS = 24 * 3600
_sec_map: list[dict] | None = None  # process-lifetime cache
_sec_map_at: float = 0.0


def search_companies(query: str, limit: int = 12) -> list[dict]:
    """Search the coverable universe. Fixture hits first, then SEC, then Yahoo.

    Returns [{"ticker","company","sector","exchange","country","source"}].
    Resilient: every source is best-effort; worst case is fixtures only.
    """
    query = (query or "").strip()
    if not query:
        return []

    results: list[dict] = []
    results.extend(_fixture_matches(query))
    try:
        results.extend(_sec_matches(query))
    except Exception:
        pass
    try:
        results.extend(_yahoo_matches(query))
    except Exception:
        pass

    seen: set[str] = set()
    merged: list[dict] = []
    for row in results:
        key = row["ticker"].upper()
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
        if len(merged) >= limit:
            break
    return merged


def resolve(ticker: str) -> dict | None:
    """Quick existence check for one ticker; same dict shape as search."""
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return None

    for row in _fixture_rows():
        if row["ticker"] == ticker:
            return row

    try:
        for entry in _load_sec_map():
            if entry["ticker"] == ticker:
                return {
                    "ticker": entry["ticker"],
                    "company": entry["title"],
                    "sector": "—",
                    "exchange": "US-listed (SEC registrant)",
                    "country": "United States",
                    "source": "sec",
                }
    except Exception:
        pass

    try:
        import yfinance as yf

        fast = yf.Ticker(ticker).fast_info
        last = getattr(fast, "last_price", None)
        if last is not None and float(last) == float(last):  # NaN guard
            return {
                "ticker": ticker,
                "company": ticker,
                "sector": "—",
                "exchange": getattr(fast, "exchange", None) or "—",
                "country": "—",
                "source": "yahoo",
            }
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- fixtures


def _fixture_rows() -> list[dict]:
    rows = []
    for fx in available_tickers():
        rows.append(
            {
                "ticker": fx["ticker"],
                "company": fx["company"],
                "sector": fx["sector"],
                "exchange": "NASDAQ",
                "country": "United States",
                "source": "fixture",
            }
        )
    return rows


def _fixture_matches(query: str) -> list[dict]:
    q = query.lower()
    out = []
    for row in _fixture_rows():
        if q in row["ticker"].lower() or q in row["company"].lower():
            out.append(row)
    return out


# ---------------------------------------------------------------- SEC


def _load_sec_map() -> list[dict]:
    """The full SEC registrant list as [{"ticker","title"}], cached
    in-process and in the DataCache (24h)."""
    global _sec_map, _sec_map_at
    if _sec_map is not None and time.time() - _sec_map_at < _SEC_TTL_SECONDS:
        return _sec_map

    cache = None
    try:
        cache = DataCache()
        payload = cache.get("__sec__", "tickers")
        if payload and isinstance(payload.get("companies"), list):
            _sec_map = payload["companies"]
            _sec_map_at = time.time()
            return _sec_map
    except Exception:
        cache = None

    import httpx

    resp = httpx.get(
        SEC_TICKER_URL,
        headers={"User-Agent": SEC_USER_AGENT},
        timeout=15.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    companies = [
        {"ticker": str(entry["ticker"]).upper(), "title": str(entry["title"])}
        for entry in resp.json().values()
    ]
    _sec_map = companies
    _sec_map_at = time.time()
    if cache is not None:
        try:
            cache.put("__sec__", "tickers", {"companies": companies}, ttl_hours=24)
        except Exception:
            pass
    return companies


def _sec_matches(query: str) -> list[dict]:
    q = query.upper()
    tokens = [t for t in query.lower().split() if t]
    scored: list[tuple[int, str, dict]] = []
    for entry in _load_sec_map():
        ticker, title = entry["ticker"], entry["title"]
        if ticker == q:
            score = 0
        elif ticker.startswith(q):
            score = 1
        elif tokens and all(t in title.lower() for t in tokens):
            score = 2
        else:
            continue
        scored.append(
            (
                score,
                ticker,
                {
                    "ticker": ticker,
                    "company": title,
                    "sector": "—",
                    "exchange": "US-listed (SEC registrant)",
                    "country": "United States",
                    "source": "sec",
                },
            )
        )
    scored.sort(key=lambda item: (item[0], len(item[1]), item[1]))
    return [row for _, _, row in scored[:12]]


# ---------------------------------------------------------------- Yahoo


def _yahoo_matches(query: str) -> list[dict]:
    quotes = _yahoo_quotes(query)
    out = []
    for quote in quotes:
        if quote.get("quoteType") != "EQUITY":
            continue
        symbol = quote.get("symbol")
        if not symbol:
            continue
        exch_code = quote.get("exchange") or ""
        exch_disp, country = EXCHANGE_COUNTRY.get(
            exch_code, (quote.get("exchDisp") or exch_code or "—", "—")
        )
        out.append(
            {
                "ticker": str(symbol).upper(),
                "company": quote.get("longname")
                or quote.get("shortname")
                or str(symbol).upper(),
                "sector": quote.get("sectorDisp") or quote.get("sector") or "—",
                "exchange": quote.get("exchDisp") or exch_disp,
                "country": country,
                "source": "yahoo",
            }
        )
    return out


def _yahoo_quotes(query: str) -> list[dict]:
    """yfinance Search first (handles Yahoo's cookie/crumb dance), raw
    HTTP as the fallback."""
    try:
        import yfinance as yf

        search = yf.Search(query, max_results=10, news_count=0)
        quotes = search.quotes
        if quotes:
            return list(quotes)
    except Exception:
        pass

    import httpx

    resp = httpx.get(
        YAHOO_SEARCH_URL.format(query=query),
        headers={"User-Agent": BROWSER_USER_AGENT},
        timeout=10.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return list(resp.json().get("quotes", []))
