"""
data_engine.py — All data download, caching, FX conversion, and universe I/O.
No yfinance or requests calls anywhere else in the project.
"""

from __future__ import annotations

import json
import logging
import pickle
import threading
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

import config

logger = logging.getLogger(__name__)

# ── Thread safety ──────────────────────────────────────────────────────────────
_ticker_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


def _get_lock(key: str) -> threading.Lock:
    with _registry_lock:
        if key not in _ticker_locks:
            _ticker_locks[key] = threading.Lock()
        return _ticker_locks[key]


# ── File cache ─────────────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = key.replace("/", "_").replace("^", "_")
    return config.CACHE_DIR / f"{safe}.pkl"


def _cache_get(key: str, ttl: int = config.CACHE_TTL) -> Optional[pd.DataFrame]:
    p = _cache_path(key)
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > ttl:
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _cache_set(key: str, data: pd.DataFrame) -> None:
    with open(_cache_path(key), "wb") as f:
        pickle.dump(data, f)


# ── Price download ─────────────────────────────────────────────────────────────

def get_prices(
    ticker: str,
    start: str = config.DEFAULT_START,
    end: Optional[str] = None,
    use_cache: bool = True,
) -> Optional[pd.DataFrame]:
    """
    Fetch daily adjusted close prices via yfinance.

    Returns DataFrame[ticker] indexed by date (DatetimeIndex), or None if:
      - ticker not found
      - fewer than config.MIN_ROWS rows returned
      - download error
    """
    cache_key = f"prices_{ticker}_{start}"

    with _get_lock(ticker):
        if use_cache:
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached

        try:
            raw = yf.download(
                ticker,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                multi_level_index=False,
            )
        except Exception as e:
            logger.warning("yfinance download failed for %s: %s", ticker, e)
            return None

        if raw is None or raw.empty or "Close" not in raw.columns:
            return None

        df = (
            raw[["Close"]]
            .rename(columns={"Close": ticker})
            .pipe(lambda d: d.set_index(pd.to_datetime(d.index)))
            .dropna()
        )

        if len(df) < config.MIN_ROWS:
            return None

        _cache_set(cache_key, df)
        return df


# ── Yahoo Finance search (handles 0P... internal fund identifiers) ─────────────

def search_yahoo(query: str, max_results: int = 8) -> list[dict]:
    """
    Search Yahoo Finance for a fund by name or any free-text query.

    Uses yfinance.Search which handles session/crumb auth — avoids the 429
    rate-limit issues of hitting the raw search API directly.

    Returns list of dicts: {symbol, name, type, exchange}
    Covers exchange-listed tickers AND internal Yahoo 0P... fund identifiers.
    """
    try:
        result = yf.Search(query, max_results=max_results, enable_fuzzy_query=True)
        return [
            {
                "symbol":   q.get("symbol", ""),
                "name":     q.get("longname") or q.get("shortname") or "",
                "type":     q.get("quoteType", ""),
                "exchange": q.get("exchange", ""),
            }
            for q in result.quotes
            if q.get("symbol")
        ]
    except Exception as e:
        logger.warning("yf.Search failed for query=%s: %s", query, e)
        return []


# ── OpenFIGI ISIN → exchange ticker lookup ─────────────────────────────────────

def lookup_isin(isin: str) -> list[dict]:
    """
    Query OpenFIGI to resolve an ISIN to exchange-listed tickers.

    Returns list of dicts:
      {ticker, exchange_code, yahoo_ticker, name, currency, security_type}
    Empty list if nothing found or request fails.
    """
    try:
        resp = requests.post(
            config.OPENFIGI_URL,
            json=[{"idType": "ID_ISIN", "idValue": isin}],
            headers={"Content-Type": "application/json"},
            timeout=config.OPENFIGI_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.warning("OpenFIGI request failed for %s: %s", isin, e)
        return []

    if not payload or "data" not in payload[0]:
        return []

    results = []
    for item in payload[0]["data"]:
        exch = item.get("exchCode", "")
        ticker = item.get("ticker", "")
        suffix = config.EXCH_YAHOO_SUFFIX.get(exch, "")
        yahoo_ticker = f"{ticker}{suffix}" if suffix else ticker
        results.append({
            "ticker": ticker,
            "exchange_code": exch,
            "yahoo_ticker": yahoo_ticker,
            "name": item.get("name", ""),
            "currency": item.get("currency", ""),
            "security_type": item.get("securityType", ""),
        })
    return results


# ── Universe I/O ───────────────────────────────────────────────────────────────

def load_universe() -> list[dict]:
    with open(config.UNIVERSE_FILE) as f:
        return json.load(f)


def save_universe(universe: list[dict]) -> None:
    with open(config.UNIVERSE_FILE, "w") as f:
        json.dump(universe, f, indent=2)


# ── Data access test ───────────────────────────────────────────────────────────

def test_access(start: str = "2018-01-01") -> pd.DataFrame:
    """
    Test Yahoo Finance access for every fund in universe.json.

    For funds with a known ticker: test directly.
    For funds with only an ISIN: query OpenFIGI for candidate exchange tickers,
    then test each until one succeeds.

    Returns a DataFrame with one row per fund showing:
      manager, name, type, isin/ticker, yahoo_ticker_tried, status, rows, date_start, date_end
    """
    universe = load_universe()
    rows = []

    for fund in universe:
        ftype      = fund["instrument_type"]
        name       = fund["name"]
        manager    = fund["manager"]
        ticker     = fund.get("ticker")
        isin       = fund.get("isin")
        notes      = fund.get("notes", "")

        result = {
            "manager":      manager,
            "name":         name,
            "type":         ftype,
            "identifier":   ticker or isin,
            "yahoo_ticker": None,
            "status":       None,
            "rows":         None,
            "date_start":   None,
            "date_end":     None,
            "notes":        notes,
        }

        # ── Path A: known US ticker ────────────────────────────────────────────
        if ticker:
            df = get_prices(ticker, start=start, use_cache=False)
            if df is not None:
                result.update({
                    "yahoo_ticker": ticker,
                    "status":       "OK",
                    "rows":         len(df),
                    "date_start":   str(df.index[0].date()),
                    "date_end":     str(df.index[-1].date()),
                })
            else:
                result.update({
                    "yahoo_ticker": ticker,
                    "status":       "FAIL — not found on Yahoo",
                })
            rows.append(result)
            continue

        # ── Path B: ISIN-only ─────────────────────────────────────────────────
        # Strategy (in priority order):
        #   1. Yahoo search by ISIN  → catches 0P... internal fund identifiers
        #   2. Yahoo search by name  → fallback if ISIN not indexed
        #   3. OpenFIGI              → exchange-listed tickers (LN, ID, LX …)
        # Small sleep between searches to avoid Yahoo rate-limiting.

        import time as _time

        def _try_symbols(symbols: list[str]) -> Optional[pd.DataFrame]:
            for sym in symbols:
                if not sym:
                    continue
                df = get_prices(sym, start=start, use_cache=False)
                if df is not None:
                    return df, sym
            return None, None

        succeeded = False
        tried: list[str] = []

        # 1. Yahoo search by ISIN
        _time.sleep(1.5)
        ysr = search_yahoo(isin)
        isin_symbols = [r["symbol"] for r in ysr if r["symbol"] not in tried]
        tried += isin_symbols
        df, winning_sym = _try_symbols(isin_symbols)

        # 2. Yahoo search by fund name (if ISIN search missed)
        if df is None:
            _time.sleep(1.5)
            ysr2 = search_yahoo(name)
            name_symbols = [
                r["symbol"] for r in ysr2
                if r["symbol"] not in tried
                # prefer MUTUALFUND / ETF types; skip plain equities
                and r.get("type", "") in ("MUTUALFUND", "ETF", "FUND", "")
            ]
            tried += name_symbols
            df, winning_sym = _try_symbols(name_symbols)

        # 3. OpenFIGI exchange tickers
        if df is None:
            _time.sleep(1.0)
            figi_candidates = lookup_isin(isin)
            preferred = [
                c["yahoo_ticker"] for c in figi_candidates
                if c["exchange_code"] in config.EXCH_YAHOO_SUFFIX
                and c["yahoo_ticker"] not in tried
            ]
            other = [
                c["yahoo_ticker"] for c in figi_candidates
                if c["yahoo_ticker"] not in tried and c["yahoo_ticker"] not in preferred
            ]
            figi_symbols = preferred + other
            tried += figi_symbols
            df, winning_sym = _try_symbols(figi_symbols)

        if df is not None:
            result.update({
                "yahoo_ticker": winning_sym,
                "status":       "OK",
                "rows":         len(df),
                "date_start":   str(df.index[0].date()),
                "date_end":     str(df.index[-1].date()),
            })
            succeeded = True

        if not succeeded:
            tried_str = ", ".join(t for t in tried if t) or "none found"
            result.update({
                "yahoo_ticker": tried_str,
                "status":       "FAIL — not found via Yahoo search, OpenFIGI, or exchange lookup",
            })

        rows.append(result)

    return pd.DataFrame(rows)


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    start_date = sys.argv[1] if len(sys.argv) > 1 else "2018-01-01"
    print(f"\nTesting Yahoo Finance access for all funds (start={start_date}) ...\n")

    results = test_access(start=start_date)

    # ── Print summary table ────────────────────────────────────────────────────
    ok  = results[results["status"] == "OK"]
    bad = results[results["status"] != "OK"]

    pd.set_option("display.max_colwidth", 40)
    pd.set_option("display.width", 140)

    print("=" * 100)
    print(f"ACCESSIBLE via Yahoo Finance  ({len(ok)}/{len(results)})")
    print("=" * 100)
    if not ok.empty:
        print(ok[["manager", "name", "type", "yahoo_ticker", "rows", "date_start", "date_end"]]
              .to_string(index=False))

    print()
    print("=" * 100)
    print(f"NOT ACCESSIBLE — manual NAV required  ({len(bad)}/{len(results)})")
    print("=" * 100)
    if not bad.empty:
        print(bad[["manager", "name", "type", "identifier", "yahoo_ticker", "status"]]
              .to_string(index=False))

    # ── Write results to CSV for reference ────────────────────────────────────
    out = config.BASE_DIR / "data_access_test.csv"
    results.to_csv(out, index=False)
    print(f"\nFull results written to: {out}")
