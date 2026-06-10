"""Provider interfaces for the DELPHI data layer.

Each data domain (market, estimates, ownership, macro, filings, social)
gets a single-method ABC. Concrete adapters wrap free sources today; at a
bank, you'd drop the Refinitiv adapter behind the same interface; nothing
else in the system changes.

Contract for every adapter:
- ``fetch(ticker)`` returns a dict shaped like the matching fixture
  section (possibly partial — only the keys it could actually source), or
  ``None`` on any failure.
- Adapters catch their own exceptions. A provider must never take the
  bundle loader down with it; the fixture snapshot is always the floor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class MarketProvider(ABC):
    """Price, capitalization, multiples, and trailing price history."""

    name: str = "market"

    @abstractmethod
    def fetch(self, ticker: str) -> dict | None:
        ...


class EstimatesProvider(ABC):
    """Consensus revenue/EPS estimates, ratings, and price targets."""

    name: str = "estimates"

    @abstractmethod
    def fetch(self, ticker: str) -> dict | None:
        ...


class OwnershipProvider(ABC):
    """Institutional holders and insider transaction signals."""

    name: str = "ownership"

    @abstractmethod
    def fetch(self, ticker: str) -> dict | None:
        ...


class MacroProvider(ABC):
    """Rates, inflation, and cycle indicators framing the sector call."""

    name: str = "macro"

    @abstractmethod
    def fetch(self, ticker: str) -> dict | None:
        ...


class FilingsProvider(ABC):
    """Regulatory filing references (10-K/10-Q/8-K) with source URLs."""

    name: str = "filings"

    @abstractmethod
    def fetch(self, ticker: str) -> dict | None:
        ...


class SocialProvider(ABC):
    """Retail sentiment, attention, and positioning reads."""

    name: str = "social"

    @abstractmethod
    def fetch(self, ticker: str) -> dict | None:
        ...
