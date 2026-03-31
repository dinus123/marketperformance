"""
config.py — All configurable constants. Import everywhere; never hardcode elsewhere.
"""
from pathlib import Path

# ── Server ─────────────────────────────────────────────────────────────────────
PORT = 5055

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
CACHE_DIR   = BASE_DIR / "data" / "cache"
MANUAL_DIR  = BASE_DIR / "data" / "manual"
UNIVERSE_FILE = BASE_DIR / "universe.json"

# ── Data ───────────────────────────────────────────────────────────────────────
DEFAULT_START    = "2010-01-01"
CACHE_TTL        = 86_400          # 24 h in seconds
MIN_ROWS         = 20              # minimum observations to consider a series valid
OPENFIGI_URL     = "https://api.openfigi.com/v3/mapping"
OPENFIGI_TIMEOUT = 10              # seconds

# ── FRED series ────────────────────────────────────────────────────────────────
FRED_SERIES = {
    "rf":      "TB3MS",       # 3-month T-bill (risk-free rate proxy)
    "usd_eur": "DEXUSEU",     # USD per EUR
    "gbp_eur": "DEXGBEU",     # GBP per EUR
}

# ── Annualisation ──────────────────────────────────────────────────────────────
TRADING_DAYS = 252             # ONLY valid multiplier — never 365 or 12

# ── OpenFIGI exchange → Yahoo Finance suffix map ───────────────────────────────
EXCH_YAHOO_SUFFIX = {
    "LN": ".L",    # London Stock Exchange
    "LX": ".LU",   # Luxembourg
    "ID": ".IR",   # Euronext Dublin (Irish)
    "GY": ".DE",   # Xetra
    "FP": ".PA",   # Euronext Paris
    "NA": ".AS",   # Euronext Amsterdam
    "SM": ".MC",   # Madrid
    "SW": ".SW",   # SIX Swiss
}
