"""
conftest.py — Shared pytest fixtures for the market performance dashboard test suite.
All fixtures use synthetic data; zero network calls.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ── Date ranges ────────────────────────────────────────────────────────────────

def _bdate_range(start: str, periods: int) -> pd.DatetimeIndex:
    """Business-day DatetimeIndex of `periods` days starting from `start`."""
    return pd.bdate_range(start=start, periods=periods)


# ── Synthetic price series ─────────────────────────────────────────────────────

@pytest.fixture
def price_series_long() -> pd.Series:
    """
    3-year (756 bday) trending price series with mild noise.
    Starts 2022-01-03, monotonically trending up so max_dd is meaningful.
    """
    rng = np.random.default_rng(42)
    idx = _bdate_range("2022-01-03", 756)
    # Daily log returns: small positive drift + noise
    log_r = rng.normal(loc=0.0003, scale=0.008, size=len(idx))
    prices = 100.0 * np.exp(np.cumsum(log_r))
    return pd.Series(prices, index=idx, name="FUND_A", dtype=float)


@pytest.fixture
def price_series_short() -> pd.Series:
    """252-day (1Y) price series — just above the MIN_OBS threshold."""
    rng = np.random.default_rng(7)
    idx = _bdate_range("2023-01-02", 252)
    log_r = rng.normal(loc=0.0001, scale=0.010, size=len(idx))
    prices = 100.0 * np.exp(np.cumsum(log_r))
    return pd.Series(prices, index=idx, name="FUND_B", dtype=float)


@pytest.fixture
def price_series_flat() -> pd.Series:
    """Flat price series (zero returns) — stress test for Sharpe / vol edge cases."""
    idx = _bdate_range("2022-01-03", 252)
    prices = pd.Series(100.0, index=idx, name="FUND_FLAT", dtype=float)
    return prices


@pytest.fixture
def price_series_declining() -> pd.Series:
    """252-day steadily declining series — max_dd should be strongly negative."""
    idx = _bdate_range("2022-01-03", 252)
    # Deterministic daily decline of 0.1 %
    prices = 100.0 * (0.999 ** np.arange(len(idx)))
    return pd.Series(prices, index=idx, name="FUND_DEC", dtype=float)


@pytest.fixture
def price_series_empty() -> pd.Series:
    """Empty series."""
    return pd.Series(dtype=float, name="EMPTY")


@pytest.fixture
def price_series_single() -> pd.Series:
    """Single-observation series."""
    idx = pd.DatetimeIndex(["2023-06-01"])
    return pd.Series([100.0], index=idx, name="SINGLE")


@pytest.fixture
def price_series_with_nan(price_series_long) -> pd.Series:
    """Long series with 5 NaN holes injected mid-series."""
    s = price_series_long.copy()
    s.iloc[100:105] = np.nan
    return s


@pytest.fixture
def bench_series(price_series_long) -> pd.Series:
    """
    Benchmark series on the same date range as price_series_long,
    but with different random seed (correlated but distinct).
    """
    rng = np.random.default_rng(99)
    log_r = rng.normal(loc=0.0002, scale=0.009, size=len(price_series_long))
    prices = 100.0 * np.exp(np.cumsum(log_r))
    return pd.Series(prices, index=price_series_long.index, name="BENCH", dtype=float)


# ── Mock _price_cache for app tests ───────────────────────────────────────────

@pytest.fixture
def mock_price_cache(price_series_long, bench_series) -> dict[str, pd.Series]:
    """
    Minimal _price_cache dict: two funds with real data, one empty.
    Sufficient to exercise all /api/* endpoints.
    """
    return {
        "FUND_A": price_series_long,
        "FUND_B": bench_series.rename("FUND_B"),
        "FUND_EMPTY": pd.Series(dtype=float, name="FUND_EMPTY"),
    }


# ── Flask test client ─────────────────────────────────────────────────────────

@pytest.fixture
def flask_client(mock_price_cache, monkeypatch):
    """
    Flask test client with:
      - _price_cache monkeypatched to mock_price_cache (no yfinance calls)
      - load_universe monkeypatched to return a minimal universe list
      - No filesystem reads or network calls
    """
    import app as app_module
    import data_engine as de

    minimal_universe = [
        {
            "id": "FUND_A",
            "name": "Synthetic Fund A",
            "ticker": "SYNTH_A",
            "isin": "",
            "instrument_type": "ETF",
            "asset_class": "DM Equity",
            "currency": "USD",
            "ter_bps": 20,
            "data_source": "yfinance",
            "active": True,
            "notes": "",
            "manager": "Test Manager",
        },
        {
            "id": "FUND_B",
            "name": "Synthetic Fund B",
            "ticker": "SYNTH_B",
            "isin": "",
            "instrument_type": "ETF",
            "asset_class": "DM Equity",
            "currency": "USD",
            "ter_bps": 15,
            "data_source": "yfinance",
            "active": True,
            "notes": "",
            "manager": "Test Manager",
        },
        {
            "id": "FUND_EMPTY",
            "name": "Empty Fund",
            "ticker": "EMPTY",
            "isin": "",
            "instrument_type": "ETF",
            "asset_class": "DM Equity",
            "currency": "USD",
            "ter_bps": 0,
            "data_source": "yfinance",
            "active": True,
            "notes": "",
            "manager": "",
        },
    ]

    monkeypatch.setattr(app_module, "_price_cache", mock_price_cache)
    monkeypatch.setattr(de, "load_universe", lambda: minimal_universe)

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client
