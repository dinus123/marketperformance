# Market Performance Dashboard

**First version:** 2026-03-31
**Local directory:** `/Users/macbookair2025/Claude-projects/dashboards/marketperformance`

A local Flask performance dashboard for monitoring CTA/managed futures funds, market indices, and UCITS/ETF/40Act funds. Dark-themed single-page application rendered via Jinja2 + Plotly.js.

**Port:** 5055 | **Base currency:** EUR | **Scope:** Returns monitoring (not portfolio construction)

---

## Tabs

| Tab | Purpose |
|---|---|
| Overview | Sortable performance table: MTD, Prev Mo, QTD, Prev Qtr, YTD, 12M, 2025–2023, Vol, AUM, Inception |
| Timeseries | Cumulative return + drawdown charts; date range slider; multi-series overlay; rebased to 100 |
| Calendar | Monthly return heatmap (rows=years, cols=months) + annual bar chart per instrument |
| Stats | Vol, Sharpe (Lo 2002 CI), Sortino, max drawdown, Calmar; rolling window selector |
| Relative | Alpha, beta, tracking error, information ratio, up/down capture vs selected benchmark |
| Correlation | Pairwise correlation heatmap; 1Y / 3Y / 5Y / All windows; green=positive, red=negative |
| Universe | Editable instrument table; add/remove instruments; manual NAV CSV upload |

---

## Stack

- **Backend:** Python 3.11+, Flask, pandas, numpy, scipy, yfinance, pandas-datareader
- **Frontend:** Vanilla JS, Plotly.js, Jinja2 templates
- **Data:** yfinance (listed instruments), FRED (FX rates, risk-free rate), manual NAV CSV upload
- **Theme:** Dark GitHub palette (`#0d1117` background, `#161b22` cards)

---

## Architecture

```
marketperformance/
├── app.py              # Flask routes + API endpoints only; no business logic
├── config.py           # All configurable constants (tickers, port, FRED IDs, cache TTL)
├── data_engine.py      # yfinance download, FX conversion, file cache, threading
├── perf_engine.py      # All performance calculations (pure Python; no Flask imports)
├── universe.json       # Instrument universe (editable via UI)
├── data/
│   ├── cache/          # File-based pickle cache; TTL-managed; never deleted on restart
│   └── manual/         # Drop zone for manually uploaded UCITS NAV CSVs
├── templates/          # Jinja2 tab templates (one file per tab)
├── static/
│   ├── dashboard.css
│   └── dashboard.js    # All client-side logic; App state object; Plotly renders
└── tests/              # pytest suite (148 tests); covers perf_engine + all API endpoints
```

---

## Performance Metrics

| Metric | Formula |
|---|---|
| CAGR | `(1 + mean_daily)^252 − 1` |
| Volatility | `std_daily × √252` |
| Sharpe | `(CAGR − rf) / vol` with Lo (2002) 95% CI |
| Sortino | `(CAGR − rf) / downside_vol` |
| Max Drawdown | Rolling peak-to-trough |
| Calmar | `CAGR / |max_dd|` |
| Alpha (Jensen) | OLS intercept × 252 vs selected benchmark |
| Information Ratio | `(CAGR_i − CAGR_b) / tracking_error` |

All annualisation: ×252 (daily). Never ×365 or ×12.

---

## Setup

```bash
pip install flask pandas numpy scipy yfinance pandas-datareader plotly
python app.py
# → http://localhost:5055
```

---

## Testing

```bash
pytest tests/ -v
# 148 tests; covers all perf_engine functions + all API endpoints
```

---

## Universe

20-instrument CTA/managed futures universe:
- 15 active instruments: 6 US-ticker ETFs/funds, 9 UCITS via Yahoo 0P... fund IDs
- 4 manual CSV (UCITS NAV upload)
- 1 inactive (bad ticker)

Data sources tagged in `universe.json`: `yfinance` | `manual_csv` | `yfinance_proxy`
Manual NAV series labelled `[M]`; ETF-as-index proxies labelled `[P]`.
