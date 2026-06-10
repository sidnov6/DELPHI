"""Consensus estimates adapter backed by the bundled fixture snapshots.

This is the triangulation point for Finnhub/FMP adapters: both expose
consensus estimates on free tiers but require API keys, so the bundled
consensus snapshot is the default adapter. Swap in a keyed adapter
behind the same EstimatesProvider interface and nothing else changes.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import EstimatesProvider

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class FixtureEstimates(EstimatesProvider):
    name = "fixture_estimates"

    def fetch(self, ticker: str) -> dict | None:
        try:
            path = FIXTURES_DIR / f"{ticker.upper()}.json"
            if not path.exists():
                return None
            snapshot = json.loads(path.read_text())
            estimates = snapshot.get("estimates")
            return estimates if isinstance(estimates, dict) else None
        except Exception:
            return None
