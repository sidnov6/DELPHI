"""Tests for the DELPHI deterministic finance engine."""

from __future__ import annotations

import math

import pytest

from delphi.engine import (
    altman_z,
    cash_conversion_cycle,
    comp_table,
    dcf_from_assumptions,
    dcf_value,
    dupont,
    implied_range,
    monte_carlo_dcf,
    peer_multiple_stats,
    piotroski_f,
    project_fcf,
    sensitivity_grid,
    tornado,
    wacc,
    winsorize,
)

BASE_ASSUMPTIONS: dict = {
    "revenue0": 1000.0,
    "growth_path": [0.08, 0.07, 0.06, 0.05, 0.04],
    "ebit_margin_path": [0.20, 0.21, 0.22, 0.22, 0.22],
    "tax_rate": 0.25,
    "da_pct_revenue": 0.05,
    "capex_pct_revenue": 0.06,
    "nwc_pct_revenue_delta": 0.10,
    "rf": 0.04,
    "erp": 0.05,
    "beta": 1.1,
    "cost_of_debt": 0.055,
    "debt_weight": 0.25,
    "terminal_growth": 0.025,
    "net_debt": 500.0,
    "shares_out": 100.0,
}


# ---------------------------------------------------------------- dcf


class TestWacc:
    def test_known_value(self):
        # coe = 0.04 + 1.2*0.05 = 0.10; wacc = 0.7*0.10 + 0.3*0.06*0.75 = 0.0835
        result = wacc(
            rf=0.04, erp=0.05, beta=1.2, cost_of_debt=0.06, tax_rate=0.25, debt_weight=0.30
        )
        assert result == pytest.approx(0.0835)

    def test_all_equity(self):
        assert wacc(0.03, 0.05, 1.0, 0.06, 0.21, 0.0) == pytest.approx(0.08)

    def test_invalid_debt_weight_raises(self):
        with pytest.raises(ValueError):
            wacc(0.03, 0.05, 1.0, 0.06, 0.21, 1.5)


class TestProjectFcf:
    def test_known_values(self):
        out = project_fcf(
            revenue0=1000.0,
            growth_path=[0.10, 0.10],
            ebit_margin_path=[0.20, 0.20],
            tax_rate=0.25,
            da_pct_revenue=0.05,
            capex_pct_revenue=0.06,
            nwc_pct_revenue_delta=0.10,
        )
        assert out["years"] == [1, 2]
        assert out["revenue"] == pytest.approx([1100.0, 1210.0])
        assert out["ebit"] == pytest.approx([220.0, 242.0])
        assert out["nopat"] == pytest.approx([165.0, 181.5])
        # FCF_1 = 165 + 55 - 66 - 10 = 144; FCF_2 = 181.5 + 60.5 - 72.6 - 11 = 158.4
        assert out["fcf"] == pytest.approx([144.0, 158.4])

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            project_fcf(1000.0, [0.1, 0.1], [0.2], 0.25, 0.05, 0.06, 0.1)


class TestDcfValue:
    def test_flat_fcf_no_growth_matches_perpetuity(self):
        # Flat 100 perpetuity at 10% is worth exactly 1000 (end-year convention).
        out = dcf_value(
            fcf=[100.0] * 5,
            wacc_rate=0.10,
            terminal_growth=0.0,
            exit_multiple=None,
            terminal_metric=None,
            net_debt=0.0,
            shares_out=1.0,
            mid_year=False,
        )
        assert out["ev"] == pytest.approx(1000.0)
        assert out["per_share"] == pytest.approx(1000.0)

    def test_gordon_constraint_raises(self):
        for tg in (0.10, 0.12):  # equal and above wacc both invalid
            with pytest.raises(ValueError):
                dcf_value([100.0] * 5, 0.10, tg, None, None, 0.0, 1.0)

    def test_no_terminal_method_raises(self):
        with pytest.raises(ValueError):
            dcf_value([100.0] * 5, 0.10, None, None, None, 0.0, 1.0)

    def test_exit_multiple_path(self):
        out = dcf_value(
            fcf=[100.0] * 5,
            wacc_rate=0.10,
            terminal_growth=None,
            exit_multiple=10.0,
            terminal_metric=150.0,
            net_debt=200.0,
            shares_out=50.0,
            mid_year=False,
        )
        pv_fcf = sum(100.0 / 1.10**t for t in range(1, 6))
        pv_tv = 1500.0 / 1.10**5
        assert out["pv_fcf"] == pytest.approx(pv_fcf)
        assert out["pv_terminal"] == pytest.approx(pv_tv)
        assert out["ev"] == pytest.approx(pv_fcf + pv_tv)
        assert out["equity_value"] == pytest.approx(out["ev"] - 200.0)
        assert out["per_share"] == pytest.approx(out["equity_value"] / 50.0)

    def test_tv_share_of_ev_in_unit_interval(self):
        out = dcf_from_assumptions(BASE_ASSUMPTIONS)
        assert 0.0 < out["tv_share_of_ev"] < 1.0

    def test_mid_year_exceeds_end_year(self):
        end = dcf_from_assumptions({**BASE_ASSUMPTIONS, "mid_year": False})
        mid = dcf_from_assumptions({**BASE_ASSUMPTIONS, "mid_year": True})
        assert mid["ev"] > end["ev"]
        assert mid["per_share"] > end["per_share"]


class TestDcfFromAssumptions:
    def test_pipeline_consistency(self):
        out = dcf_from_assumptions(BASE_ASSUMPTIONS)
        expected_wacc = wacc(0.04, 0.05, 1.1, 0.055, 0.25, 0.25)
        assert out["wacc"] == pytest.approx(expected_wacc)

        proj = project_fcf(1000.0, [0.08, 0.07, 0.06, 0.05, 0.04],
                           [0.20, 0.21, 0.22, 0.22, 0.22], 0.25, 0.05, 0.06, 0.10)
        assert out["fcf"] == pytest.approx(proj["fcf"])

        manual = dcf_value(proj["fcf"], expected_wacc, 0.025, None, None, 500.0, 100.0)
        assert out["per_share"] == pytest.approx(manual["per_share"])
        for key in ("ev", "pv_fcf", "pv_terminal", "tv_share_of_ev", "equity_value"):
            assert key in out

    def test_wacc_override(self):
        out = dcf_from_assumptions({**BASE_ASSUMPTIONS, "wacc": 0.09})
        assert out["wacc"] == pytest.approx(0.09)


# ---------------------------------------------------------------- comps


class TestWinsorize:
    def test_bounds_clip_at_quantiles(self):
        values = [float(v) for v in range(1, 101)]
        w = winsorize(values, p=0.05)
        assert len(w) == len(values)
        assert min(w) == pytest.approx(5.95)   # 5% quantile of 1..100
        assert max(w) == pytest.approx(95.05)  # 95% quantile
        assert w[49] == pytest.approx(50.0)    # interior values untouched

    def test_empty_and_invalid_p(self):
        assert winsorize([]) == []
        with pytest.raises(ValueError):
            winsorize([1.0, 2.0], p=0.5)


class TestPeerMultipleStats:
    def test_ignores_invalid_entries(self):
        stats = peer_multiple_stats([10.0, None, float("nan"), -5.0, 0.0, 20.0, 15.0])
        assert stats["n"] == 3
        assert stats["median"] == pytest.approx(15.0)
        assert stats["p25"] <= stats["median"] <= stats["p75"]

    def test_all_invalid(self):
        stats = peer_multiple_stats([None, float("nan"), -1.0])
        assert stats == {"p25": None, "median": None, "p75": None, "mean": None, "n": 0}


class TestImpliedRange:
    def test_ordering(self):
        out = implied_range(
            metric_value=100.0,
            multiples=[8.0, 10.0, 12.0, 14.0, 16.0],
            net_debt=200.0,
            shares_out=50.0,
            is_enterprise=True,
        )
        assert out["low"] < out["mid"] < out["high"]

    def test_equity_multiple_ignores_net_debt(self):
        out = implied_range(5.0, [10.0, 12.0, 14.0], net_debt=999.0, shares_out=1.0)
        assert out["mid"] == pytest.approx(60.0)  # median 12 * EPS 5

    def test_no_valid_multiples_raises(self):
        with pytest.raises(ValueError):
            implied_range(100.0, [None, -1.0])


class TestCompTable:
    def test_median_row_appended(self):
        peers = [
            {"ticker": "AAA", "name": "Alpha", "pe_fwd": 10.0, "ev_ebitda": 8.0,
             "ev_sales": 2.0, "growth": 0.05},
            {"ticker": "BBB", "name": "Beta", "pe_fwd": 20.0, "ev_ebitda": None,
             "ev_sales": 3.0, "growth": 0.10},
            {"ticker": "CCC", "name": "Gamma", "pe_fwd": 30.0, "ev_ebitda": 12.0,
             "ev_sales": 4.0, "growth": 0.15},
        ]
        rows = comp_table(peers)
        assert len(rows) == 4
        median = rows[-1]
        assert median["ticker"] == "MEDIAN"
        assert median["pe_fwd"] == pytest.approx(20.0)
        assert median["ev_ebitda"] == pytest.approx(10.0)  # None ignored
        assert median["growth"] == pytest.approx(0.10)
        assert peers[1]["ticker"] == "BBB"  # inputs not mutated


# ---------------------------------------------------------------- ratios


class TestDupont:
    def test_components_multiply_to_roe(self):
        out = dupont(net_income=120.0, revenue=1000.0, avg_assets=2000.0, avg_equity=800.0)
        assert out["net_margin"] == pytest.approx(0.12)
        assert out["asset_turnover"] == pytest.approx(0.5)
        assert out["leverage"] == pytest.approx(2.5)
        product = out["net_margin"] * out["asset_turnover"] * out["leverage"]
        assert out["roe"] == pytest.approx(product)
        assert out["roe"] == pytest.approx(120.0 / 800.0)


class TestAltmanZ:
    def test_safe_zone(self):
        out = altman_z(20.0, 30.0, 15.0, 80.0, 40.0, 110.0, 100.0)
        assert out["z"] == pytest.approx(3.455)
        assert out["zone"] == "safe"

    def test_grey_zone(self):
        out = altman_z(10.0, 10.0, 8.0, 50.0, 50.0, 90.0, 100.0)
        assert 1.81 <= out["z"] < 2.99
        assert out["zone"] == "grey"

    def test_distress_zone(self):
        out = altman_z(-10.0, -20.0, -5.0, 10.0, 90.0, 50.0, 100.0)
        assert out["z"] < 1.81
        assert out["zone"] == "distress"


class TestPiotroski:
    def test_perfect_nine(self):
        prev = {"net_income": 50.0, "cfo": 60.0, "total_assets": 1000.0,
                "long_term_debt": 300.0, "current_assets": 400.0,
                "current_liabilities": 250.0, "shares_out": 100.0,
                "gross_margin": 0.40, "revenue": 900.0}
        curr = {"net_income": 80.0, "cfo": 120.0, "total_assets": 1000.0,
                "long_term_debt": 250.0, "current_assets": 500.0,
                "current_liabilities": 250.0, "shares_out": 100.0,
                "gross_margin": 0.45, "revenue": 1000.0}
        out = piotroski_f(curr, prev)
        assert out["score"] == 9
        assert all(out["signals"].values())
        assert len(out["signals"]) == 9

    def test_zero_score(self):
        prev = {"net_income": 80.0, "cfo": 120.0, "total_assets": 1000.0,
                "long_term_debt": 200.0, "current_assets": 500.0,
                "current_liabilities": 250.0, "shares_out": 100.0,
                "gross_margin": 0.45, "revenue": 1000.0}
        curr = {"net_income": -50.0, "cfo": -60.0, "total_assets": 1000.0,
                "long_term_debt": 300.0, "current_assets": 400.0,
                "current_liabilities": 250.0, "shares_out": 120.0,
                "gross_margin": 0.40, "revenue": 800.0}
        out = piotroski_f(curr, prev)
        assert out["score"] == 0
        assert not any(out["signals"].values())


def test_cash_conversion_cycle():
    assert cash_conversion_cycle(45.0, 60.0, 30.0) == pytest.approx(75.0)
    assert cash_conversion_cycle(30.0, 20.0, 60.0) == pytest.approx(-10.0)


# ---------------------------------------------------------------- scenarios


class TestSensitivityGrid:
    def test_shape_and_monotonicity(self):
        grid = sensitivity_grid(
            BASE_ASSUMPTIONS,
            row_key="wacc", row_values=[0.07, 0.08, 0.09],
            col_key="terminal_growth", col_values=[0.02, 0.025],
        )
        assert grid["rows"] == [0.07, 0.08, 0.09]
        assert grid["cols"] == [0.02, 0.025]
        assert len(grid["cells"]) == 6
        by_cell = {(c["row"], c["col"]): c["value"] for c in grid["cells"]}
        # Lower discount rate -> higher value, holding terminal growth fixed.
        for tg in (0.02, 0.025):
            assert by_cell[(0.07, tg)] > by_cell[(0.08, tg)] > by_cell[(0.09, tg)]
        # Higher terminal growth -> higher value, holding wacc fixed.
        assert by_cell[(0.08, 0.025)] > by_cell[(0.08, 0.02)]

    def test_gordon_violation_yields_none(self):
        grid = sensitivity_grid(
            BASE_ASSUMPTIONS,
            row_key="wacc", row_values=[0.08, 0.10],
            col_key="terminal_growth", col_values=[0.02, 0.10],
        )
        by_cell = {(c["row"], c["col"]): c["value"] for c in grid["cells"]}
        assert by_cell[(0.08, 0.02)] is not None
        assert by_cell[(0.08, 0.10)] is None   # tg > wacc
        assert by_cell[(0.10, 0.10)] is None   # tg == wacc
        assert by_cell[(0.10, 0.02)] is not None


class TestTornado:
    def test_sorted_by_impact_with_path_deltas(self):
        variables = {
            "terminal_growth": (0.015, 0.035),
            "beta": (0.9, 1.3),
            "ebit_margin_path": (-0.02, 0.02),
            "growth_path": (-0.02, 0.02),
            "tax_rate": (0.22, 0.28),
        }
        rows = tornado(BASE_ASSUMPTIONS, variables)
        assert {r["variable"] for r in rows} == set(variables)
        impacts = [abs(r["high_value"] - r["low_value"]) for r in rows]
        assert impacts == sorted(impacts, reverse=True)
        base = dcf_from_assumptions(BASE_ASSUMPTIONS)["per_share"]
        for r in rows:
            assert r["base_value"] == pytest.approx(base)
        # Additive path delta: higher margins must lift value above base.
        margin_row = next(r for r in rows if r["variable"] == "ebit_margin_path")
        assert margin_row["low_value"] < base < margin_row["high_value"]


class TestMonteCarlo:
    def test_deterministic_and_distribution_shape(self):
        kwargs = dict(n=400, seed=7, last_price=20.0)
        a = monte_carlo_dcf(BASE_ASSUMPTIONS, **kwargs)
        b = monte_carlo_dcf(BASE_ASSUMPTIONS, **kwargs)
        assert a == b  # same seed -> identical output

        s = a["per_share_draws_summary"]
        assert s["p5"] < s["p25"] < s["p50"] < s["p75"] < s["p95"]
        assert math.isfinite(s["mean"])

        hist = a["draws_histogram"]
        assert len(hist["bin_edges"]) == 21
        assert len(hist["counts"]) == 20
        assert sum(hist["counts"]) == 400

        assert a["draws_stats"]["n"] == 400
        assert a["draws_stats"]["min"] <= s["p5"]
        assert a["draws_stats"]["max"] >= s["p95"]
        assert 0.0 <= a["prob_upside"] <= 1.0

    def test_no_last_price_omits_prob_upside(self):
        out = monte_carlo_dcf(BASE_ASSUMPTIONS, n=50, seed=1)
        assert "prob_upside" not in out

    def test_different_seeds_differ(self):
        a = monte_carlo_dcf(BASE_ASSUMPTIONS, n=200, seed=1)
        b = monte_carlo_dcf(BASE_ASSUMPTIONS, n=200, seed=2)
        assert a["per_share_draws_summary"] != b["per_share_draws_summary"]
