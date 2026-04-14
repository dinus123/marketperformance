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

# ── Frequency detection ───────────────────────────────────────────────────────

def detect_freq(prices: pd.Series) -> tuple[str, int]:
    """
    Infer observation frequency from median inter-obs gap.
    Returns (label, ann_factor): ('D', 252) | ('W', 52) | ('M', 12).
    Threshold: median gap ≤2d → daily; ≤10d → weekly; >10d → monthly.
    """
    if prices is None or len(prices) < 4:
        return 'D', TRADING_DAYS
    gaps = prices.index.to_series().diff().dt.days.dropna()
    median_gap = gaps.median()
    if median_gap <= 2:
        return 'D', TRADING_DAYS
    elif median_gap <= 10:
        return 'W', 52
    else:
        return 'M', 12


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


def _prior_close(prices: pd.Series, period_start: pd.Timestamp) -> float | None:
    """Last price strictly before period_start. Used as base for period returns."""
    before = prices[prices.index < period_start]
    return float(before.iloc[-1]) if not before.empty else None


def period_return(prices: pd.Series, window: str) -> float | None:
    """
    Cumulative return over the given window.
    Uses last price before window start as base (consistent with calc_calendar).
    window: '1M' | '3M' | '6M' | 'YTD' | '1Y' | '3Y' | '5Y' | 'All'
    Returns float (e.g. 0.123 = 12.3%) or None if insufficient data.
    """
    if prices is None or prices.empty:
        return None
    start = _window_start(prices, window)
    if start is None:
        return None
    sub = prices.loc[prices.index >= start]
    if sub.empty:
        return None
    end_price = float(sub.iloc[-1])
    base = _prior_close(prices, start)
    if base is None:
        # No prior data (e.g. All-history or inception): use first price in window
        if len(sub) < 2:
            return None
        base = float(sub.iloc[0])
    return end_price / base - 1


# ── Annualised statistics ──────────────────────────────────────────────────────

def cagr(returns: pd.Series, ann_factor: int = TRADING_DAYS) -> float:
    """Compound annual growth rate. Annualised ×ann_factor (default 252)."""
    if returns.empty:
        return 0.0
    return float((1 + returns).prod() ** (ann_factor / len(returns)) - 1)


def vol(returns: pd.Series, ann_factor: int = TRADING_DAYS) -> float:
    """Annualised volatility ×√ann_factor (default 252)."""
    if len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(ann_factor))


def sharpe(returns: pd.Series, rf_daily: float = 0.0, ann_factor: int = TRADING_DAYS) -> float:
    """Annualised Sharpe ratio."""
    excess = returns - rf_daily
    if excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(ann_factor))


def sharpe_ci(
    returns: pd.Series, rf_daily: float = 0.0, z: float = 1.96,
    ann_factor: int = TRADING_DAYS,
) -> tuple[float, float, float]:
    """
    Lo (2002) Sharpe ratio with 95% CI.
    Returns (sharpe_ann, lo_95, hi_95).
    se = sqrt((1 + 0.5*SR_d^2) / n) * sqrt(ann_factor)
    """
    excess = returns - rf_daily
    n = len(excess)
    if n < 2 or excess.std() == 0:
        return 0.0, 0.0, 0.0
    sr_d = excess.mean() / excess.std()
    se = np.sqrt((1 + 0.5 * sr_d**2) / n) * np.sqrt(ann_factor)
    sr_ann = float(sr_d * np.sqrt(ann_factor))
    return sr_ann, float(sr_ann - z * se), float(sr_ann + z * se)


def sortino(returns: pd.Series, rf_daily: float = 0.0, ann_factor: int = TRADING_DAYS) -> float:
    """Sortino ratio: CAGR / downside vol (semi-deviation annualised)."""
    excess = returns - rf_daily
    downside = excess[excess < 0]
    if len(downside) < 2:
        return 0.0
    downside_vol = downside.std() * np.sqrt(ann_factor)
    if downside_vol == 0:
        return 0.0
    return float(cagr(returns, ann_factor) / downside_vol)


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
    Auto-detects observation frequency; uses correct ann_factor for all metrics.
    Returns dict with: cagr, vol, sharpe, sharpe_lo, sharpe_hi,
                       sortino, max_dd, calmar, skew, kurt, n_obs, freq
    All floats. None for series with < MIN_OBS observations.
    """
    MIN_OBS = 20
    if prices is None or len(prices) < MIN_OBS:
        return _empty_stats()

    freq_label, ann_factor = detect_freq(prices)
    r = returns_from_prices(prices)
    sr, sr_lo, sr_hi = sharpe_ci(r, rf_daily, ann_factor=ann_factor)

    return {
        "cagr":      cagr(r, ann_factor),
        "vol":       vol(r, ann_factor),
        "sharpe":    sr,
        "sharpe_lo": sr_lo,
        "sharpe_hi": sr_hi,
        "sortino":   sortino(r, rf_daily, ann_factor),
        "max_dd":    max_drawdown(prices),
        "calmar":    calmar(r, prices),
        "skew":      skew(r),
        "kurt":      kurt(r),
        "n_obs":     len(r),
        "freq":      freq_label,
    }


def _empty_stats() -> dict:
    keys = ["cagr", "vol", "sharpe", "sharpe_lo", "sharpe_hi",
            "sortino", "max_dd", "calmar", "skew", "kurt", "n_obs", "freq"]
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


def calc_correlation(price_cache: dict, window: str = "3Y", min_overlap: int = 60) -> dict:
    """Pairwise Pearson correlation of daily returns. window: 1Y|3Y|5Y|All"""
    import numpy as np

    lookback_days = {"1Y": 365, "3Y": 1095, "5Y": 1825, "All": None}
    days = lookback_days.get(window)
    cutoff = (pd.Timestamp.today() - pd.Timedelta(days=days)) if days else None

    returns = {}
    for fid, prices in price_cache.items():
        if prices is None or prices.empty:
            continue
        sub = prices[prices.index >= cutoff] if cutoff is not None else prices
        r = sub.pct_change().dropna()
        if len(r) >= min_overlap:
            returns[fid] = r

    if not returns:
        return {"ids": [], "names": [], "matrix": [], "window": window, "n_obs": {}}

    ids = sorted(returns.keys())
    matrix = []
    for id_i in ids:
        row = []
        for id_j in ids:
            if id_i == id_j:
                row.append(1.0)
            else:
                df = pd.DataFrame({"a": returns[id_i], "b": returns[id_j]}).dropna()
                if len(df) < min_overlap:
                    row.append(None)
                else:
                    c = df["a"].corr(df["b"])
                    row.append(round(float(c), 4) if not np.isnan(c) else None)
        matrix.append(row)

    return {
        "ids": ids,
        "names": ids,
        "matrix": matrix,
        "window": window,
        "n_obs": {fid: int(len(returns[fid])) for fid in ids},
    }


# ── New period functions for overview rebuild ─────────────────────────────────

def mtd(prices: pd.Series, ref_date: pd.Timestamp | None = None) -> float | None:
    """
    Return from prior month-end close to last price in the current month.
    ref_date: reference point for 'current month' (defaults to prices.index[-1]).
    Returns None if fund has no data in the current month.
    """
    if prices is None or prices.empty:
        return None
    ref = ref_date if ref_date is not None else prices.index[-1]
    month_start = pd.Timestamp(ref.year, ref.month, 1)
    base = _prior_close(prices, month_start)
    if base is None:
        return None
    current = prices[prices.index >= month_start]
    if current.empty:
        return None
    return float(current.iloc[-1]) / base - 1


def prev_month_return(prices: pd.Series, ref_date: pd.Timestamp | None = None) -> float | None:
    """
    Return for the previous complete calendar month (prior month-end to month-end).
    ref_date: reference point defining 'current month' (defaults to prices.index[-1]).
    """
    if prices is None or prices.empty:
        return None
    ref = ref_date if ref_date is not None else prices.index[-1]
    cur_month_start = pd.Timestamp(ref.year, ref.month, 1)
    prev_end = cur_month_start - pd.Timedelta(days=1)
    prev_start = pd.Timestamp(prev_end.year, prev_end.month, 1)
    sub_end = prices[prices.index <= prev_end]
    if sub_end.empty:
        return None
    end_price = float(sub_end.iloc[-1])
    base = _prior_close(prices, prev_start)
    if base is None:
        return None
    return end_price / base - 1


def qtd(prices: pd.Series, ref_date: pd.Timestamp | None = None) -> float | None:
    """
    Return from prior quarter-end close to last price in the current quarter.
    ref_date: reference point defining 'current quarter' (defaults to prices.index[-1]).
    Returns None if fund has no data in the current quarter.
    """
    if prices is None or prices.empty:
        return None
    ref = ref_date if ref_date is not None else prices.index[-1]
    q_month = ((ref.month - 1) // 3) * 3 + 1
    q_start = pd.Timestamp(ref.year, q_month, 1)
    base = _prior_close(prices, q_start)
    if base is None:
        return None
    current = prices[prices.index >= q_start]
    if current.empty:
        return None
    return float(current.iloc[-1]) / base - 1


def prev_quarter_return(prices: pd.Series, ref_date: pd.Timestamp | None = None) -> float | None:
    """
    Return for the previous complete calendar quarter (prior quarter-end to quarter-end).
    ref_date: reference point defining 'current quarter' (defaults to prices.index[-1]).
    """
    if prices is None or prices.empty:
        return None
    ref = ref_date if ref_date is not None else prices.index[-1]
    cur_q_month = ((ref.month - 1) // 3) * 3 + 1
    cur_q_start = pd.Timestamp(ref.year, cur_q_month, 1)
    prev_q_end = cur_q_start - pd.Timedelta(days=1)
    prev_q_month = ((prev_q_end.month - 1) // 3) * 3 + 1
    prev_q_start = pd.Timestamp(prev_q_end.year, prev_q_month, 1)
    sub_end = prices[prices.index <= prev_q_end]
    if sub_end.empty:
        return None
    end_price = float(sub_end.iloc[-1])
    base = _prior_close(prices, prev_q_start)
    if base is None:
        return None
    return end_price / base - 1


def calendar_year_return(prices: pd.Series, year: int) -> float | None:
    """Full calendar year return using prior year-end as base."""
    if prices is None or prices.empty:
        return None
    sub = prices[prices.index.year == year]
    if sub.empty:
        return None
    if sub.index[0] > pd.Timestamp(year, 1, 31):
        return None  # fund launched mid-year
    if sub.index[-1] < pd.Timestamp(year, 12, 1) and year < pd.Timestamp.today().year:
        return None  # fund ended mid-year
    end_price = float(sub.iloc[-1])
    base = _prior_close(prices, pd.Timestamp(year, 1, 1))
    if base is None:
        base = float(sub.iloc[0])  # fund started this year: use inception price
    return end_price / base - 1


def inception_date(prices: pd.Series) -> str | None:
    """Return first date in price series as YYYY-MM string."""
    if prices is None or prices.empty:
        return None
    return prices.index[0].strftime("%Y-%m")


def aum_from_ticker(ticker: str) -> str | None:
    """Try to fetch AUM from yfinance fast_info.total_assets. Returns formatted string or None."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        ta = getattr(info, 'total_assets', None)
        if ta and ta > 0:
            if ta >= 1e9:
                return f"${ta/1e9:.1f}bn"
            elif ta >= 1e6:
                return f"${ta/1e6:.0f}m"
    except Exception:
        pass
    return None
