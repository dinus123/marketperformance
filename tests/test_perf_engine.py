"""
test_perf_engine.py — Unit tests for perf_engine.py.
All tests use synthetic data; zero network calls.
Annualisation: ×252 throughout (matching perf_engine convention).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import perf_engine as pe
from config import TRADING_DAYS


# ════════════════════════════════════════════════════════════════════════════
# returns_from_prices
# ════════════════════════════════════════════════════════════════════════════

class TestReturnsFromPrices:
    def test_basic_return(self):
        idx = pd.bdate_range("2023-01-02", periods=5)
        prices = pd.Series([100, 105, 100, 110, 100], index=idx, dtype=float)
        r = pe.returns_from_prices(prices)
        assert len(r) == 4
        assert math.isclose(r.iloc[0], 0.05, rel_tol=1e-9)

    def test_drops_first_nan(self):
        idx = pd.bdate_range("2023-01-02", periods=5)
        prices = pd.Series([100.0] * 5, index=idx)
        r = pe.returns_from_prices(prices)
        assert not r.isna().any()
        assert len(r) == 4

    def test_single_value(self, price_series_single):
        r = pe.returns_from_prices(price_series_single)
        assert r.empty

    def test_empty_series(self, price_series_empty):
        r = pe.returns_from_prices(price_series_empty)
        assert r.empty


# ════════════════════════════════════════════════════════════════════════════
# cagr
# ════════════════════════════════════════════════════════════════════════════

class TestCagr:
    def test_zero_return_flat(self, price_series_flat):
        r = pe.returns_from_prices(price_series_flat)
        result = pe.cagr(r)
        assert math.isclose(result, 0.0, abs_tol=1e-10)

    def test_positive_for_trending_up(self):
        # Deterministic: 0.05% daily return every day → positive CAGR guaranteed.
        idx = pd.bdate_range("2022-01-03", periods=500)
        prices = 100.0 * (1.0005 ** np.arange(len(idx)))
        r = pe.returns_from_prices(pd.Series(prices, index=idx))
        assert pe.cagr(r) > 0

    def test_negative_for_declining(self, price_series_declining):
        r = pe.returns_from_prices(price_series_declining)
        assert pe.cagr(r) < 0

    def test_empty_returns_zero(self):
        assert pe.cagr(pd.Series(dtype=float)) == 0.0

    def test_annualisation_formula(self):
        # 0.1% daily return for exactly TRADING_DAYS days
        idx = pd.bdate_range("2023-01-02", periods=TRADING_DAYS)
        r = pd.Series([0.001] * TRADING_DAYS, index=idx)
        expected = (1.001 ** TRADING_DAYS) - 1
        assert math.isclose(pe.cagr(r), expected, rel_tol=1e-9)


# ════════════════════════════════════════════════════════════════════════════
# vol
# ════════════════════════════════════════════════════════════════════════════

class TestVol:
    def test_flat_series_zero_vol(self, price_series_flat):
        r = pe.returns_from_prices(price_series_flat)
        assert pe.vol(r) == 0.0

    def test_single_return_zero_vol(self):
        r = pd.Series([0.01], index=pd.bdate_range("2023-01-02", periods=1))
        assert pe.vol(r) == 0.0

    def test_empty_zero_vol(self):
        assert pe.vol(pd.Series(dtype=float)) == 0.0

    def test_scale_matches_sqrt252(self):
        idx = pd.bdate_range("2023-01-02", periods=300)
        r = pd.Series([0.01, -0.01] * 150, index=idx, dtype=float)
        expected = r.std() * np.sqrt(TRADING_DAYS)
        assert math.isclose(pe.vol(r), expected, rel_tol=1e-9)

    def test_higher_noise_higher_vol(self, price_series_long):
        """Series with doubled noise should have approximately doubled vol."""
        rng = np.random.default_rng(42)
        idx = price_series_long.index
        r_low = pd.Series(rng.normal(0, 0.005, len(idx)), index=idx)
        r_high = pd.Series(rng.normal(0, 0.010, len(idx)), index=idx)
        assert pe.vol(r_high) > pe.vol(r_low)


# ════════════════════════════════════════════════════════════════════════════
# sharpe
# ════════════════════════════════════════════════════════════════════════════

class TestSharpe:
    def test_zero_std_returns_zero(self, price_series_flat):
        r = pe.returns_from_prices(price_series_flat)
        assert pe.sharpe(r) == 0.0

    def test_empty_returns_zero_or_nan(self):
        # sharpe on empty series: std=0 path not triggered (empty std is NaN);
        # result may be 0.0 or NaN — both are acceptable for an empty input.
        result = pe.sharpe(pd.Series(dtype=float))
        import math
        assert result == 0.0 or math.isnan(result)

    def test_sign_positive_drift(self, price_series_long):
        r = pe.returns_from_prices(price_series_long)
        # Positive drift → positive Sharpe (rf=0)
        assert pe.sharpe(r, rf_daily=0.0) > 0

    def test_rf_reduces_sharpe(self, price_series_long):
        r = pe.returns_from_prices(price_series_long)
        sr_no_rf = pe.sharpe(r, rf_daily=0.0)
        sr_with_rf = pe.sharpe(r, rf_daily=0.001)
        assert sr_no_rf > sr_with_rf


# ════════════════════════════════════════════════════════════════════════════
# sharpe_ci  (Lo 2002)
# ════════════════════════════════════════════════════════════════════════════

class TestSharpeCI:
    def test_returns_three_tuple(self, price_series_long):
        r = pe.returns_from_prices(price_series_long)
        result = pe.sharpe_ci(r)
        assert isinstance(result, tuple) and len(result) == 3

    def test_lo_le_sharpe_le_hi(self, price_series_long):
        r = pe.returns_from_prices(price_series_long)
        sr, lo, hi = pe.sharpe_ci(r)
        assert lo <= sr <= hi

    def test_ci_widens_with_fewer_obs(self):
        rng = np.random.default_rng(0)
        idx_long = pd.bdate_range("2018-01-02", periods=1260)
        idx_short = pd.bdate_range("2022-01-03", periods=252)
        r_long = pd.Series(rng.normal(0.0005, 0.008, len(idx_long)), index=idx_long)
        r_short = pd.Series(rng.normal(0.0005, 0.008, len(idx_short)), index=idx_short)
        _, lo_l, hi_l = pe.sharpe_ci(r_long)
        _, lo_s, hi_s = pe.sharpe_ci(r_short)
        assert (hi_s - lo_s) > (hi_l - lo_l)

    def test_zero_std_returns_zeros(self, price_series_flat):
        r = pe.returns_from_prices(price_series_flat)
        assert pe.sharpe_ci(r) == (0.0, 0.0, 0.0)

    def test_insufficient_obs_returns_zeros(self):
        r = pd.Series([0.01], index=pd.bdate_range("2023-01-02", periods=1))
        assert pe.sharpe_ci(r) == (0.0, 0.0, 0.0)


# ════════════════════════════════════════════════════════════════════════════
# sortino
# ════════════════════════════════════════════════════════════════════════════

class TestSortino:
    def test_all_positive_returns_zero(self):
        idx = pd.bdate_range("2023-01-02", periods=252)
        r = pd.Series([0.001] * 252, index=idx, dtype=float)
        # No downside returns → returns 0.0
        assert pe.sortino(r) == 0.0

    def test_positive_for_trending_up(self):
        # Deterministic: 0.05% daily return with tiny symmetric noise → positive CAGR/Sortino.
        idx = pd.bdate_range("2022-01-03", periods=500)
        rng = np.random.default_rng(123)
        r = pd.Series(0.0005 + rng.normal(0, 0.002, len(idx)), index=idx)
        assert pe.sortino(r) > 0

    def test_empty_returns_zero(self):
        assert pe.sortino(pd.Series(dtype=float)) == 0.0

    def test_negative_when_declining(self, price_series_declining):
        r = pe.returns_from_prices(price_series_declining)
        # CAGR is negative, downside_vol > 0 → Sortino < 0
        assert pe.sortino(r) < 0


# ════════════════════════════════════════════════════════════════════════════
# max_drawdown
# ════════════════════════════════════════════════════════════════════════════

class TestMaxDrawdown:
    def test_monotone_increasing_zero_dd(self):
        idx = pd.bdate_range("2023-01-02", periods=100)
        prices = pd.Series(np.linspace(100, 200, 100), index=idx)
        assert pe.max_drawdown(prices) == 0.0

    def test_empty_zero(self, price_series_empty):
        assert pe.max_drawdown(price_series_empty) == 0.0

    def test_always_nonpositive(self, price_series_long):
        assert pe.max_drawdown(price_series_long) <= 0.0

    def test_known_drawdown(self):
        """Peak=200, trough=100 → MDD = -0.5."""
        idx = pd.bdate_range("2023-01-02", periods=4)
        prices = pd.Series([100.0, 200.0, 150.0, 100.0], index=idx)
        mdd = pe.max_drawdown(prices)
        assert math.isclose(mdd, -0.5, rel_tol=1e-9)

    def test_declining_series_large_dd(self, price_series_declining):
        mdd = pe.max_drawdown(price_series_declining)
        assert mdd < -0.20  # roughly 22% decline over 252 days at 0.1%/day


# ════════════════════════════════════════════════════════════════════════════
# calmar
# ════════════════════════════════════════════════════════════════════════════

class TestCalmar:
    def test_zero_dd_returns_zero(self, price_series_flat):
        r = pe.returns_from_prices(price_series_flat)
        assert pe.calmar(r, price_series_flat) == 0.0

    def test_positive_for_uptrending(self):
        # Deterministic uptrend with drawdown: ensures CAGR > 0 and MDD < 0 → Calmar > 0.
        idx = pd.bdate_range("2022-01-03", periods=500)
        prices = pd.Series(100.0 * (1.0005 ** np.arange(len(idx))), index=idx)
        r = pe.returns_from_prices(prices)
        # Inject a drawdown by inserting a dip — use a V-shape series
        v = prices.copy()
        mid = len(v) // 2
        v.iloc[mid] = v.iloc[mid] * 0.80  # 20% single-day drop
        r2 = pe.returns_from_prices(v)
        assert pe.calmar(r2, v) > 0

    def test_ratio_definition(self, price_series_long):
        r = pe.returns_from_prices(price_series_long)
        expected = pe.cagr(r) / abs(pe.max_drawdown(price_series_long))
        result = pe.calmar(r, price_series_long)
        assert math.isclose(result, expected, rel_tol=1e-9)


# ════════════════════════════════════════════════════════════════════════════
# mtd / qtd / prev_month_return / prev_quarter_return
# ════════════════════════════════════════════════════════════════════════════

class TestPeriodFunctions:
    @pytest.fixture
    def multi_year_prices(self) -> pd.Series:
        """Daily prices spanning 2022-01-03 to 2024-03-29 (business days)."""
        idx = pd.bdate_range("2022-01-03", "2024-03-29")
        rng = np.random.default_rng(1)
        log_r = rng.normal(0.0002, 0.008, len(idx))
        prices = 100.0 * np.exp(np.cumsum(log_r))
        return pd.Series(prices, index=idx, name="MULTI")

    def test_mtd_returns_float(self, multi_year_prices):
        result = pe.mtd(multi_year_prices)
        assert isinstance(result, float)

    def test_mtd_empty_none(self, price_series_empty):
        assert pe.mtd(price_series_empty) is None

    def test_qtd_returns_float(self, multi_year_prices):
        result = pe.qtd(multi_year_prices)
        assert isinstance(result, float)

    def test_qtd_empty_none(self, price_series_empty):
        assert pe.qtd(price_series_empty) is None

    def test_prev_month_return_returns_float(self, multi_year_prices):
        result = pe.prev_month_return(multi_year_prices)
        assert isinstance(result, float)

    def test_prev_month_return_empty_none(self, price_series_empty):
        assert pe.prev_month_return(price_series_empty) is None

    def test_prev_quarter_return_returns_float(self, multi_year_prices):
        result = pe.prev_quarter_return(multi_year_prices)
        assert isinstance(result, float)

    def test_prev_quarter_return_empty_none(self, price_series_empty):
        assert pe.prev_quarter_return(price_series_empty) is None

    def test_mtd_single_obs_none(self, price_series_single):
        assert pe.mtd(price_series_single) is None

    def test_qtd_single_obs_none(self, price_series_single):
        assert pe.qtd(price_series_single) is None


# ════════════════════════════════════════════════════════════════════════════
# calendar_year_return
# ════════════════════════════════════════════════════════════════════════════

class TestCalendarYearReturn:
    @pytest.fixture
    def full_2022(self) -> pd.Series:
        """Full year 2022 of business-day prices."""
        idx = pd.bdate_range("2022-01-03", "2022-12-30")
        prices = pd.Series(np.linspace(100.0, 110.0, len(idx)), index=idx)
        return prices

    def test_known_return_2022(self, full_2022):
        result = pe.calendar_year_return(full_2022, 2022)
        expected = full_2022.iloc[-1] / full_2022.iloc[0] - 1
        assert math.isclose(result, expected, rel_tol=1e-9)

    def test_missing_year_none(self, full_2022):
        assert pe.calendar_year_return(full_2022, 2021) is None

    def test_empty_series_none(self, price_series_empty):
        assert pe.calendar_year_return(price_series_empty, 2022) is None

    def test_mid_year_launch_none(self):
        """Fund starting June should return None for that year (past year)."""
        idx = pd.bdate_range("2022-06-01", "2022-12-30")
        prices = pd.Series(100.0, index=idx)
        # first date > Jan 31 → None
        assert pe.calendar_year_return(prices, 2022) is None


# ════════════════════════════════════════════════════════════════════════════
# inception_date
# ════════════════════════════════════════════════════════════════════════════

class TestInceptionDate:
    def test_format_yyyy_mm(self, price_series_long):
        result = pe.inception_date(price_series_long)
        assert result is not None
        assert len(result) == 7  # "YYYY-MM"
        assert result[4] == "-"

    def test_correct_year_month(self, price_series_long):
        # price_series_long starts 2022-01-03
        assert pe.inception_date(price_series_long) == "2022-01"

    def test_empty_returns_none(self, price_series_empty):
        assert pe.inception_date(price_series_empty) is None


# ════════════════════════════════════════════════════════════════════════════
# calc_stats
# ════════════════════════════════════════════════════════════════════════════

class TestCalcStats:
    EXPECTED_KEYS = {"cagr", "vol", "sharpe", "sharpe_lo", "sharpe_hi",
                     "sortino", "max_dd", "skew", "kurt", "n_obs", "calmar"}

    def test_returns_expected_keys(self, price_series_long):
        result = pe.calc_stats(price_series_long)
        assert self.EXPECTED_KEYS == set(result.keys())

    def test_all_floats_or_int(self, price_series_long):
        result = pe.calc_stats(price_series_long)
        for k, v in result.items():
            assert isinstance(v, (int, float)), f"{k} is {type(v)}"

    def test_below_min_obs_returns_nones(self):
        idx = pd.bdate_range("2023-01-02", periods=5)
        prices = pd.Series([100.0, 101, 102, 103, 104], index=idx)
        result = pe.calc_stats(prices)
        for v in result.values():
            assert v is None

    def test_none_input_returns_nones(self):
        result = pe.calc_stats(None)
        for v in result.values():
            assert v is None

    def test_max_dd_nonpositive(self, price_series_long):
        result = pe.calc_stats(price_series_long)
        assert result["max_dd"] <= 0

    def test_vol_nonnegative(self, price_series_long):
        result = pe.calc_stats(price_series_long)
        assert result["vol"] >= 0

    def test_n_obs_matches_returns_length(self, price_series_long):
        result = pe.calc_stats(price_series_long)
        expected_n = len(pe.returns_from_prices(price_series_long))
        assert result["n_obs"] == expected_n

    def test_sharpe_lo_le_sharpe_le_hi(self, price_series_long):
        result = pe.calc_stats(price_series_long)
        assert result["sharpe_lo"] <= result["sharpe"] <= result["sharpe_hi"]


# ════════════════════════════════════════════════════════════════════════════
# calc_calendar — CRITICAL: all dict keys must be strings
# ════════════════════════════════════════════════════════════════════════════

class TestCalcCalendar:
    def test_empty_returns_empty_dict(self, price_series_empty):
        assert pe.calc_calendar(price_series_empty) == {}

    def test_none_returns_empty_dict(self):
        assert pe.calc_calendar(None) == {}

    def test_all_outer_keys_are_strings(self, price_series_long):
        """Year keys MUST be str, not int — Python 3.13 jsonify fails on mixed int/str."""
        result = pe.calc_calendar(price_series_long)
        for k in result.keys():
            assert isinstance(k, str), f"Year key {k!r} is {type(k)}, expected str"

    def test_all_inner_keys_are_strings(self, price_series_long):
        """Month keys (1–12) and 'ann' MUST all be strings."""
        result = pe.calc_calendar(price_series_long)
        for year_str, month_dict in result.items():
            for mk in month_dict.keys():
                assert isinstance(mk, str), (
                    f"Inner key {mk!r} in year {year_str} is {type(mk)}, expected str"
                )

    def test_ann_key_present_in_each_year(self, price_series_long):
        result = pe.calc_calendar(price_series_long)
        for year_str, month_dict in result.items():
            assert "ann" in month_dict, f"'ann' missing for year {year_str}"

    def test_monthly_values_are_floats(self, price_series_long):
        result = pe.calc_calendar(price_series_long)
        for year_str, month_dict in result.items():
            for mk, mv in month_dict.items():
                assert isinstance(mv, float), f"Value for {year_str}/{mk} is {type(mv)}"

    def test_covers_expected_years(self, price_series_long):
        """price_series_long spans 2022–2024 (3 years)."""
        result = pe.calc_calendar(price_series_long)
        years = set(result.keys())
        assert "2022" in years
        assert "2023" in years

    def test_monthly_product_matches_annual(self, price_series_long):
        """Product of monthly returns should equal the annual return."""
        result = pe.calc_calendar(price_series_long)
        for year_str, month_dict in result.items():
            monthly = [v for k, v in month_dict.items() if k != "ann"]
            product = (1 + np.array(monthly)).prod() - 1
            assert math.isclose(product, month_dict["ann"], rel_tol=1e-6), (
                f"Year {year_str}: monthly product {product:.6f} != ann {month_dict['ann']:.6f}"
            )


# ════════════════════════════════════════════════════════════════════════════
# calc_returns_table
# ════════════════════════════════════════════════════════════════════════════

class TestCalcReturnsTable:
    def test_returns_all_fund_ids(self, price_series_long, bench_series):
        cache = {"FUND_A": price_series_long, "FUND_B": bench_series}
        result = pe.calc_returns_table(cache)
        assert set(result.keys()) == {"FUND_A", "FUND_B"}

    def test_default_windows_present(self, price_series_long):
        cache = {"FUND_A": price_series_long}
        result = pe.calc_returns_table(cache)
        row = result["FUND_A"]
        for w in ["1M", "3M", "YTD", "1Y", "3Y"]:
            assert w in row

    def test_empty_series_all_none(self, price_series_empty):
        cache = {"EMPTY": price_series_empty}
        result = pe.calc_returns_table(cache)
        row = result["EMPTY"]
        for w in ["1M", "3M", "YTD", "1Y", "3Y"]:
            assert row[w] is None

    def test_empty_cache_returns_empty(self):
        assert pe.calc_returns_table({}) == {}

    def test_vol_1y_nonnegative(self, price_series_long):
        cache = {"FUND_A": price_series_long}
        result = pe.calc_returns_table(cache)
        v = result["FUND_A"].get("vol_1y")
        if v is not None:
            assert v >= 0

    def test_custom_windows(self, price_series_long):
        cache = {"FUND_A": price_series_long}
        result = pe.calc_returns_table(cache, windows=["1M", "1Y"])
        row = result["FUND_A"]
        assert "1M" in row and "1Y" in row
        assert "3M" not in row


# ════════════════════════════════════════════════════════════════════════════
# calc_relative
# ════════════════════════════════════════════════════════════════════════════

class TestCalcRelative:
    EXPECTED_KEYS = {"alpha", "beta", "te", "ir", "up_cap", "dn_cap", "rolling_beta"}

    def test_returns_expected_keys(self, price_series_long, bench_series):
        result = pe.calc_relative(price_series_long, bench_series)
        assert self.EXPECTED_KEYS == set(result.keys())

    def test_rolling_beta_structure(self, price_series_long, bench_series):
        result = pe.calc_relative(price_series_long, bench_series)
        rb = result["rolling_beta"]
        assert "dates" in rb and "values" in rb
        assert len(rb["dates"]) == len(rb["values"])

    def test_none_fund_returns_empty(self, bench_series):
        result = pe.calc_relative(None, bench_series)
        assert result["alpha"] is None

    def test_none_bench_returns_empty(self, price_series_long):
        result = pe.calc_relative(price_series_long, None)
        assert result["alpha"] is None

    def test_beta_roughly_one_identical_series(self, price_series_long):
        """Fund identical to bench → beta ≈ 1, alpha ≈ 0."""
        result = pe.calc_relative(price_series_long, price_series_long)
        assert math.isclose(result["beta"], 1.0, abs_tol=1e-6)

    def test_short_series_returns_empty(self):
        """Less than 20 obs → _empty_relative."""
        idx = pd.bdate_range("2023-01-02", periods=10)
        p1 = pd.Series(np.linspace(100, 105, 10), index=idx)
        p2 = pd.Series(np.linspace(100, 103, 10), index=idx)
        result = pe.calc_relative(p1, p2)
        assert result["alpha"] is None

    def test_te_nonnegative(self, price_series_long, bench_series):
        result = pe.calc_relative(price_series_long, bench_series)
        if result["te"] is not None:
            assert result["te"] >= 0

    def test_start_date_filter(self, price_series_long, bench_series):
        """Passing start_date slices the series; result should still be valid."""
        result = pe.calc_relative(price_series_long, bench_series, start_date="2023-01-01")
        assert result["alpha"] is not None


# ════════════════════════════════════════════════════════════════════════════
# calc_correlation
# ════════════════════════════════════════════════════════════════════════════

class TestCalcCorrelation:
    def test_empty_cache_returns_empty(self):
        result = pe.calc_correlation({})
        assert result["ids"] == []
        assert result["matrix"] == []

    def test_single_fund_self_corr_one(self, price_series_long):
        cache = {"FUND_A": price_series_long}
        result = pe.calc_correlation(cache, window="All")
        assert result["matrix"] == [[1.0]]

    def test_matrix_is_square(self, price_series_long, bench_series):
        cache = {"FUND_A": price_series_long, "FUND_B": bench_series}
        result = pe.calc_correlation(cache, window="All")
        n = len(result["ids"])
        assert len(result["matrix"]) == n
        for row in result["matrix"]:
            assert len(row) == n

    def test_diagonal_is_one(self, price_series_long, bench_series):
        cache = {"FUND_A": price_series_long, "FUND_B": bench_series}
        result = pe.calc_correlation(cache, window="All")
        for i in range(len(result["ids"])):
            assert result["matrix"][i][i] == 1.0

    def test_correlation_bounded(self, price_series_long, bench_series):
        cache = {"FUND_A": price_series_long, "FUND_B": bench_series}
        result = pe.calc_correlation(cache, window="All")
        for row in result["matrix"]:
            for v in row:
                if v is not None:
                    assert -1.0 <= v <= 1.0

    def test_ids_sorted_alphabetically(self, price_series_long, bench_series):
        cache = {"ZZFUND": price_series_long, "AAFUND": bench_series}
        result = pe.calc_correlation(cache, window="All")
        assert result["ids"] == sorted(result["ids"])

    def test_n_obs_populated(self, price_series_long, bench_series):
        cache = {"FUND_A": price_series_long, "FUND_B": bench_series}
        result = pe.calc_correlation(cache, window="All")
        assert "n_obs" in result
        for fid in result["ids"]:
            assert isinstance(result["n_obs"][fid], int)

    def test_empty_series_excluded(self, price_series_long, price_series_empty):
        """Empty series should be silently excluded from the correlation matrix."""
        cache = {"FUND_A": price_series_long, "EMPTY": price_series_empty}
        result = pe.calc_correlation(cache, window="All")
        assert "EMPTY" not in result["ids"]

    def test_window_1y(self, price_series_long, bench_series):
        """window=1Y should produce valid result (may have fewer obs)."""
        cache = {"FUND_A": price_series_long, "FUND_B": bench_series}
        result = pe.calc_correlation(cache, window="1Y")
        assert result["window"] == "1Y"


# ════════════════════════════════════════════════════════════════════════════
# Edge cases: NaN gaps in price series
# ════════════════════════════════════════════════════════════════════════════

class TestNaNEdgeCases:
    def test_returns_from_prices_with_nan(self, price_series_with_nan):
        """returns_from_prices uses pct_change().dropna() — NaN propagates then drops."""
        r = pe.returns_from_prices(price_series_with_nan)
        # Some NaNs will survive pct_change at gap boundaries, but dropna() removes them
        # Result should not be empty
        assert len(r) > 0

    def test_calc_stats_with_nan_prices(self, price_series_with_nan):
        """calc_stats should not raise on a series with NaN holes."""
        result = pe.calc_stats(price_series_with_nan)
        # Should return a valid stats dict (the NaN rows just drop)
        assert isinstance(result, dict)

    def test_calc_calendar_with_nan_prices(self, price_series_with_nan):
        """calc_calendar should not raise on NaN holes."""
        result = pe.calc_calendar(price_series_with_nan)
        assert isinstance(result, dict)

    def test_period_return_with_nan(self, price_series_with_nan):
        """period_return should handle NaN-containing series."""
        result = pe.period_return(price_series_with_nan, "1Y")
        # May be None if insufficient data after NaN drop, or a float
        assert result is None or isinstance(result, float)
