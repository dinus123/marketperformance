# Architecture Decisions

## 2026-03-31 — Initial Architecture

### Decision: Flask + Plotly.js, port 5055
- Consistent with portfolio_optimizer_2 (5051) and portfolio_optimizer (5052) — avoid collisions.
- No React/Vue; Jinja2 + vanilla JS keeps the stack minimal and auditable.

### Decision: perf_engine.py separate from app.py
- All calculations pure Python (no Flask imports). Enables CLI testing without server running.
- Pattern from portfolio_optimizer_2 where risk_engine.py is cleanly separated.

### Decision: universe.json as the single source of truth for the instrument list
- Editable via Universe tab UI (POST /api/universe).
- Avoids config.py bloat as universe grows.
- data_source field distinguishes yfinance vs manual CSV vs proxy — critical for display labeling.

### Decision: file-based pickle cache (not in-memory)
- Server restarts do not force re-downloads (important given yfinance rate limits).
- data/manual/ directory for UCITS NAV CSVs never touched by download logic.

### Decision: EUR base currency, toggle to local
- Owner is EUR-based (Saxo DK account).
- FX conversion via FRED DEXUSEU / DEXGBEU — same source used in portfolio_optimizer_2.

### Decision: no portfolio weighting or backtest in v1
- This dashboard is returns-monitoring, not portfolio construction.
- Weighted composite / backtest is already in portfolio_optimizer_2.
- Keeps scope tight; add later if needed.

### Decision: Lo (2002) Sharpe CI on all Sharpe displays
- Consistent with portfolio_optimizer_2. CI inline: `0.72 [0.48–0.96]`.
- Prevents over-reading noisy Sharpe estimates on short windows.
