"""Retail sentiment from the public StockTwits symbol stream.

The stream returns ~30 recent messages, some tagged Bullish/Bearish by
their authors. We compute the bullish share among labeled messages and
merge it over the fixture's social block. Returns None on any failure
or if too few labeled messages to be meaningful.
"""

from __future__ import annotations

from .base import SocialProvider

STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
MIN_LABELED = 3


class StockTwitsSocial(SocialProvider):
    name = "stocktwits_social"

    def fetch(self, ticker: str) -> dict | None:
        try:
            import httpx

            resp = httpx.get(
                STREAM_URL.format(ticker=ticker.upper()),
                timeout=10.0,
                follow_redirects=True,
                headers={"User-Agent": "DELPHI Research delphi@example.com"},
            )
            resp.raise_for_status()
            messages = resp.json().get("messages", [])

            bullish = bearish = 0
            for msg in messages:
                sentiment = ((msg.get("entities") or {}).get("sentiment") or {})
                basic = sentiment.get("basic")
                if basic == "Bullish":
                    bullish += 1
                elif basic == "Bearish":
                    bearish += 1

            labeled = bullish + bearish
            if labeled < MIN_LABELED:
                return None

            share = bullish / labeled
            return {
                "stocktwits_sentiment": round(share, 2),
                "summary": (
                    f"StockTwits: {share:.0%} bullish across {labeled} "
                    f"labeled messages in the latest stream"
                ),
            }
        except Exception:
            return None
