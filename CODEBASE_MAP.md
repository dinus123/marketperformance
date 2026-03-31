# Codebase Map

Living index of all project files. **Update this file whenever a file is created, deleted, or significantly refactored.**
Claude reads this at session start instead of scanning the directory. Keep descriptions tight — one line per file.

---

## Status
`[PLANNED]` = not yet created | `[EXISTS]` = created | `[STUB]` = skeleton only

---

## Backend — Python

| File | Status | Purpose | Key symbols |
|---|---|---|---|
| `app.py` | EXISTS | Flask routes + API endpoints; _price_cache populated at startup | `/api/overview`, `/api/timeseries`, `/api/stats`, `/api/calendar`, `/api/relative`, `/api/correlation`, `/api/refresh`, `/api/upload-nav` |
| `config.py` | EXISTS | All configurable constants: port, paths, FRED series IDs, cache TTL, Yahoo exchange suffix map | `PORT`, `UNIVERSE_FILE`, `CACHE_DIR`, `FRED_SERIES`, `EXCH_YAHOO_SUFFIX` |
| `perf_engine.py` | EXISTS | All performance calculations (pure Python, no Flask) | `calc_returns_table`, `calc_stats`, `calc_calendar`, `calc_relative`, `calc_correlation`, `mtd`, `qtd`, `prev_month_return`, `prev_quarter_return`, `calendar_year_return`, `inception_date`, `aum_from_ticker` |
| `data_engine.py` | EXISTS | yfinance download, Yahoo search (0P... fund IDs), OpenFIGI ISIN lookup, file cache, threading | `get_prices()`, `search_yahoo()`, `lookup_isin()`, `test_access()`, `load_universe()` |
| `universe.json` | EXISTS | 20-fund CTA universe. 15 active (6 US-ticker, 9 UCITS via 0P... Yahoo IDs). 4 manual CSV. 1 bad ticker (GQSXX, inactive). | schema: id, ticker, isin, currency, data_source, active |

## Frontend — Templates

| File | Status | Purpose |
|---|---|---|
| `templates/base.html` | EXISTS | Shell: nav tabs (Overview/Timeseries/Calendar/Stats/Relative/Correlation/Universe) |
| `templates/tab_overview.html` | EXISTS | Sortable table: Fund/Manager/Type/CCY/MTD/Prev Mo/QTD/Prev Qtr/YTD/12M/2025/2024/2023/Vol/AUM/Inception + Last Updated + Refresh button |
| `templates/tab_timeseries.html` | EXISTS | Cumulative return + drawdown Plotly charts; date range slider; multi-series; rebased to 100 at window start |
| `templates/tab_calendar.html` | EXISTS | Monthly heatmap (rows=years, cols=months) + annual bar chart |
| `templates/tab_stats.html` | EXISTS | Vol, Sharpe+CI, Sortino, max DD, Calmar; rolling window selector |
| `templates/tab_relative.html` | EXISTS | Alpha, beta, TE, IR, up/down capture vs selected benchmark |
| `templates/tab_universe.html` | EXISTS | Editable instrument table; add/remove; manual NAV CSV upload |
| `templates/tab_corr.html` | EXISTS | Pairwise correlation heatmap; window dropdown (1Y/3Y/5Y/All); red=positive, blue=negative |

## Frontend — Static

| File | Status | Purpose | Key symbols |
|---|---|---|---|
| `static/dashboard.css` | EXISTS | Dark GitHub theme; tab panel show/hide; table styles; .corr-* rules; .pos/.neg/.num-col | CSS vars for colors |
| `static/dashboard.js` | EXISTS | All client JS; App state object; tab routing; Plotly renders | `App`, `overviewTab`, `corrTab`, `timeseriesTab`, `calendarTab`, `statsTab`, `relativeTab` |

## Data

| Path | Status | Purpose |
|---|---|---|
| `data/cache/` | PLANNED | File-based pickle cache; TTL-managed; never delete on restart |
| `data/manual/` | PLANNED | Drop zone for manually uploaded UCITS NAV CSVs |

## Config & Infra

| File | Status | Purpose |
|---|---|---|
| `.gitignore` | EXISTS | Excludes cache, venv, __pycache__, .env, manual NAV CSVs |
| `CLAUDE.md` | EXISTS | Claude Code project rules + session protocol |
| `MASTER_PROMPT.md` | EXISTS | Full project spec (architecture, universe, formulas, conventions) |
| `DECISIONS.md` | EXISTS | Architecture decision log |
| `CODEBASE_MAP.md` | EXISTS | This file |
| `requirements.txt` | PLANNED | Pinned dependencies |

---

## API Endpoints (planned)

| Method | Path | Handler | Returns |
|---|---|---|---|
| GET | `/` | `index` | Renders `base.html` |
| GET | `/api/universe` | `get_universe` | JSON array of instruments |
| POST | `/api/universe` | `update_universe` | Updated universe |
| GET | `/api/returns` | `get_returns` | `{id: {window: pct}}` for all active instruments |
| GET | `/api/timeseries?ids=...&start=...&end=...` | `get_timeseries` | `{id: {dates, cum_ret, drawdown}}` |
| GET | `/api/stats?ids=...&start=...&end=...` | `get_stats` | `{id: {cagr, vol, sharpe, sharpe_ci_lo, sharpe_ci_hi, ...}}` |
| GET | `/api/calendar?id=...` | `get_calendar` | `{year: {month: pct, ann: pct}}` |
| GET | `/api/relative?id=...&bench=...` | `get_relative` | `{alpha, beta, te, ir, up_cap, dn_cap}` |
| POST | `/api/upload-nav` | `upload_nav` | `{status, rows_loaded}` |

---

## Known Issues / Tech Debt
_Add entries here as they arise — prevents re-diagnosing the same issue._

| Date | File | Issue | Status |
|---|---|---|---|
| — | — | — | — |
