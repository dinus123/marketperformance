"""
app.py — Flask routes and API endpoints only.
No business logic here — all calculations delegate to perf_engine.py.
All data I/O delegates to data_engine.py.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, abort

import config
import data_engine as de
import perf_engine as pe

# ── App setup ──────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
CACHE_VERSION = int(time.time())

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


# ── Context processor: inject cache-busting version ───────────────────────────

@app.context_processor
def inject_version():
    return {"v": CACHE_VERSION}


@app.after_request
def no_cache_api(response):
    """Prevent browser from caching API JSON responses."""
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ── Price cache (module-level, populated at startup) ──────────────────────────
# Keys = fund id (from universe.json), values = pd.Series of Close prices.
# Manual-CSV funds with no file → empty Series (never None, prevents repeated None checks).

_price_cache: dict[str, pd.Series] = {}


def _load_price_cache() -> None:
    """
    Pre-load all active funds into _price_cache on server startup.
    yfinance funds: fetch via data_engine.get_prices().
    manual_csv funds: read from data/manual/{id}.csv if present, else empty Series.
    Inactive funds: skipped.
    """
    universe = de.load_universe()
    total = sum(1 for f in universe if f.get("active", True))
    logger.info("Loading price cache for %d active funds…", total)

    for fund in universe:
        fid = fund["id"]
        if not fund.get("active", True):
            continue

        src = fund.get("data_source", "yfinance")

        if src == "manual_csv":
            _price_cache[fid] = _load_manual_csv(fid)
            continue

        # yfinance (ticker may be None for some manual funds mis-labelled)
        ticker = fund.get("ticker")
        if not ticker:
            _price_cache[fid] = pd.Series(dtype=float)
            continue

        df = de.get_prices(ticker, start=config.DEFAULT_START)
        if df is not None and not df.empty:
            series = df.iloc[:, 0]
            series.name = fid
            _price_cache[fid] = series
        else:
            logger.warning("No data for %s (ticker=%s)", fid, ticker)
            _price_cache[fid] = pd.Series(dtype=float)

    ok = sum(1 for s in _price_cache.values() if not s.empty)
    logger.info("Price cache ready: %d/%d funds have data.", ok, len(_price_cache))


def _load_manual_csv(fid: str) -> pd.Series:
    """Read data/manual/{fid}.csv → pd.Series indexed by date. Returns empty if missing."""
    path = config.MANUAL_DIR / f"{fid}.csv"
    if not path.exists():
        return pd.Series(dtype=float, name=fid)
    try:
        df = pd.read_csv(path, parse_dates=["date"], index_col="date")
        df.sort_index(inplace=True)
        # accept 'nav' or 'close' or 'price' column names
        for col in ("nav", "close", "price", "NAV", "Close", "Price"):
            if col in df.columns:
                s = df[col].dropna()
                s.name = fid
                return s
        logger.warning("manual CSV %s has no recognised price column", path)
        return pd.Series(dtype=float, name=fid)
    except Exception as e:
        logger.warning("Error loading manual CSV %s: %s", path, e)
        return pd.Series(dtype=float, name=fid)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_float(v) -> float | None:
    """Convert numpy/pandas scalar to Python float; None if NaN/inf."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _serialise(obj):
    """JSON-safe recursive converter for dicts/lists with numpy scalars."""
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialise(v) for v in obj]
    if isinstance(obj, str):
        return obj
    return _safe_float(obj)


def _fund_map() -> dict[str, dict]:
    """Return universe as dict keyed by fund id."""
    return {f["id"]: f for f in de.load_universe()}


# ── HTML routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    universe = de.load_universe()
    return render_template("base.html", universe=universe)


@app.route("/universe")
def universe_page():
    universe = de.load_universe()
    return render_template("tab_universe.html", universe=universe)


# ── API: universe ─────────────────────────────────────────────────────────────

@app.route("/api/universe", methods=["GET"])
def get_universe():
    return jsonify(de.load_universe())


@app.route("/api/universe", methods=["POST"])
def update_universe():
    data = request.get_json()
    if not isinstance(data, list):
        abort(400, "Expected JSON array")
    de.save_universe(data)
    return jsonify({"status": "ok"})


# ── API: returns (overview table) ─────────────────────────────────────────────

@app.route("/api/returns")
def get_returns():
    """
    GET /api/returns?window=1M|3M|6M|YTD|1Y|3Y|5Y|All
    Returns {fund_id: {return: float|null, currency: str}} for all active funds.
    """
    window = request.args.get("window", "YTD")
    fund_meta = _fund_map()
    result = {}
    for fid, prices in _price_cache.items():
        meta = fund_meta.get(fid, {})
        ret = pe.period_return(prices, window) if not prices.empty else None
        result[fid] = {
            "return":   _safe_float(ret),
            "currency": meta.get("currency", "USD"),
        }
    return jsonify(result)


# ── API: timeseries ───────────────────────────────────────────────────────────

@app.route("/api/timeseries")
def get_timeseries():
    """
    GET /api/timeseries?ids=id1,id2&start=YYYY-MM-DD&end=YYYY-MM-DD
    Returns {id: {dates, prices_100, drawdown}} — prices rebased to 100 at start.
    """
    ids_raw = request.args.get("ids", "")
    ids = [i.strip() for i in ids_raw.split(",") if i.strip()]
    start = request.args.get("start", config.DEFAULT_START)
    end = request.args.get("end", None)

    if not ids:
        # default: return all funds with data
        ids = [fid for fid, s in _price_cache.items() if not s.empty]

    result = {}
    for fid in ids:
        prices = _price_cache.get(fid)
        if prices is None or prices.empty:
            result[fid] = {"dates": [], "prices_100": [], "drawdown": []}
            continue

        rebased = pe.rebase_to_window(prices, start)
        if end:
            rebased = rebased.loc[rebased.index <= pd.Timestamp(end)]

        if rebased.empty:
            result[fid] = {"dates": [], "prices_100": [], "drawdown": []}
            continue

        dd = pe.drawdown_series(rebased)
        result[fid] = {
            "dates":     [d.strftime("%Y-%m-%d") for d in rebased.index],
            "prices_100": [round(float(v), 4) for v in rebased.values],
            "drawdown":  [round(float(v), 6) for v in dd.values],
        }

    return jsonify(result)


# ── API: stats ────────────────────────────────────────────────────────────────

@app.route("/api/stats")
def get_stats():
    """
    GET /api/stats?ids=id1,id2&start=YYYY-MM-DD
    Returns {id: {cagr, vol, sharpe, sharpe_lo, sharpe_hi, sortino, max_dd, calmar, skew, kurt, n_obs}}
    """
    ids_raw = request.args.get("ids", "")
    ids = [i.strip() for i in ids_raw.split(",") if i.strip()]
    start = request.args.get("start", None)

    if not ids:
        ids = list(_price_cache.keys())

    result = {}
    for fid in ids:
        prices = _price_cache.get(fid)
        if prices is None or prices.empty:
            result[fid] = pe._empty_stats()
            continue

        sub = prices if start is None else prices.loc[prices.index >= pd.Timestamp(start)]
        result[fid] = _serialise(pe.calc_stats(sub))

    return jsonify(result)


# ── API: calendar ─────────────────────────────────────────────────────────────

@app.route("/api/calendar")
def get_calendar():
    """
    GET /api/calendar?id=FUND_ID
    Returns {year: {1..12: pct, ann: pct}}
    """
    fid = request.args.get("id")
    if not fid:
        abort(400, "id parameter required")

    prices = _price_cache.get(fid)
    cal = pe.calc_calendar(prices) if prices is not None else {}
    return jsonify(cal)


# ── API: relative ─────────────────────────────────────────────────────────────

@app.route("/api/relative")
def get_relative():
    """
    GET /api/relative?id=FUND_ID&bench=BENCH_ID&start=YYYY-MM-DD
    Returns {alpha, beta, te, ir, up_cap, dn_cap, rolling_beta: {dates, values}}
    """
    fid = request.args.get("id")
    bench_id = request.args.get("bench", "AQMIX")
    start = request.args.get("start", None)

    if not fid:
        abort(400, "id parameter required")

    fund_prices = _price_cache.get(fid)
    bench_prices = _price_cache.get(bench_id)

    result = pe.calc_relative(fund_prices, bench_prices, start_date=start)
    return jsonify(_serialise(result))


# ── API: fund detail (modal) ──────────────────────────────────────────────────

@app.route("/api/fund_detail")
def get_fund_detail():
    """
    GET /api/fund_detail?id=FUND_ID
    Combined: timeseries (rebased to 100 from All), all stats periods, calendar, relative vs AQMIX.
    """
    fid = request.args.get("id")
    if not fid:
        abort(400, "id parameter required")

    prices = _price_cache.get(fid)
    fund_meta = _fund_map().get(fid, {})

    if prices is None or prices.empty:
        return jsonify({
            "id": fid, "meta": fund_meta,
            "timeseries": {"dates": [], "prices_100": [], "drawdown": []},
            "stats": {}, "calendar": {}, "relative": pe._empty_relative(),
        })

    # Timeseries (all history)
    rebased = pe.rebase_to_window(prices, str(prices.index[0].date()))
    dd = pe.drawdown_series(rebased)
    ts = {
        "dates":     [d.strftime("%Y-%m-%d") for d in rebased.index],
        "prices_100": [round(float(v), 4) for v in rebased.values],
        "drawdown":  [round(float(v), 6) for v in dd.values],
    }

    # Stats for multiple windows
    windows = ["1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "All"]
    stats_by_window = {}
    for w in windows:
        start_dt = pe._window_start(prices, w)
        sub = prices if start_dt is None else prices.loc[prices.index >= start_dt]
        stats_by_window[w] = {
            **_serialise(pe.calc_stats(sub)),
            "period_return": _safe_float(pe.period_return(prices, w)),
        }

    # Calendar
    calendar = pe.calc_calendar(prices)

    # Relative vs AQMIX (default benchmark)
    bench_prices = _price_cache.get("AQMIX", pd.Series(dtype=float))
    relative = _serialise(pe.calc_relative(prices, bench_prices))

    return jsonify({
        "id": fid,
        "meta": fund_meta,
        "timeseries": ts,
        "stats": stats_by_window,
        "calendar": calendar,
        "relative": relative,
    })


# ── API: overview table data ───────────────────────────────────────────────────

def _get_last_updated() -> str:
    """Date of most recent price point across all loaded funds."""
    dates = [s.index[-1] for s in _price_cache.values() if s is not None and not s.empty]
    if not dates:
        return "N/A"
    return max(dates).strftime("%Y-%m-%d")


@app.route("/api/overview")
def get_overview():
    """
    GET /api/overview
    Full overview table: MTD, Prev Month, QTD, Prev Qtr, YTD, 12M, 2025, 2024, 2023,
    Vol (trailing 252d), AUM, Inception.
    Returns {rows: [...], last_updated: str}
    """
    fund_meta = _fund_map()
    universe = de.load_universe()

    rows = []
    # Global reference date: most recent price point across all funds.
    # Passed to period functions so all funds compute MTD/QTD relative to the same date.
    _lu = _get_last_updated()
    ref_date = pd.Timestamp(_lu) if _lu else None

    for fid, prices in _price_cache.items():
        meta = fund_meta.get(fid, {})
        if not meta.get("active", True) or meta.get("data_source") == "manual_csv":
            continue
        has_data = prices is not None and not prices.empty

        row = {
            "id":        fid,
            "name":      meta.get("name", fid),
            "manager":   meta.get("manager", ""),
            "type":      meta.get("instrument_type", ""),
            "currency":  meta.get("currency", "USD"),
            "has_data":  has_data,
            "last_date": prices.index[-1].strftime("%Y-%m-%d") if has_data else None,
        }

        if has_data:
            row["mtd"]        = _safe_float(pe.mtd(prices, ref_date))
            row["prev_month"] = _safe_float(pe.prev_month_return(prices, ref_date))
            row["qtd"]        = _safe_float(pe.qtd(prices, ref_date))
            row["prev_qtr"]   = _safe_float(pe.prev_quarter_return(prices, ref_date))
            row["ytd"]        = _safe_float(pe.period_return(prices, "YTD"))
            row["ret_12m"]    = _safe_float(pe.period_return(prices, "1Y"))
            row["ret_2025"]   = _safe_float(pe.calendar_year_return(prices, 2025))
            row["ret_2024"]   = _safe_float(pe.calendar_year_return(prices, 2024))
            row["ret_2023"]   = _safe_float(pe.calendar_year_return(prices, 2023))
            _freq_label, _ann = pe.detect_freq(prices)
            row["vol"]        = _safe_float(pe.vol(pe.returns_from_prices(prices).iloc[-_ann:], ann_factor=_ann))
            row["freq"]       = _freq_label
            row["inception"]  = pe.inception_date(prices)
        else:
            for k in ["mtd", "prev_month", "qtd", "prev_qtr", "ytd", "ret_12m",
                      "ret_2025", "ret_2024", "ret_2023", "vol", "inception", "freq"]:
                row[k] = None

        row["aum"] = None  # fetched lazily via /api/refresh, not at render time
        rows.append(row)

    last_updated = _get_last_updated()
    return jsonify({"rows": rows, "last_updated": last_updated})


@app.route("/api/refresh", methods=["POST"])
def refresh_data():
    """Re-download all yfinance prices (bypass cache) and reload _price_cache."""
    universe = de.load_universe()
    reloaded = 0
    for fund in universe:
        if not fund.get("active", True):
            continue
        fid = fund["id"]
        src = fund.get("data_source", "yfinance")
        ticker = fund.get("ticker")
        if src == "yfinance" and ticker:
            df = de.get_prices(ticker, start=config.DEFAULT_START, use_cache=False)
            if df is not None and not df.empty:
                s = df.iloc[:, 0]
                s.name = fid
                _price_cache[fid] = s
                reloaded += 1
            else:
                _price_cache[fid] = pd.Series(dtype=float)
    last_updated = _get_last_updated()
    return jsonify({"status": "ok", "reloaded": reloaded, "last_updated": last_updated})


# ── API: correlation matrix ───────────────────────────────────────────────────

@app.route("/api/correlation")
def get_correlation():
    """GET /api/correlation?window=1Y|3Y|5Y|All"""
    window = request.args.get("window", "3Y")
    fm = _fund_map()
    filtered_cache = {fid: v for fid, v in _price_cache.items()
                      if fm.get(fid, {}).get("data_source") != "manual_csv"}
    result = pe.calc_correlation(filtered_cache, window=window)
    result["names"] = [fm.get(fid, {}).get("name", fid) for fid in result["ids"]]
    return jsonify(result)


# ── API: upload manual NAV ────────────────────────────────────────────────────

@app.route("/api/upload-nav", methods=["POST"])
def upload_nav():
    """
    POST /api/upload-nav
    Multipart form: fund_id (str) + file (CSV with date + nav/close/price column).
    Saves to data/manual/{fund_id}.csv and reloads price cache for that fund.
    """
    fund_id = request.form.get("fund_id", "").strip()
    if not fund_id:
        abort(400, "fund_id required")
    if "file" not in request.files:
        abort(400, "file required")

    f = request.files["file"]
    config.MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.MANUAL_DIR / f"{fund_id}.csv"
    f.save(str(dest))

    # Reload into cache
    _price_cache[fund_id] = _load_manual_csv(fund_id)
    rows = len(_price_cache[fund_id])
    logger.info("Uploaded NAV for %s: %d rows", fund_id, rows)

    return jsonify({"status": "ok", "fund_id": fund_id, "rows_loaded": rows})


# ── Startup ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _load_price_cache()
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
