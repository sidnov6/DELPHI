"""Unified data bundle loader for DELPHI.

The fixture snapshot is always the base — the demo works fully offline.
When ``online=True`` we try the cache, then each live provider, and
deep-merge whatever actually came back over the fixture (never clobbering
fixture keys with None). The bundle is stamped with the providers that
succeeded so the agent layer can disclose data provenance.
"""

from __future__ import annotations

import json
from pathlib import Path

from .cache import DataCache

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def available_tickers() -> list[dict]:
    """Tickers with bundled fixture coverage, sorted by ticker."""
    out = []
    for path in FIXTURES_DIR.glob("*.json"):
        try:
            snapshot = json.loads(path.read_text())
            out.append(
                {
                    "ticker": snapshot["ticker"],
                    "company": snapshot["company"],
                    "sector": snapshot["sector"],
                }
            )
        except Exception:
            continue
    return sorted(out, key=lambda row: row["ticker"])


def load_bundle(ticker: str, online: bool = True, cache: DataCache | None = None) -> dict:
    """Load the full research bundle for one ticker.

    Fixture JSON is the base; live providers enrich it when reachable.
    Non-fixture tickers are built dynamically from live sources when
    online; offline, unknown tickers raise ValueError listing the
    bundled universe.
    """
    ticker = ticker.upper().strip()
    path = FIXTURES_DIR / f"{ticker}.json"
    if not path.exists():
        if online:
            from .builder import build_bundle  # lazy: offline path stays import-free

            return build_bundle(ticker, cache=cache)
        universe = ", ".join(row["ticker"] for row in available_tickers())
        raise ValueError(f"No coverage for {ticker}. Universe: {universe}")

    bundle = json.loads(path.read_text())
    live_sources: list[str] = []

    if online:
        for provider, section in _live_providers():
            payload = None
            if cache is not None:
                payload = cache.get(ticker, provider.name)
                from_cache = payload is not None
            else:
                from_cache = False

            if payload is None:
                try:
                    payload = provider.fetch(ticker)
                except Exception:
                    payload = None  # providers self-guard, but belt and braces

            if not payload:
                continue

            if cache is not None and not from_cache:
                cache.put(ticker, provider.name, payload)

            if section is None:
                _deep_merge(bundle, payload)  # provider returns top-level keys
            else:
                node = bundle.setdefault(section, {})
                if isinstance(node, dict):
                    _deep_merge(node, payload)
            live_sources.append(provider.name)

    bundle["live_sources"] = live_sources
    bundle["mode_data"] = "live+snapshot" if live_sources else "snapshot"
    if any("market" in src for src in live_sources):
        # The tape is live — don't let the bundled snapshot date imply staleness.
        from datetime import date
        bundle["as_of"] = date.today().isoformat()
    return bundle


def _live_providers() -> list[tuple]:
    """(provider, target_section) pairs; section None = merge at top level.

    Imported lazily so the fully-offline path never touches network
    libraries, and a broken optional dependency can't break fixture mode.
    """
    pairs = []
    try:
        from .providers.market import YFinanceMarket

        pairs.append((YFinanceMarket(), "market"))
    except Exception:
        pass
    try:
        from .providers.fred import FredMacro

        pairs.append((FredMacro(), "macro"))
    except Exception:
        pass
    try:
        from .providers.edgar import EdgarFilings

        pairs.append((EdgarFilings(), None))  # returns {"filings": [...]}
    except Exception:
        pass
    try:
        from .providers.sentiment_social import StockTwitsSocial

        pairs.append((StockTwitsSocial(), "social"))
    except Exception:
        pass
    return pairs


def _deep_merge(base: dict, overlay: dict) -> None:
    """Merge overlay into base in place. None never clobbers; dicts recurse;
    everything else (scalars, lists) replaces wholesale."""
    for key, value in overlay.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
