"""Fundamental ratio analysis: DuPont, Altman Z, Piotroski F, cash cycle.

Pure, deterministic functions. No I/O, no randomness, no external state.
"""

from __future__ import annotations


def dupont(
    net_income: float,
    revenue: float,
    avg_assets: float,
    avg_equity: float,
) -> dict:
    """Three-factor DuPont decomposition of return on equity.

    ROE = net margin * asset turnover * equity multiplier (leverage).

    Args:
        net_income: Net income for the period.
        revenue: Revenue for the period.
        avg_assets: Average total assets.
        avg_equity: Average shareholders' equity.

    Returns:
        {"net_margin", "asset_turnover", "leverage", "roe"}.

    Raises:
        ValueError: If revenue, avg_assets, or avg_equity is zero.
    """
    if revenue == 0 or avg_assets == 0 or avg_equity == 0:
        raise ValueError("revenue, avg_assets, and avg_equity must be non-zero")
    net_margin = net_income / revenue
    asset_turnover = revenue / avg_assets
    leverage = avg_assets / avg_equity
    return {
        "net_margin": net_margin,
        "asset_turnover": asset_turnover,
        "leverage": leverage,
        "roe": net_margin * asset_turnover * leverage,
    }


def altman_z(
    working_capital: float,
    retained_earnings: float,
    ebit: float,
    market_cap: float,
    total_liabilities: float,
    revenue: float,
    total_assets: float,
) -> dict:
    """Altman Z-score (original 1968 public-manufacturer model).

    Z = 1.2*WC/TA + 1.4*RE/TA + 3.3*EBIT/TA + 0.6*MktCap/TL + 1.0*Rev/TA.
    Zones: distress < 1.81 <= grey < 2.99 <= safe.

    Args:
        working_capital: Current assets minus current liabilities.
        retained_earnings: Balance-sheet retained earnings.
        ebit: Earnings before interest and taxes.
        market_cap: Market value of equity.
        total_liabilities: Total liabilities.
        revenue: Total revenue.
        total_assets: Total assets.

    Returns:
        {"z": float, "zone": "distress" | "grey" | "safe"}.

    Raises:
        ValueError: If total_assets or total_liabilities is non-positive.
    """
    if total_assets <= 0:
        raise ValueError(f"total_assets must be positive, got {total_assets}")
    if total_liabilities <= 0:
        raise ValueError(f"total_liabilities must be positive, got {total_liabilities}")
    z = (
        1.2 * working_capital / total_assets
        + 1.4 * retained_earnings / total_assets
        + 3.3 * ebit / total_assets
        + 0.6 * market_cap / total_liabilities
        + 1.0 * revenue / total_assets
    )
    zone = "distress" if z < 1.81 else "grey" if z < 2.99 else "safe"
    return {"z": z, "zone": zone}


def piotroski_f(curr: dict, prev: dict) -> dict:
    """Piotroski F-score: nine binary fundamentals signals (0-9).

    Each period dict needs: net_income, cfo, total_assets, long_term_debt,
    current_assets, current_liabilities, shares_out, gross_margin, revenue.

    Signals — profitability: positive net income, positive CFO, ROA improved,
    CFO > net income (accrual quality); leverage/liquidity: lower LTD/assets,
    higher current ratio, no share dilution; efficiency: higher gross margin,
    higher asset turnover.

    Args:
        curr: Current-period fundamentals.
        prev: Prior-period fundamentals.

    Returns:
        {"score": int 0-9, "signals": {signal_name: bool}}.
    """
    roa_curr = curr["net_income"] / curr["total_assets"]
    roa_prev = prev["net_income"] / prev["total_assets"]
    signals = {
        "positive_net_income": curr["net_income"] > 0,
        "positive_cfo": curr["cfo"] > 0,
        "roa_improved": roa_curr > roa_prev,
        "cfo_exceeds_net_income": curr["cfo"] > curr["net_income"],
        "lower_leverage": (
            curr["long_term_debt"] / curr["total_assets"]
            < prev["long_term_debt"] / prev["total_assets"]
        ),
        "higher_current_ratio": (
            curr["current_assets"] / curr["current_liabilities"]
            > prev["current_assets"] / prev["current_liabilities"]
        ),
        "no_dilution": curr["shares_out"] <= prev["shares_out"],
        "higher_gross_margin": curr["gross_margin"] > prev["gross_margin"],
        "higher_asset_turnover": (
            curr["revenue"] / curr["total_assets"]
            > prev["revenue"] / prev["total_assets"]
        ),
    }
    return {"score": sum(signals.values()), "signals": signals}


def cash_conversion_cycle(dso: float, dio: float, dpo: float) -> float:
    """Cash conversion cycle in days: DSO + DIO - DPO.

    Args:
        dso: Days sales outstanding.
        dio: Days inventory outstanding.
        dpo: Days payables outstanding.

    Returns:
        Cash conversion cycle in days.
    """
    return dso + dio - dpo
