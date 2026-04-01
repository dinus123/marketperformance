"""
api/prices.py  —  Vercel serverless function
Fetches monthly OHLC + FX data via yfinance and returns JSON.
Deployed automatically by Vercel from GitHub.
"""

from http.server import BaseHTTPRequestHandler
import json, yfinance as yf, pandas as pd
from datetime import date

# ── Instrument universe (yfinance-capable only) ───────────────────────────────
INSTRUMENTS = [
    # 40 Act
    {"id": "AQMIX",         "ticker": "AQMIX",          "ccy": "USD"},
    {"id": "EBSIX",         "ticker": "EBSIX",           "ccy": "USD"},
    {"id": "ABYIX",         "ticker": "ABYIX",           "ccy": "USD"},
    {"id": "ASFYX",         "ticker": "ASFYX",           "ccy": "USD"},
    {"id": "PQTIX",         "ticker": "PQTIX",           "ccy": "USD"},
    # ETF
    {"id": "KMLM",          "ticker": "KMLM",            "ccy": "USD"},
    {"id": "DBMF",          "ticker": "DBMF",            "ccy": "USD"},
    {"id": "SIMPLIFY_CTA",  "ticker": "CTA",             "ccy": "USD"},
    # UCITS
    {"id": "MAN_AHL_TREND", "ticker": "0P0000P7NF",      "ccy": "USD"},
    {"id": "WINTON_MULTI",  "ticker": "0P0001ALX2",      "ccy": "USD"},
    {"id": "ASPECT_CORE",   "ticker": "0P0001P6TV",      "ccy": "USD"},
    {"id": "CRABEL_UCITS",  "ticker": "0P0001BGJU",      "ccy": "USD"},
    {"id": "SCHRODER_GAIA", "ticker": "0P000177IX",      "ccy": "USD"},
    {"id": "CRABEL_GEMINI", "ticker": "0P0001BGK2",      "ccy": "USD"},
    {"id": "AMUNDI_WNT",    "ticker": "0P0001NCH3",      "ccy": "USD"},
    {"id": "MAN_AHL_ALPHA", "ticker": "0P0001CTOR",      "ccy": "USD"},
    {"id": "LYNX_UCITS",    "ticker": "0P0001HIS7.F",    "ccy": "EUR"},
    {"id": "CANDRIAM_DIV",  "ticker": "0P0000NA4A.F",    "ccy": "EUR"},
    {"id": "DUNN_WMA",      "ticker": "0P0001840K.F",    "ccy": "EUR"},
    {"id": "WINTON_ALMA",   "ticker": "0P0000RT99.L",    "ccy": "GBP"},
    # Benchmarks
    {"id": "SPY",           "ticker": "SPY",             "ccy": "USD"},
    {"id": "ACWI",          "ticker": "ACWI",            "ccy": "USD"},
    {"id": "AGG",           "ticker": "AGG",             "ccy": "USD"},
    {"id": "GLD",           "ticker": "GLD",             "ccy": "USD"},
]

# FRED tickers via yfinance proxy
FX_TICKERS = {
    "usd_eur": "DEXUSEU",   # USD per EUR  (invert → EUR per USD)
    "gbp_eur": "DEXGBEU",   # GBP per EUR  (invert → EUR per GBP)
}

START = "2010-01-01"


def fetch_prices() -> dict:
    tickers = [i["ticker"] for i in INSTRUMENTS]
    raw = yf.download(
        tickers, start=START, end=str(date.today()),
        interval="1mo", auto_adjust=True, progress=False
    )["Close"]

    # Normalise to {id: {YYYY-MM-DD: float}}
    prices = {}
    for inst in INSTRUMENTS:
        t = inst["ticker"]
        if t not in raw.columns:
            continue
        s = raw[t].dropna()
        if len(s) < 2:
            continue
        prices[inst["id"]] = {
            d.strftime("%Y-%m-%d"): round(float(v), 4)
            for d, v in s.items()
        }
    return prices


def fetch_fx() -> dict:
    fx = {}
    for key, fred_id in FX_TICKERS.items():
        try:
            s = yf.download(fred_id, start=START, interval="1mo",
                            auto_adjust=False, progress=False)["Close"].dropna()
            fx[key] = {
                d.strftime("%Y-%m-%d"): round(float(v), 6)
                for d, v in s.items()
            }
        except Exception:
            fx[key] = {}
    return fx


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        try:
            prices = fetch_prices()
            fx     = fetch_fx()
            body   = json.dumps({"prices": prices, "fx": fx}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")   # allow artifact to call
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
