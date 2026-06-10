"""Live market data via yfinance (free, keyless).

Returns the fixture ``market`` shape — only the keys yfinance can
actually source — so the bundle loader can deep-merge it straight over
the snapshot. Any failure (network, schema drift, delisting) returns
None and the fixture stands.
"""

from __future__ import annotations

from .base import MarketProvider


class YFinanceMarket(MarketProvider):
    name = "yfinance_market"

    def fetch(self, ticker: str) -> dict | None:
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            fast = t.fast_info
            out: dict = {}

            last_price = _safe_float(getattr(fast, "last_price", None))
            if last_price:
                out["last_price"] = round(last_price, 2)

            market_cap = _safe_float(getattr(fast, "market_cap", None))
            if market_cap:
                out["market_cap_b"] = round(market_cap / 1e9, 1)

            shares = _safe_float(getattr(fast, "shares", None))
            if shares:
                out["shares_out_b"] = round(shares / 1e9, 3)

            low = _safe_float(getattr(fast, "year_low", None))
            high = _safe_float(getattr(fast, "year_high", None))
            if low:
                out["week52_low"] = round(low, 2)
            if high:
                out["week52_high"] = round(high, 2)

            hist = t.history(period="1y")
            if hist is not None and not hist.empty and "Close" in hist:
                closes = [round(float(c), 2) for c in hist["Close"].tolist()]
                # Downsample to at most 252 closes, keeping the most recent.
                if len(closes) > 252:
                    closes = closes[-252:]
                if closes:
                    out["price_history"] = closes
                    if "last_price" not in out:
                        out["last_price"] = closes[-1]

            return out or None
        except Exception:
            return None


def _safe_float(value) -> float | None:
    try:
        f = float(value)
        return f if f == f else None  # NaN guard
    except (TypeError, ValueError):
        return None
