"""Offline tests for the dynamic bundle builder. No network calls — only
the pure helpers and static tables that the live path depends on."""

import pytest

from delphi.data.builder import (
    COUNTRY_CENTROIDS,
    COUNTRY_ISO_N3,
    DEFAULT_SECTOR,
    SECTOR_COMPS,
    CoverageError,
    convert_financials,
    normalize_quote,
)

MAJOR_EUROPEAN = [
    "United Kingdom", "Germany", "France", "Netherlands", "Switzerland",
    "Sweden", "Denmark", "Norway", "Finland", "Italy", "Spain", "Portugal",
    "Belgium", "Austria", "Ireland", "Poland", "Greece", "Czechia",
    "Hungary", "Luxembourg",
]

SECTORS = [
    "Technology", "Semiconductors", "Communication Services",
    "Consumer Cyclical", "Consumer Defensive", "Healthcare",
    "Financial Services", "Industrials", "Energy", "Utilities",
    "Real Estate", "Basic Materials",
]


# ------------------------------------------------------------ country maps

def test_iso_map_covers_at_least_30_countries():
    assert len(COUNTRY_ISO_N3) >= 30


@pytest.mark.parametrize("country", MAJOR_EUROPEAN)
def test_iso_map_covers_major_european_countries(country):
    assert country in COUNTRY_ISO_N3


@pytest.mark.parametrize("country", ["United States", "China", "Japan",
                                     "South Korea", "Taiwan", "India",
                                     "Brazil", "Canada", "Australia", "Singapore"])
def test_iso_map_covers_rest_of_world_domiciles(country):
    assert country in COUNTRY_ISO_N3


def test_iso_codes_are_three_digit_strings():
    for country, code in COUNTRY_ISO_N3.items():
        assert isinstance(code, str) and len(code) == 3 and code.isdigit(), (
            f"{country}: bad ISO numeric {code!r}")
    assert COUNTRY_ISO_N3["United States"] == "840"
    assert COUNTRY_ISO_N3["United Kingdom"] == "826"
    assert COUNTRY_ISO_N3["Germany"] == "276"


def test_every_iso_country_has_a_centroid():
    missing = set(COUNTRY_ISO_N3) - set(COUNTRY_CENTROIDS)
    assert not missing, f"countries without HQ centroid: {missing}"


def test_centroids_are_lon_lat_pairs_in_range():
    for country, (lon, lat) in COUNTRY_CENTROIDS.items():
        assert -180 <= lon <= 180, f"{country}: lon {lon}"
        assert -90 <= lat <= 90, f"{country}: lat {lat}"
    assert COUNTRY_CENTROIDS["United States"] == [-98.5, 39.8]


# ------------------------------------------------------------ sector comps

def test_sector_comps_table_complete():
    assert set(SECTOR_COMPS) == set(SECTORS)
    assert DEFAULT_SECTOR in SECTOR_COMPS


@pytest.mark.parametrize("sector", SECTORS)
def test_sector_comps_values_sane(sector):
    peers = SECTOR_COMPS[sector]
    assert len(peers) == 4
    for peer in peers:
        assert set(peer) == {"ticker", "name", "pe_fwd", "ev_ebitda",
                             "ev_sales", "growth"}
        assert peer["ticker"].endswith(("-REF-1", "-REF-2", "-REF-3", "-REF-4"))
        assert 5.0 <= peer["pe_fwd"] <= 60.0
        assert 0.5 <= peer["ev_ebitda"] <= 40.0
        assert 0.1 <= peer["ev_sales"] <= 20.0
        assert -0.10 <= peer["growth"] <= 0.60
    # quartile points should be ordered
    pes = [p["pe_fwd"] for p in peers]
    assert pes == sorted(pes)


# ----------------------------------------------------- GBp normalization

def test_normalize_quote_gbp_pence():
    price, cur = normalize_quote(3239.0, "GBp")
    assert cur == "GBP"
    assert price == pytest.approx(32.39)


def test_normalize_quote_gbx_alias():
    price, cur = normalize_quote(150.0, "GBX")
    assert (price, cur) == (1.5, "GBP")


def test_normalize_quote_passthrough():
    assert normalize_quote(204.57, "USD") == (204.57, "USD")
    assert normalize_quote(149.7, "EUR") == (149.7, "EUR")
    assert normalize_quote(79.73, "CHF") == (79.73, "CHF")


def test_normalize_quote_none_tolerant():
    price, cur = normalize_quote(None, "GBp")
    assert price is None and cur == "GBP"
    assert normalize_quote(10.0, None) == (10.0, "USD")


# ------------------------------------------------------- fx conversion

def test_convert_financials_scales_currency_keys():
    year = {
        "year": "FY2025",
        "revenue_b": 100.0,
        "gross_margin": 0.5,
        "ebit_b": 20.0,
        "op_margin": 0.2,
        "net_income_b": 15.0,
        "eps": 2.0,
        "fcf_b": 12.0,
        "da_b": 5.0,
        "capex_b": 6.0,
        "cfo_b": 18.0,
        "total_assets_b": 200.0,
        "total_liabilities_b": 120.0,
        "current_assets_b": 60.0,
        "current_liabilities_b": 40.0,
        "long_term_debt_b": 50.0,
        "equity_b": 80.0,
        "retained_earnings_b": 48.0,
        "working_capital_b": 20.0,
        "rd_b": 10.0,
    }
    out = convert_financials(year, 0.75)
    # currency-denominated values scale...
    assert out["revenue_b"] == pytest.approx(75.0)
    assert out["ebit_b"] == pytest.approx(15.0)
    assert out["eps"] == pytest.approx(1.5)
    assert out["working_capital_b"] == pytest.approx(15.0)
    assert out["total_assets_b"] == pytest.approx(150.0)
    # ...ratios and labels do not
    assert out["year"] == "FY2025"
    assert out["gross_margin"] == 0.5
    assert out["op_margin"] == 0.2


def test_convert_financials_is_pure_and_none_tolerant():
    year = {"year": "FY2024", "revenue_b": 10.0, "eps": None, "op_margin": 0.1}
    out = convert_financials(year, 2.0)
    assert year["revenue_b"] == 10.0  # input untouched
    assert out["revenue_b"] == 20.0
    assert out["eps"] is None
    assert out["op_margin"] == 0.1


def test_coverage_error_is_value_error():
    assert issubclass(CoverageError, ValueError)
    err = CoverageError("insufficient financial history")
    assert "insufficient" in str(err)
