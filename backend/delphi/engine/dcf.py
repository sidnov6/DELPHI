"""Discounted cash flow valuation: WACC, FCF projection, and DCF value.

Pure, deterministic functions. No I/O, no randomness, no external state.
"""

from __future__ import annotations


def wacc(
    rf: float,
    erp: float,
    beta: float,
    cost_of_debt: float,
    tax_rate: float,
    debt_weight: float,
) -> float:
    """Weighted average cost of capital using CAPM for the cost of equity.

    Cost of equity = rf + beta * erp. Debt is tax-shielded:
    WACC = we * coe + wd * cod * (1 - tax_rate), where we = 1 - debt_weight.

    Args:
        rf: Risk-free rate (decimal, e.g. 0.04).
        erp: Equity risk premium (decimal).
        beta: Levered equity beta.
        cost_of_debt: Pre-tax cost of debt (decimal).
        tax_rate: Marginal tax rate (decimal).
        debt_weight: Debt share of total capital, in [0, 1].

    Returns:
        WACC as a decimal.

    Raises:
        ValueError: If debt_weight is outside [0, 1].
    """
    if not 0.0 <= debt_weight <= 1.0:
        raise ValueError(f"debt_weight must be in [0, 1], got {debt_weight}")
    cost_of_equity = rf + beta * erp
    equity_weight = 1.0 - debt_weight
    return equity_weight * cost_of_equity + debt_weight * cost_of_debt * (1.0 - tax_rate)


def project_fcf(
    revenue0: float,
    growth_path: list[float],
    ebit_margin_path: list[float],
    tax_rate: float,
    da_pct_revenue: float,
    capex_pct_revenue: float | list[float],
    nwc_pct_revenue_delta: float,
) -> dict:
    """Project unlevered free cash flow over an explicit forecast horizon.

    Per year t: revenue_t = revenue_{t-1} * (1 + g_t); EBIT = revenue * margin;
    NOPAT = EBIT * (1 - tax); FCF = NOPAT + D&A - capex - dNWC, where
    dNWC = nwc_pct_revenue_delta * (revenue_t - revenue_{t-1}).

    Args:
        revenue0: Trailing (year 0) revenue.
        growth_path: Year-over-year revenue growth rates, one per forecast year.
        ebit_margin_path: EBIT margins, one per forecast year (same length).
        tax_rate: Tax rate applied to EBIT.
        da_pct_revenue: D&A as a fraction of revenue.
        capex_pct_revenue: Capex as a fraction of revenue — a scalar, or one
            value per forecast year (lets a capex supercycle normalize toward
            maintenance levels by the terminal year instead of compounding
            peak investment into perpetuity).
        nwc_pct_revenue_delta: Incremental NWC as a fraction of the revenue change.

    Returns:
        {"years": [1..n], "revenue": [...], "ebit": [...], "nopat": [...], "fcf": [...]}.

    Raises:
        ValueError: If growth_path and ebit_margin_path lengths differ or are empty.
    """
    if len(growth_path) != len(ebit_margin_path):
        raise ValueError(
            f"growth_path (n={len(growth_path)}) and ebit_margin_path "
            f"(n={len(ebit_margin_path)}) must have equal length"
        )
    if not growth_path:
        raise ValueError("growth_path must contain at least one year")
    if isinstance(capex_pct_revenue, (int, float)):
        capex_path = [float(capex_pct_revenue)] * len(growth_path)
    else:
        capex_path = list(capex_pct_revenue)
        if len(capex_path) != len(growth_path):
            raise ValueError(
                f"capex_pct_revenue list (n={len(capex_path)}) must match "
                f"growth_path (n={len(growth_path)})"
            )

    years: list[int] = []
    revenue: list[float] = []
    ebit: list[float] = []
    nopat: list[float] = []
    fcf: list[float] = []

    prev_revenue = revenue0
    for t, (g, margin) in enumerate(zip(growth_path, ebit_margin_path), start=1):
        rev_t = prev_revenue * (1.0 + g)
        ebit_t = rev_t * margin
        nopat_t = ebit_t * (1.0 - tax_rate)
        da_t = rev_t * da_pct_revenue
        capex_t = rev_t * capex_path[t - 1]
        delta_nwc_t = nwc_pct_revenue_delta * (rev_t - prev_revenue)
        fcf_t = nopat_t + da_t - capex_t - delta_nwc_t

        years.append(t)
        revenue.append(rev_t)
        ebit.append(ebit_t)
        nopat.append(nopat_t)
        fcf.append(fcf_t)
        prev_revenue = rev_t

    return {"years": years, "revenue": revenue, "ebit": ebit, "nopat": nopat, "fcf": fcf}


def dcf_value(
    fcf: list[float],
    wacc_rate: float,
    terminal_growth: float | None,
    exit_multiple: float | None,
    terminal_metric: float | None,
    net_debt: float,
    shares_out: float,
    mid_year: bool = True,
) -> dict:
    """Discount projected FCF plus a terminal value to enterprise and equity value.

    Terminal value: Gordon growth when terminal_growth is provided
    (TV = FCF_n * (1 + g) / (wacc - g), requires g < wacc), otherwise
    exit_multiple * terminal_metric. The mid-year convention discounts cash
    flows at t - 0.5 to reflect intra-year receipt; the terminal value is
    discounted at the same horizon-end factor as the final year's FCF.

    Args:
        fcf: Explicit-period free cash flows (years 1..n).
        wacc_rate: Discount rate (decimal).
        terminal_growth: Perpetuity growth rate, or None to use the exit multiple.
        exit_multiple: EV multiple applied to terminal_metric (used if growth is None).
        terminal_metric: Terminal-year metric (e.g. EBITDA) for the exit multiple.
        net_debt: Net debt subtracted from EV to get equity value.
        shares_out: Diluted shares outstanding.
        mid_year: Use mid-year discounting convention.

    Returns:
        {"ev", "pv_fcf", "pv_terminal", "tv_share_of_ev", "equity_value", "per_share"}.

    Raises:
        ValueError: If fcf is empty, no terminal method is specified, or
            terminal_growth >= wacc_rate.
    """
    if not fcf:
        raise ValueError("fcf must contain at least one year")
    if shares_out <= 0:
        raise ValueError(f"shares_out must be positive, got {shares_out}")

    n = len(fcf)
    offset = 0.5 if mid_year else 0.0
    pv_fcf = sum(cf / (1.0 + wacc_rate) ** (t - offset) for t, cf in enumerate(fcf, start=1))

    if terminal_growth is not None:
        if terminal_growth >= wacc_rate:
            raise ValueError(
                f"terminal_growth ({terminal_growth}) must be below wacc ({wacc_rate})"
            )
        terminal_value = fcf[-1] * (1.0 + terminal_growth) / (wacc_rate - terminal_growth)
    elif exit_multiple is not None and terminal_metric is not None:
        terminal_value = exit_multiple * terminal_metric
    else:
        raise ValueError(
            "specify terminal_growth, or both exit_multiple and terminal_metric"
        )

    pv_terminal = terminal_value / (1.0 + wacc_rate) ** (n - offset)
    ev = pv_fcf + pv_terminal
    equity_value = ev - net_debt
    return {
        "ev": ev,
        "pv_fcf": pv_fcf,
        "pv_terminal": pv_terminal,
        "tv_share_of_ev": pv_terminal / ev if ev != 0.0 else float("nan"),
        "equity_value": equity_value,
        "per_share": equity_value / shares_out,
    }


def dcf_from_assumptions(a: dict) -> dict:
    """Run the full DCF pipeline (wacc -> project_fcf -> dcf_value) from one dict.

    Required keys: revenue0, growth_path, ebit_margin_path, tax_rate,
    da_pct_revenue, capex_pct_revenue, nwc_pct_revenue_delta, rf, erp, beta,
    cost_of_debt, debt_weight, terminal_growth, net_debt, shares_out.
    Optional: exit_multiple / terminal_metric (used when terminal_growth is
    None), wacc (overrides the CAPM-derived rate), mid_year (default True).

    Args:
        a: Assumption dict as described above.

    Returns:
        dcf_value output merged with {"wacc": float, "fcf": list[float]}.
    """
    wacc_rate = (
        float(a["wacc"])
        if a.get("wacc") is not None
        else wacc(
            rf=a["rf"],
            erp=a["erp"],
            beta=a["beta"],
            cost_of_debt=a["cost_of_debt"],
            tax_rate=a["tax_rate"],
            debt_weight=a["debt_weight"],
        )
    )
    projection = project_fcf(
        revenue0=a["revenue0"],
        growth_path=list(a["growth_path"]),
        ebit_margin_path=list(a["ebit_margin_path"]),
        tax_rate=a["tax_rate"],
        da_pct_revenue=a["da_pct_revenue"],
        capex_pct_revenue=a["capex_pct_revenue"],
        nwc_pct_revenue_delta=a["nwc_pct_revenue_delta"],
    )
    valuation = dcf_value(
        fcf=projection["fcf"],
        wacc_rate=wacc_rate,
        terminal_growth=a.get("terminal_growth"),
        exit_multiple=a.get("exit_multiple"),
        terminal_metric=a.get("terminal_metric"),
        net_debt=a["net_debt"],
        shares_out=a["shares_out"],
        mid_year=bool(a.get("mid_year", True)),
    )
    return {**valuation, "wacc": wacc_rate, "fcf": projection["fcf"]}
