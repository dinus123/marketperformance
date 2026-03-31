"""
perf_engine.py — All performance calculations.
Pure Python/pandas/numpy/scipy — no Flask imports.
Annualisation: ×252 only. No ×365, no ×12.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from config import TRADING_DAYS

# ── Basic building blocks ──────────────────────────────────────────────────────

def returns_from_prices(prices: pd.Series) -> pd.Series:
    """Daily simple returns from price series."""
    return prices.pct_change().dropna()


def cum_return_indexed(returns: pd.Series, base: float = 100.0) -> pd.Series:
    """Cumulative return series rebased to `base` at first observation."""
    return base * (1 + returns).cumprod()


def rebase_to_window(prices: pd.Series, start_date: str) -> pd.Series:
    """
    Slice prices to [start_date, end] and rebase so first value = 100.
    Returns rebased price series.
    """
    sub = prices.loc[prices.index >= pd.Timestamp(start_date)]
    if sub.empty:
        return sub
    return sub / sub.iloc[0] * 100.0


# ── Return windows ─────────────────────────────────────────────────────────────

def _window_start(prices: pd.Series, window: str) -> pd.Timestamp | None:
    """Resolve window string to start date given the price series end date."""
    if prices.empty:
        return None
    end = prices.index[-1]
    today = pd.Timestamp.today().normalize()

    if window == "1M":
        return end - pd.DateOffset(months=1)
    elif window == "3M":
        return end - pd.DateOffset(months=3)
    elif window == "6M":
        return end - pd.DateOffset(months=6)
    elif window == "YTD":
        return pd.Timestamp(f"{end.year}-01-01")
    elif window == "1Y":
        return end - pd.DateOffset(years=1)
    elif window == "3Y":
        return end - pd.DateOffset(years=3)
    elif window == "5Y":
        return end - pd.DateOffset(years=5)
    elif window == "All":
        return prices.index[0]
    return None


def period_return(prices: pd.Series, window: str) -> float | None:
    """
    Cumulative return over the given window.
    window: '1M' | '3M' | '6M' | 'YTD' | '1Y' | '3Y' | '5Y' | 'All'
    Returns float (e.g. 0.123 = 12.3%) or None if insufficient data.
    """
    if prices is None or prices.empty:
        return None
    start = _window_start(prices, window)
    if start is None:
        return None
    sub = prices.loc[prices.index >= start]
    if len(sub) < 2:
        return None
    return float(sub.iloc[-1] / sub.iloc[0] - 1)


# ── Annualised statistics ──────────────────────────────────────────────────────

def cagr(returns: pd.Series) -> float:
    """Compound annual growth rate. Annualised ×252."""
    if returns.empty:
        return 0.0
    return float((1 + returns).prod() ** (TRADING_DAYS / len(returns)) - 1)


def vol(returns: pd.Series) -> float:
    """Annualised volatility ×√252."""
    if len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(TRADING_DAYS))


def sharpe(returns: pd.Series, rf_daily: float = 0.0) -> float:
    """Annualised Sharpe ratio."""
    excess = returns - rf_daily
    if excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(TRADING_DAYS))


def sharpe_ci(
    returns: pd.Series, rf_daily: float = 0.0, z: float = 1.96
) -> tuple[float, float, float]:
    """
    Lo (2002) Sharpe ratio with 95% CI.
    Returns (sharpe_ann, lo_95, hi_95).
    se = sqrt((1 + 0.5*SR_d^2) / n) * sqrt(252)
    """
    excess = returns - rf_daily
    n = len(excess)
    if n < 2 or excess.std() == 0:
        return 0.0, 0.0, 0.0
    sr_d = excess.mean() / excess.std()
    se = np.sqrt((1 + 0.5 * sr_d**2) / n) * np.sqrt(TRADING_DAYS)
    sr_ann = float(sr_d * np.sqrt(TRADING_DAYS))
    return sr_ann, float(sr_ann - z * se), float(sr_ann + z * se)


def sortino(returns: pd.Series, rf_daily: float = 0.0) -> float:
    """Sortino ratio: CAGR / downside vol (semi-deviation annualised)."""
    excess = returns - rf_daily
    downside = excess[excess < 0]
    if len(downside) < 2:
        return 0.0
    downside_vol = downside.std() * np.sqrt(TRADING_DAYS)
    if downside_vol == 0:
        return 0.0
    return float(cagr(returns) / downside_vol)


def max_drawdown(prices: pd.Series) -> float:
    """Maximum drawdown (negative float, e.g. -0.275 = -27.5%)."""
    if prices.empty:
        return 0.0
    peak = prices.cummax()
    dd = (prices - peak) / peak
    return float(dd.min())


def calmar(returns: pd.Series, prices: pd.Series) -> float:
    """Calmar ratio: CAGR / abs(max drawdown)."""
    mdd = abs(max_drawdown(prices))
    if mdd == 0:
        return 0.0
    return float(cagr(returns) / mdd)


def skew(returns: pd.Series) -> float:
    """Return skewness (Fisher)."""
    if len(returns) < 4:
        return 0.0
    return float(sp_stats.skew(returns.dropna()))


def kurt(returns: pd.Series) -> float:
    """Excess kurtosis (Fisher definition)."""
    if len(returns) < 4:
        return 0.0
    return float(sp_stats.kurtosis(returns.dropna()))


# ── Full stats dict ────────────────────────────────────────────────────────────

def calc_stats(prices: pd.Series, rf_daily: float = 0.0) -> dict:
    """
    Full stat block for a price series.
    Returns dict with: cagr, vol, sharpe, sharpe_lo, sharpe_hi,
                       sortino, max_dd, calmar, skew, kurt, n_obs
    All floats. None for series with < MIN_OBS observations.
    """
    MIN_OBS = 20
    if prices is None or len(prices) < MIN_OBS:
        return _empty_stats()

    r = returns_from_prices(prices)
    sr, sr_lo, sr_hi = sharpe_ci(r, rf_daily)

    return {
        "cagr":      cagr(r),
        "vol":       vol(r),
        "sharpe":    sr,
        "sharpe_lo": sr_lo,
        "sharpe_hi": sr_hi,
        "sortino":   sortino(r, rf_daily),
        "max_dd":    max_drawdown(prices),
        "calmar":    calmar(r, prices),
        "skew":      skew(r),
        "kurt":      kurt(r),
        "n_obs":     len(r),
    }


def _empty_stats() -> dict:
    keys = ["cagr", "vol", "sharpe", "sharpe_lo", "sharpe_hi",
            "sortino", "max_dd", "calmar", "skew", "kurt", "n_obs"]
    return {k: None for k in keys}


# ── Calendar returns ───────────────────────────────────────────────────────────

def calc_calendar(prices: pd.Series) -> dict:
    """
    Monthly and annual return heatmap data.
    Returns: {year_int: {1..12: pct_float, 'ann': pct_float}}
    Incomplete current year labeled with month dict only (ann = YTD).
    """
    if prices is None or prices.empty:
        return {}

    r = returns_from_prices(prices)
    r.index = pd.to_datetime(r.index)

    result: dict = {}
    for year, year_data in r.groupby(r.index.year):
        year_dict: dict = {}
        for month, month_data in year_data.groupby(year_data.index.month):
            year_dict[str(int(month))] = float((1 + month_data).prod() - 1)
        year_dict["ann"] = float((1 + year_data).prod() - 1)
        result[str(int(year))] = year_dict

    return result


# ── Drawdown series ────────────────────────────────────────────────────────────

def drawdown_series(prices: pd.Series) -> pd.Series:
    """Returns daily drawdown series (0 to negative float)."""
    if prices.empty:
        return prices
    peak = prices.cummax()
    return (prices - peak) / peak


# ── Benchmark-relative metrics ─────────────────────────────────────────────────

def _align(fund_r: pd.Series, bench_r: pd.Series) -> pd.DataFrame:
    """Inner-join on dates; drop NaN rows."""
    return pd.DataFrame({"f": fund_r, "b": bench_r}).dropna()


def alpha_beta(fund_r: pd.Series, bench_r: pd.Series) -> tuple[float, float]:
    """
    Jensen alpha (annualised) and beta via OLS.
    Returns (alpha_ann, beta).
    """
    df = _align(fund_r, bench_r)
    if len(df) < 20:
        return 0.0, 0.0
    b_var = df["b"].var()
    if b_var == 0:
        return 0.0, 0.0
    beta = float(df.cov()["f"]["b"] / b_var)
    alpha_daily = float(df["f"].mean() - beta * df["b"].mean())
    return alpha_daily * TRADING_DAYS, beta


def tracking_error(fund_r: pd.Series, bench_r: pd.Series) -> float:
    """Annualised tracking error."""
    df = _align(fund_r, bench_r)
    if len(df) < 2:
        return 0.0
    return float((df["f"] - df["b"]).std() * np.sqrt(TRADING_DAYS))


def info_ratio(fund_r: pd.Series, bench_r: pd.Series) -> float:
    """Information ratio: annualised active return / annualised TE."""
    df = _align(fund_r, bench_r)
    if len(df) < 2:
        return 0.0
    active = df["f"] - df["b"]
    te = active.std() * np.sqrt(TRADING_DAYS)
    if te == 0:
        return 0.0
    ann_active = active.mean() * TRADING_DAYS
    return float(ann_active / te)


def up_down_capture(
    fund_r: pd.Series, bench_r: pd.Series
) -> tuple[float | None, float | None]:
    """Up-capture and down-capture ratios."""
    df = _align(fund_r, bench_r)
    up = df[df["b"] > 0]
    dn = df[df["b"] < 0]
    up_cap = (
        float(up["f"].mean() / up["b"].mean())
        if len(up) > 0 and up["b"].mean() != 0
        else None
    )
    dn_cap = (
        float(dn["f"].mean() / dn["b"].mean())
        if len(dn) > 0 and dn["b"].mean() != 0
        else None
    )
    return up_cap, dn_cap


def rolling_beta(
    fund_r: pd.Series, bench_r: pd.Series, window: int = 252
) -> pd.Series:
    """Rolling beta (OLS slope) over `window` trading days."""
    df = _align(fund_r, bench_r)
    if len(df) < window:
        return pd.Series(dtype=float)

    def _beta(sub: pd.DataFrame) -> float:
        bv = sub["b"].var()
        if bv == 0:
            return np.nan
        return sub.cov()["f"]["b"] / bv

    betas = [
        _beta(df.iloc[i - window: i])
        for i in range(window, len(df) + 1)
    ]
    return pd.Series(betas, index=df.index[window - 1:])


def calc_relative(
    fund_prices: pd.Series,
    bench_prices: pd.Series,
    start_date: str | None = None,
) -> dict:
    """
    Full benchmark-relative stat block.
    Returns: {alpha, beta, te, ir, up_cap, dn_cap,
              rolling_beta: {dates, values}}
    """
    if fund_prices is None or bench_prices is None:
        return _empty_relative()

    fp = fund_prices if start_date is None else fund_prices.loc[fund_prices.index >= pd.Timestamp(start_date)]
    bp = bench_prices if start_date is None else bench_prices.loc[bench_prices.index >= pd.Timestamp(start_date)]

    fr = returns_from_prices(fp)
    br = returns_from_prices(bp)

    if len(fr) < 20 or len(br) < 20:
        return _empty_relative()

    alpha_ann, beta = alpha_beta(fr, br)
    te = tracking_error(fr, br)
    ir = info_ratio(fr, br)
    up_cap, dn_cap = up_down_capture(fr, br)
    rb = rolling_beta(fr, br, window=252)

    return {
        "alpha":        alpha_ann,
        "beta":         beta,
        "te":           te,
        "ir":           ir,
        "up_cap":       up_cap,
        "dn_cap":       dn_cap,
        "rolling_beta": {
            "dates":  [d.strftime("%Y-%m-%d") for d in rb.index],
            "values": [None if np.isnan(v) else round(v, 4) for v in rb.values],
        },
    }


def _empty_relative() -> dict:
    return {
        "alpha": None, "beta": None, "te": None, "ir": None,
        "up_cap": None, "dn_cap": None,
        "rolling_beta": {"dates": [], "values": []},
    }


# ── Multi-fund return table ────────────────────────────────────────────────────

def calc_returns_table(
    price_cache: dict[str, pd.Series],
    windows: list[str] | None = None,
    rf_daily: float = 0.0,
) -> dict[str, dict]:
    """
    For each fund in price_cache, compute return for each window + 1Y vol + 1Y Sharpe.
    Returns: {fund_id: {window: float_or_None, 'vol_1y': float, 'sharpe_1y': float}}
    """
    if windows is None:
        windows = ["1M", "3M", "YTD", "1Y", "3Y"]

    result = {}
    for fid, prices in price_cache.items():
        if prices is None or prices.empty:
            result[fid] = {w: None for w in windows}
            result[fid].update({"vol_1y": None, "sharpe_1y": None})
            continue

        row: dict = {}
        for w in windows:
            row[w] = period_return(prices, w)

        # 1Y vol and Sharpe
        start_1y = _window_start(prices, "1Y")
        if start_1y is not None:
            sub_p = prices.loc[prices.index >= start_1y]
            if len(sub_p) >= 20:
                sub_r = returns_from_prices(sub_p)
                row["vol_1y"] = vol(sub_r)
                row["sharpe_1y"], row["sharpe_1y_lo"], row["sharpe_1y_hi"] = sharpe_ci(sub_r, rf_daily)
            else:
                row.update({"vol_1y": None, "sharpe_1y": None, "sharpe_1y_lo": None, "sharpe_1y_hi": None})
        else:
            row.update({"vol_1y": None, "sharpe_1y": None, "sharpe_1y_lo": None, "sharpe_1y_hi": None})

        result[fid] = row

    return result
