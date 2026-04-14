# Market Performance Dashboard

Flask performance dashboard for market indices + UCITS/ETF/40Act funds.
Port 5055. Returns-first (no portfolio weighting, no backtest in v1).
Full spec: @MASTER_PROMPT.md | File index: @CODEBASE_MAP.md | Arch log: @DECISIONS.md

---

## Session Initialization Protocol

**Before any task**, do exactly this — no directory scans, no speculative reads:
1. Read `CODEBASE_MAP.md` (file index — tells you what exists and where)
2. `Grep` for the specific symbol/function you need to change
3. `Read` only the targeted file section (use `offset`/`limit`)

**Never** `ls` a directory already inventoried in CODEBASE_MAP.md.
**Never** read a full file to find one function — grep first.
**Never** re-read a file you already read in the same session.

---

## Model Selection

| Task type | Model | Rationale |
|---|---|---|
| Architecture decisions, complex multi-file refactors | `opus` | Best reasoning; cost justified |
| Feature implementation, debugging, code review | `sonnet` (default) | Best cost/quality ratio |
| Config edits, formatting, single-line fixes, test runs | `haiku` | ~5× cheaper than Sonnet |
| Research / web lookups | `sonnet` | Balanced; Haiku misses nuance |

Switch with `/model haiku` before simple edits; switch back with `/model sonnet`.
When uncertain: start with Sonnet. Escalate to Opus only if Sonnet fails on second attempt.

---

## Rules

- All annualisation: ×252 (daily). Never ×365 or ×12.
- All calcs in `perf_engine.py` — no business logic in `app.py`
- All downloads/caching in `data_engine.py` — no yfinance calls elsewhere
- All JS state in `App` object — no other mutable globals
- Render latches (`App.rendered['tab']`) set AFTER successful render only
- Currency label always explicit — never silently present USD returns as EUR
- Manual NAV series: tag `[M]` in all display labels
- ETF-as-index proxy: tag `[P]` in display labels
- Sharpe always with Lo (2002) 95% CI: `0.72 [0.48–0.96]`
- Static cache-busting: `?v={{ v }}` on every CSS/JS tag; `SEND_FILE_MAX_AGE_DEFAULT = 0`

---

## Token Efficiency Rules

- **Spec before edits**: changes touching >2 locations → state edit plan, get confirmation first
- **Dry-runs**: show only the changed section, not full output
- **Iteration 2+**: list only what changed and why — do not restate prior context
- **Batch verification**: combine test/check commands into one script; never sequential individual runs
- **File reads**: read each file once per session; use `offset`/`limit` on files >100 lines
- **Grep before read**: always locate the target symbol before opening a file

---

## Testing Protocol (mandatory before any push)

Before pushing ANY change that touches a display path (modal, chart, table cell):
1. Verify the API response JSON directly — `curl http://localhost:5055/api/fund_detail?id=<id>` — confirm the fields you're relying on are non-null.
2. If adding a new field to an API response, trace the full path: Python computation → `_serialise`/`_safe_float` → JSON key → JS field access → `fmtPct`/display. Null at any step renders as "—".
3. Never assume a helper function returns a value just because a related function does. Compute from the same already-validated sub-series where possible.
4. When modifying display logic for one window tier (e.g. SHORT_WINDOWS), verify ALL tiers still render before pushing.

---

## Environment

```bash
python app.py          # → http://localhost:5055
pip install flask pandas numpy scipy yfinance pandas-datareader plotly
```
Config: `config.py` — import everywhere; never hardcode tickers, ports, or lookback windows.
Cache: `data/cache/` — never delete on server restart; TTL-managed.

**Server restart required after any change to:** `app.py`, `perf_engine.py`, `data_engine.py`, `config.py`, `templates/*.html`
**No restart needed for:** `static/dashboard.css`, `static/dashboard.js`, `universe.json` (browser hard-refresh still needed for CSS/JS)
Restart: `lsof -ti:5055 | xargs kill -9 && python3 app.py`
Verify template changes live: `curl http://localhost:5055 | grep <changed_element>` before browser test.

---

## Static Cache-Busting (mandatory)
```python
# app.py
CACHE_VERSION = int(time.time())
@app.context_processor
def inject_version(): return {"v": CACHE_VERSION}
```
All `<link>`/`<script>` tags: `href="...?v={{ v }}"`.

---

## Frontend Theme
`bg:#0d1117` | `card:#161b22` | `border:#30363d` | `text:#e6edf3`
`accent:#58a6ff` | `pos:#3fb950` | `neg:#f85149` | `warn:#d29922`
Font: Menlo/Monaco monospace. Plotly: match bg/card colors above, `font.size:11`.
