"""Tests for the DELPHI data layer. Fully offline — no network calls."""

import json

import pytest

from delphi.data.bundle import FIXTURES_DIR, available_tickers, load_bundle

TICKERS = ["AAPL", "AMZN", "GOOGL", "MSFT", "NVDA", "TSLA"]

TOP_LEVEL_KEYS = [
    "as_of", "ticker", "company", "sector", "currency", "hq",
    "market", "financials", "estimates", "ownership", "geo_revenue",
    "arcs", "filings", "social", "macro", "peers",
]

MARKET_KEYS = [
    "last_price", "market_cap_b", "shares_out_b", "net_debt_b", "beta",
    "pe_fwd", "ev_ebitda", "ev_sales", "week52_low", "week52_high",
    "price_history",
]

FINANCIAL_KEYS = [
    "year", "revenue_b", "gross_margin", "ebit_b", "op_margin",
    "net_income_b", "eps", "fcf_b", "da_b", "capex_b", "cfo_b",
    "total_assets_b", "total_liabilities_b", "current_assets_b",
    "current_liabilities_b", "long_term_debt_b", "equity_b",
    "retained_earnings_b", "working_capital_b", "rd_b",
]

ESTIMATES_KEYS = [
    "rev_growth_next_fy", "rev_growth_fy2", "eps_next_fy",
    "consensus_rating", "n_analysts", "pt_mean", "pt_high", "pt_low",
]

OWNERSHIP_KEYS = [
    "institutional_pct", "insider_net_shares_6m", "top_holders", "form4_signal",
]

SOCIAL_KEYS = [
    "stocktwits_sentiment", "reddit_mentions_30d", "trend_score",
    "short_interest_pct", "iv_rank", "summary",
]

MACRO_KEYS = ["rf_10y", "cpi_yoy", "ism_pmi", "fed_funds", "sector_signal", "erp"]


def load_fixture(ticker: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{ticker}.json").read_text())


@pytest.mark.parametrize("ticker", TICKERS)
def test_fixture_loads_with_schema(ticker):
    snap = load_fixture(ticker)
    for key in TOP_LEVEL_KEYS:
        assert key in snap, f"{ticker}: missing top-level key {key}"
    assert snap["ticker"] == ticker
    assert snap["as_of"] == "2026-01-15"
    assert snap["currency"] == "USD"
    assert len(snap["hq"]) == 2

    for key in MARKET_KEYS:
        assert key in snap["market"], f"{ticker}: market missing {key}"

    assert len(snap["financials"]) == 4
    for fy in snap["financials"]:
        for key in FINANCIAL_KEYS:
            assert key in fy, f"{ticker}: financials missing {key}"

    for key in ESTIMATES_KEYS:
        assert key in snap["estimates"], f"{ticker}: estimates missing {key}"
    for key in OWNERSHIP_KEYS:
        assert key in snap["ownership"], f"{ticker}: ownership missing {key}"
    assert len(snap["ownership"]["top_holders"]) == 5
    for key in SOCIAL_KEYS:
        assert key in snap["social"], f"{ticker}: social missing {key}"
    for key in MACRO_KEYS:
        assert key in snap["macro"], f"{ticker}: macro missing {key}"

    assert 5 <= len(snap["geo_revenue"]) <= 8
    for region in snap["geo_revenue"]:
        for key in ("iso_n3", "name", "revenue_share", "revenue_usd_b", "note"):
            assert key in region

    assert 4 <= len(snap["arcs"]) <= 7
    for arc in snap["arcs"]:
        for key in ("src", "dst", "label", "kind"):
            assert key in arc
        assert arc["kind"] in {"supply", "demand", "risk", "hq"}

    assert 4 <= len(snap["filings"]) <= 6
    for filing in snap["filings"]:
        for key in ("doc_type", "title", "date", "url", "snippets"):
            assert key in filing
        assert filing["url"].startswith("https://www.sec.gov/")

    assert 5 <= len(snap["peers"]) <= 6
    for p in snap["peers"]:
        for key in ("ticker", "name", "pe_fwd", "ev_ebitda", "ev_sales", "growth"):
            assert key in p


@pytest.mark.parametrize("ticker", TICKERS)
def test_geo_shares_sum_to_one(ticker):
    snap = load_fixture(ticker)
    total = sum(r["revenue_share"] for r in snap["geo_revenue"])
    assert 0.95 <= total <= 1.05, f"{ticker}: geo shares sum to {total:.3f}"


@pytest.mark.parametrize("ticker", TICKERS)
def test_price_history_shape(ticker):
    market = load_fixture(ticker)["market"]
    history = market["price_history"]
    assert 200 <= len(history) <= 260
    assert history[-1] == pytest.approx(market["last_price"], rel=0.01)
    assert min(history) >= market["week52_low"] - 0.01
    assert max(history) <= market["week52_high"] + 0.01
    # not a smooth line: daily moves must vary in sign
    ups = sum(1 for a, b in zip(history, history[1:]) if b > a)
    downs = sum(1 for a, b in zip(history, history[1:]) if b < a)
    assert ups > 20 and downs > 20, f"{ticker}: price path implausibly smooth"


@pytest.mark.parametrize("ticker", TICKERS)
def test_internal_consistency(ticker):
    snap = load_fixture(ticker)
    market = snap["market"]

    # market cap identity within +/-15%
    implied = market["last_price"] * market["shares_out_b"]
    assert market["market_cap_b"] == pytest.approx(implied, rel=0.15)

    # 52-week band brackets the last price
    assert market["week52_low"] <= market["last_price"] <= market["week52_high"]

    for fy in snap["financials"]:
        assert fy["op_margin"] == pytest.approx(fy["ebit_b"] / fy["revenue_b"], abs=0.01)
        assert fy["working_capital_b"] == pytest.approx(
            fy["current_assets_b"] - fy["current_liabilities_b"], abs=0.1
        )
        assert fy["equity_b"] == pytest.approx(
            fy["total_assets_b"] - fy["total_liabilities_b"], abs=0.1
        )
        assert fy["fcf_b"] == pytest.approx(fy["cfo_b"] - fy["capex_b"], abs=0.1)
        assert 0.0 < fy["gross_margin"] < 1.0

    # eps * implied share count roughly matches net income (latest year)
    latest = snap["financials"][-1]
    if latest["eps"]:
        implied_shares = latest["net_income_b"] / latest["eps"]
        assert implied_shares == pytest.approx(market["shares_out_b"], rel=0.20)


@pytest.mark.parametrize("ticker", TICKERS)
def test_bundle_offline(ticker):
    bundle = load_bundle(ticker, online=False)
    assert bundle["ticker"] == ticker
    assert bundle["mode_data"] == "snapshot"
    assert bundle["live_sources"] == []
    for key in TOP_LEVEL_KEYS:
        assert key in bundle


def test_bundle_unknown_ticker_raises():
    with pytest.raises(ValueError) as excinfo:
        load_bundle("ZZZZ", online=False)
    message = str(excinfo.value)
    assert "No coverage for ZZZZ" in message
    for ticker in TICKERS:
        assert ticker in message


def test_available_tickers():
    rows = available_tickers()
    assert len(rows) == 6
    assert [row["ticker"] for row in rows] == TICKERS  # sorted
    for row in rows:
        assert set(row) == {"ticker", "company", "sector"}
        assert row["company"] and row["sector"]


def test_fixture_estimates_provider():
    from delphi.data.providers.estimates import FixtureEstimates

    provider = FixtureEstimates()
    estimates = provider.fetch("NVDA")
    assert estimates is not None
    for key in ESTIMATES_KEYS:
        assert key in estimates
    assert provider.fetch("ZZZZ") is None


def test_cache_roundtrip(tmp_path):
    from delphi.data.cache import DataCache

    cache = DataCache(path=str(tmp_path / "cache.sqlite"))
    assert cache.get("NVDA", "test") is None
    cache.put("NVDA", "test", {"a": 1}, ttl_hours=24)
    assert cache.get("NVDA", "test") == {"a": 1}
    cache.put("NVDA", "expired", {"b": 2}, ttl_hours=0)
    assert cache.get("NVDA", "expired") is None
    cache.close()
