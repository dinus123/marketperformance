# Market Performance Dashboard — Master Prompt

## Project Brief

Build and maintain a local Flask performance dashboard (`http://localhost:5055`) for monitoring
market indices and a curated universe of UCITS, ETF, and 40 Act funds. Dark-themed SPA rendered
via Jinja2 templates and Plotly.js.

**Owner**: Jeppe Furbo Ladekarl
**Base currency**: EUR (all returns converted unless toggled)
**Purpose**: Comparative performance monitoring, not portfolio risk decomposition.
Companion to `portfolio_optimizer_2` (risk dashboard); this dashboard is returns-first.

---

## Architecture

```
marketperformance/
├── app.py                    # Flask: routes + API endpoints only, no business logic
├── config.py                 # All configurable parameters (tickers, lookbacks, port, universe)
├── data_engine.py            # Download, FX conversion, caching, threading
├── perf_engine.py            # All performance calculations (pure Python, no Flask imports)
├── universe.json             # Fund/index universe definition (editable via UI)
├── data/
│   └── cache/                # File-based cache (pickle, TTL-managed)
│   └── manual/               # Drop zone for manually uploaded NAV CSVs (UCITS funds)
├── templates/
│   ├── base.html             # Shell: header, nav tabs, footer
│   └── tab_*.html            # One file per tab (see Tabs section)
└── static/
    ├── dashboard.css
    └── dashboard.js          # All client-side logic; single file
```

---

## Tabs (exhaustive — do not add or remove without explicit instruction)

| Tab | One-line purpose |
|---|---|
| Overview | YTD / 1M / 3M / 1Y / 3Y / 5Y return cards; sortable performance table |
| Timeseries | Cumulative return chart; drawdown chart; multi-series overlay; date range slider |
| Calendar | Annual and monthly return heatmaps per instrument |
| Risk/Stats | Volatility, Sharpe (with CI), Sortino, max drawdown, Calmar; rolling windows |
| Relative | Benchmark-relative: alpha, beta, tracking error, information ratio, up/down capture |
| Universe | Editable fund/index table; add/remove instruments; manual NAV upload |

---

## Fund Universe (initial seed — expand via Universe tab)

### Market Indices
| Name | Ticker | Currency | Notes |
|---|---|---|---|
| S&P 500 | ^GSPC | USD | |
| MSCI World (proxy) | IWDA.AS | USD | ETF proxy; use as MSCI World |
| MSCI EM | IEEM.AS | USD | ETF proxy |
| Euro Stoxx 50 | ^STOXX50E | EUR | |
| FTSE 100 | ^FTSE | GBP | |
| Nasdaq 100 | ^NDX | USD | |
| Bloomberg Global Agg (proxy) | AGG | USD | USD IG agg proxy |

### ETFs
| Name | Ticker | ISIN | Currency | Type |
|---|---|---|---|---|
| iShares Core MSCI World | IWDA.AS | IE00B4L5Y983 | USD | ETF (physical) |
| iShares Core MSCI EM | IEEM.AS | IE00B0M63177 | USD | ETF (physical) |
| iShares $ Treasury Bond 20yr+ | IDTL.L | IE00B1FZS798 | USD | ETF (physical) |
| iShares EUR Inflation Linked | IBCI.AS | IE00B0M62X26 | EUR | ETF (physical) |
| iShares Physical Gold | IAUS.L | IE00B4ND3602 | USD | ETC (physical) |
| iShares MSCI Europe | IEUR.AS | IE00B4K48X80 | EUR | ETF (physical) |
| iShares Bloomberg Commodity | ICOM.L | IE00BDFL4P12 | USD | ETF (swap-based) |

### UCITS / 40 Act Funds (initial)
| Name | Ticker | ISIN | Currency | Type | Notes |
|---|---|---|---|---|---|
| Aspect Diversified (UCITS) | AHLT.L | IE00BYVJRP78 | USD | UCITS Fund | CTA / managed futures |
| Schroder GAIA Cat Bond | — | LU0424370004 | USD | UCITS Fund | NAV via manual upload |

> **Data sourcing rule**: yfinance for listed instruments. For unlisted UCITS with no exchange ticker,
> accept manual NAV CSV upload (date, nav columns). Tag source in universe.json.

---

## Data Model

### universe.json schema (per instrument)
```json
{
  "id": "IWDA",
  "name": "iShares Core MSCI World",
  "ticker": "IWDA.AS",
  "isin": "IE00B4L5Y983",
  "instrument_type": "ETF (physical)",
  "asset_class": "DM Equity",
  "currency": "USD",
  "ter_bps": 20,
  "data_source": "yfinance",
  "active": true,
  "notes": ""
}
```
`data_source` values: `"yfinance"` | `"manual_csv"` | `"yfinance_proxy"` (when using ETF as index proxy).

### Return series conventions
- **Frequency**: daily (closing prices / NAVs)
- **Return type**: total return where available (`auto_adjust=True` in yfinance)
- **Currency conversion**: ECB reference rates via FRED (`DEXUSEU`, `DEXGBEU`) or yfinance FX pairs
- **Base**: EUR unless user toggles to local currency per instrument
- **Annualisation**: ×252 for vol; `(1+r_d)^252 - 1` for CAGR. Never ×365 or ×12.

---

## Performance Calculations (perf_engine.py)

All functions are pure Python (pandas/numpy in, dict/DataFrame out). No Flask imports.

### Return windows (all trailing, business-day end)
`1W | 1M | 3M | 6M | YTD | 1Y | 3Y | 5Y | ITD`

### Per-instrument stats
| Metric | Formula | Notes |
|---|---|---|
| CAGR | `(1+mean_d)^252 - 1` | |
| Volatility | `std_d × √252` | |
| Sharpe | `(CAGR - rf) / vol` | rf = annualised TB3MS from FRED |
| Sharpe CI | Lo (2002): `se = √((1 + 0.5×SR_d²)/n) × √252` | 95% CI |
| Sortino | `(CAGR - rf) / downside_vol` | downside_vol: semi-deviation, annualised |
| Max Drawdown | rolling peak-to-trough | calendar days between peak and trough |
| Calmar | `CAGR / abs(max_dd)` | |
| Skewness | `scipy.stats.skew(r_d)` | |
| Excess Kurtosis | `scipy.stats.kurtosis(r_d)` | Fisher definition |

### Benchmark-relative stats (Relative tab)
| Metric | Formula |
|---|---|
| Alpha (Jensen) | OLS intercept ×252 |
| Beta | OLS slope |
| Tracking Error | `std(r_i - r_b) × √252` |
| Information Ratio | `(CAGR_i - CAGR_b) / TE` |
| Up-capture | mean(r_i \| r_b > 0) / mean(r_b \| r_b > 0) |
| Down-capture | mean(r_i \| r_b < 0) / mean(r_b \| r_b < 0) |

Default benchmark: S&P 500 (^GSPC). User-selectable per instrument.

---

## Calendar Tab

- **Monthly heatmap**: rows = years, columns = Jan–Dec + Ann. Color scale: red (negative) → green (positive). Symmetric around 0.
- **Annual bar chart**: side-by-side bars for selected instruments vs benchmark.
- Monthly returns aggregated from daily: `prod(1 + r_d) - 1` per month.
- Annual: `prod(1 + r_m) - 1` per calendar year.
- Incomplete current year labeled as "YTD".

---

## Caching (data_engine.py)

- File-based pickle cache in `data/cache/`. Filename: `{ticker}_{start}_{end}.pkl`.
- TTL: 24h for daily price data. Intraday: not used.
- Thread safety: one download per ticker at a time (`threading.Lock` per ticker).
- Manual NAV CSVs: read from `data/manual/`, never overwritten by yfinance downloads.
- FX rates: cached separately with 24h TTL.

---

## Frontend Conventions

### Theme
Dark GitHub palette — identical to portfolio_optimizer_2. See CLAUDE.md for exact hex values.

### Tabs
CSS `.tab-panel {display:none}` / `.tab-panel.active {display:block}`. Lazy Plotly render on
tab activation via `App.rendered['tab']` latch (set AFTER successful render).

### Overview table
Sortable by any return column. Columns: Name | Type | Currency | 1M | 3M | YTD | 1Y | 3Y | Vol | Sharpe.
Color cells: positive green, negative red, zero neutral. Threshold: >0 / <0.

### Plotly defaults (apply to every chart)
```js
const LAYOUT_DEFAULTS = {
  paper_bgcolor: '#0d1117',
  plot_bgcolor: '#161b22',
  font: {color: '#e6edf3', family: 'Menlo,Monaco,monospace', size: 11},
  margin: {t: 30, r: 20, b: 40, l: 60}
};
```

### Number formatting
- Returns: `+12.3%` / `-4.1%` with sign; 1 decimal place in tables, 2 in detail cards
- Vol / TE: `14.2%` (no sign)
- Sharpe / IR: `0.72 [0.48–0.96]` (CI inline)
- Drawdown: `-27.5%` (always negative sign)

---

## Key Implementation Notes

1. **annualise ×252 only** — no ×365, no ×12, no shortcuts
2. **Currency toggle** — always display label; never silently present USD returns as EUR
3. **Incomplete periods** — label partial-year returns as "YTD", partial-month as "MTD"
4. **NAV series** sourced from manual CSV: tag `[M]` in all display labels
5. **Proxy instruments** (ETF used as index proxy): tag `[P]` in display labels
6. **Risk-free rate**: daily TB3MS from FRED; annualised; cache with 24h TTL
7. **FRED series needed**: `TB3MS` (rf), `DEXUSEU` (USD/EUR), `DEXGBEU` (GBP/EUR)
8. **Static cache-busting**: mandatory — see CLAUDE.md
9. **No backtest engine in scope** for v1. Performance tab shows observed returns only.
10. **No holdings/weighting in scope** for v1. Each instrument tracked independently.

---

## Running

```bash
# Install
pip install flask pandas numpy scipy yfinance pandas-datareader plotly

# Start
python app.py
# → http://localhost:5055
```
