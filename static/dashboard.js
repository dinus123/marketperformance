/**
 * dashboard.js — All client-side logic for CTA Performance Dashboard.
 * Single App object; all mutable state lives here.
 * Lazy Plotly renders via App.rendered latch (set only after successful render).
 */

/* ── Plotly layout defaults ────────────────────────────────────────────────── */
const PLOT_LAYOUT = {
  paper_bgcolor: '#0d1117',
  plot_bgcolor:  '#161b22',
  font: { color: '#e6edf3', family: 'Menlo,Monaco,monospace', size: 11 },
  margin: { t: 30, r: 20, b: 40, l: 60 },
  xaxis: { gridcolor: '#30363d', zerolinecolor: '#30363d' },
  yaxis: { gridcolor: '#30363d', zerolinecolor: '#30363d' },
  legend: { bgcolor: '#161b22', bordercolor: '#30363d', borderwidth: 1 },
};

const PLOT_CONFIG = { responsive: true, displayModeBar: false };

/* Plotly color palette for multi-series */
const COLORS = [
  '#58a6ff','#3fb950','#f78166','#d29922','#a371f7',
  '#79c0ff','#56d364','#ffa657','#ff7b72','#bc8cff',
  '#1f6feb','#238636','#cf222e','#9e6a03','#8250df',
  '#388bfd','#2ea043','#da3633','#bf8700','#6e40c9',
];

/* ── Formatters ────────────────────────────────────────────────────────────── */
function fmtPct(v, decimals = 1) {
  if (v == null || isNaN(v)) return '—';
  const s = (v * 100).toFixed(decimals);
  return v >= 0 ? `+${s}%` : `${s}%`;
}
function fmtPctNoSign(v, decimals = 1) {
  if (v == null || isNaN(v)) return '—';
  return `${(v * 100).toFixed(decimals)}%`;
}
function fmtNum(v, decimals = 2) {
  if (v == null || isNaN(v)) return '—';
  return v.toFixed(decimals);
}
function fmtSharpe(sr, lo, hi) {
  if (sr == null || isNaN(sr)) return '—';
  if (lo != null && hi != null)
    return `${sr.toFixed(2)} <span class="ci-inline">[${lo.toFixed(2)}–${hi.toFixed(2)}]</span>`;
  return sr.toFixed(2);
}
function colorClass(v) {
  if (v == null || isNaN(v)) return 'cell-na';
  return v > 0 ? 'cell-pos' : v < 0 ? 'cell-neg' : '';
}

/* ── Date helpers ──────────────────────────────────────────────────────────── */
function windowToStartDate(window, lastDate) {
  const end = lastDate ? new Date(lastDate) : new Date();
  const d = new Date(end);
  switch (window) {
    case '1M':  d.setMonth(d.getMonth() - 1);    break;
    case '3M':  d.setMonth(d.getMonth() - 3);    break;
    case '6M':  d.setMonth(d.getMonth() - 6);    break;
    case 'YTD': d.setMonth(0); d.setDate(1);      break;
    case '1Y':  d.setFullYear(d.getFullYear()-1); break;
    case '3Y':  d.setFullYear(d.getFullYear()-3); break;
    case '5Y':  d.setFullYear(d.getFullYear()-5); break;
    case 'Max':
    case 'All': return null;
  }
  return d.toISOString().slice(0, 10);
}

/**
 * Rebase an array of values so values[startIdx] = 100.
 * Returns sliced + rebased array starting from startIdx.
 */
function rebaseToWindow(dates, values, startDate) {
  if (!startDate) return { dates, values };
  const startIdx = dates.findIndex(d => d >= startDate);
  if (startIdx < 0) return { dates: [], values: [] };
  const base = values[startIdx];
  if (!base || base === 0) return {
    dates: dates.slice(startIdx),
    values: dates.slice(startIdx).map(() => 100),
  };
  return {
    dates:  dates.slice(startIdx),
    values: values.slice(startIdx).map(v => (v / base) * 100),
  };
}

/* ── API helpers ───────────────────────────────────────────────────────────── */
async function apiFetch(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${url}`);
  return resp.json();
}

/* ── App state object ──────────────────────────────────────────────────────── */
const App = {
  // Render latches — set true only after successful first render
  rendered: {
    overview:    false,
    timeseries:  false,
    calendar:    false,
    stats:       false,
    relative:    false,
    universe:    false,
  },
  calendarRenderedFund: null,   // ID of last successfully rendered calendar fund

  // Cached universe metadata
  universe: [],

  // Overview state (legacy fields retained for compatibility)
  overviewWindow: 'YTD',
  overviewData: null,
  overviewSort: { col: 'ytd', dir: -1 },

  // Timeseries state
  tsRange: '1Y',
  tsScale: 'linear',
  tsSelected: new Set(),
  tsData: null,         // raw full-history data from /api/timeseries

  // Calendar state
  calFund: null,

  // Stats state
  statsWindow: '3Y',

  // Relative state
  relFund: null,
  relBench: 'AQMIX',
  relWindow: 'All',

  /* ── Init ────────────────────────────────────────────────────────────────── */
  async init() {
    // Load universe metadata
    try {
      this.universe = await apiFetch('/api/universe');
    } catch (e) {
      console.error('Failed to load universe:', e);
      this.universe = [];
    }

    // Populate selects in other tabs
    this._populateSelects();

    // Tab routing
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => this.activateTab(btn.dataset.tab));
    });

    // Render Overview on load
    App.overviewTab.load();
  },

  _populateSelects() {
    const active = this.universe.filter(f => f.active && f.data_source !== 'manual_csv' || (f.active && true));
    const withData = this.universe.filter(f => f.active);

    // Calendar fund select
    const calSel = document.getElementById('cal-fund-select');
    if (calSel) {
      calSel.innerHTML = withData.map(f =>
        `<option value="${f.id}">${f.name} (${f.currency})</option>`
      ).join('');
      calSel.addEventListener('change', () => {
        this.calFund = calSel.value;
        this.renderCalendar();  // ID tracker in renderCalendar handles re-render vs skip
      });
      this.calFund = withData.length ? withData[0].id : null;
    }

    // Relative fund + bench selects
    const relFundSel = document.getElementById('rel-fund-select');
    const relBenchSel = document.getElementById('rel-bench-select');
    if (relFundSel) {
      relFundSel.innerHTML = withData.map(f =>
        `<option value="${f.id}">${f.name}</option>`
      ).join('');
      relFundSel.addEventListener('change', () => {
        this.relFund = relFundSel.value;
        this.rendered.relative = false;
        this.renderRelative();
      });
      this.relFund = withData.length ? withData[0].id : null;
    }
    if (relBenchSel) {
      relBenchSel.innerHTML = withData.map(f =>
        `<option value="${f.id}" ${f.id === 'AQMIX' ? 'selected' : ''}>${f.name}</option>`
      ).join('');
      relBenchSel.addEventListener('change', () => {
        this.relBench = relBenchSel.value;
        this.rendered.relative = false;
        this.renderRelative();
      });
    }

    // Relative window buttons
    document.querySelectorAll('.rel-win-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.rel-win-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.relWindow = btn.dataset.window;
        this.rendered.relative = false;
        this.renderRelative();
      });
    });

    // Stats window buttons
    document.querySelectorAll('.stats-win-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.stats-win-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.statsWindow = btn.dataset.window;
        this.rendered.stats = false;
        this.renderStats();
      });
    });

    // Timeseries range buttons
    document.querySelectorAll('.range-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.tsRange = btn.dataset.range;
        this._renderTsCharts();
      });
    });

    // Timeseries scale buttons
    document.querySelectorAll('.scale-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.scale-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.tsScale = btn.dataset.scale;
        this._renderTsCharts();
      });
    });
  },

  /* ── Tab activation ──────────────────────────────────────────────────────── */
  activateTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelector(`.tab-btn[data-tab="${tab}"]`).classList.add('active');
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.getElementById(`tab-${tab}`).classList.add('active');

    // Lazy render
    if (tab === 'overview'   && !App.overviewTab.loaded)   App.overviewTab.load();
    if (tab === 'timeseries' && !this.rendered.timeseries)  this.renderTimeseries();
    if (tab === 'calendar')   this.renderCalendar();
    if (tab === 'stats'      && !this.rendered.stats)       this.renderStats();
    if (tab === 'relative'   && !this.rendered.relative)    this.renderRelative();
    if (tab === 'corr' && !App.corrTab.loaded) App.corrTab.load('3Y');
  },

  /* ── Overview (legacy stubs — delegated to App.overviewTab) ─────────────── */
  async renderOverview(forceRefresh = false) {
    // Retained for any legacy call-sites; delegates to overviewTab
    if (!forceRefresh && App.overviewTab.loaded) return;
    App.overviewTab.loaded = false;
    App.overviewTab.load();
  },

  /* ── Timeseries ──────────────────────────────────────────────────────────── */
  async renderTimeseries() {
    if (this.rendered.timeseries) return;
    // Build fund checklist
    this._buildTsFundList();

    // Select first ~8 funds with data as default
    const withData = this.universe.filter(f => f.active && f.data_source === 'yfinance');
    withData.slice(0, 8).forEach(f => this.tsSelected.add(f.id));
    this._syncTsCheckboxes();

    // Fetch data for all yfinance funds (full history; rebasing done client-side)
    await this._fetchTsData();
    this.rendered.timeseries = true;
  },

  _buildTsFundList() {
    const container = document.getElementById('ts-fund-list');
    if (!container) return;
    const active = this.universe.filter(f => f.active);
    container.innerHTML = active.map((f, i) => {
      const color = COLORS[i % COLORS.length];
      const hasData = f.data_source === 'yfinance';
      return `<label class="fund-check-item" title="${f.name}">
        <input type="checkbox" value="${f.id}" onchange="App.onTsCheck(this)"
          ${hasData ? '' : 'disabled'} />
        <span class="check-dot" style="background:${color}"></span>
        <span>${f.id}</span>
        ${!hasData ? '<span class="muted">[M]</span>' : ''}
      </label>`;
    }).join('');
  },

  _syncTsCheckboxes() {
    document.querySelectorAll('#ts-fund-list input[type=checkbox]').forEach(cb => {
      cb.checked = this.tsSelected.has(cb.value);
    });
  },

  onTsCheck(cb) {
    if (cb.checked) this.tsSelected.add(cb.value);
    else this.tsSelected.delete(cb.value);
    this._renderTsCharts();
  },

  tsSelectAll() {
    document.querySelectorAll('#ts-fund-list input[type=checkbox]:not([disabled])').forEach(cb => {
      cb.checked = true;
      this.tsSelected.add(cb.value);
    });
    this._renderTsCharts();
  },

  tsSelectNone() {
    document.querySelectorAll('#ts-fund-list input[type=checkbox]').forEach(cb => {
      cb.checked = false;
    });
    this.tsSelected.clear();
    this._renderTsCharts();
  },

  async _fetchTsData() {
    const ids = this.universe
      .filter(f => f.active && f.data_source === 'yfinance')
      .map(f => f.id);
    if (!ids.length) return;
    try {
      this.tsData = await apiFetch(`/api/timeseries?ids=${ids.join(',')}`);
      this._renderTsCharts();
    } catch (e) {
      console.error('Timeseries fetch failed:', e);
    }
  },

  _renderTsCharts() {
    if (!this.tsData) return;
    const selected = [...this.tsSelected];
    if (!selected.length) {
      Plotly.purge('ts-chart');
      Plotly.purge('dd-chart');
      return;
    }

    // Determine start date from range
    // Use the last date available across all selected series
    let globalLastDate = null;
    selected.forEach(id => {
      const d = this.tsData[id];
      if (d && d.dates && d.dates.length) {
        const last = d.dates[d.dates.length - 1];
        if (!globalLastDate || last > globalLastDate) globalLastDate = last;
      }
    });
    const startDate = windowToStartDate(this.tsRange, globalLastDate);

    const cumTraces = [];
    const ddTraces = [];

    selected.forEach((id, i) => {
      const d = this.tsData[id];
      if (!d || !d.dates || !d.dates.length) return;
      const color = COLORS[this._fundColorIndex(id)];
      const meta = this.universe.find(f => f.id === id) || {};
      const label = meta.name || id;

      const { dates, values } = rebaseToWindow(d.dates, d.prices_100, startDate);
      if (!dates.length) return;

      // Recompute drawdown from rebased series
      const dd = this._computeDrawdown(values);

      cumTraces.push({
        x: dates, y: values,
        name: id,
        type: 'scatter', mode: 'lines',
        line: { color, width: 1.5 },
        hovertemplate: `<b>${label}</b><br>%{x}<br>%{y:.2f}<extra></extra>`,
      });
      ddTraces.push({
        x: dates, y: dd,
        name: id,
        type: 'scatter', mode: 'lines',
        line: { color, width: 1 },
        fill: 'tozeroy',
        fillcolor: color + '22',
        showlegend: false,
        hovertemplate: `${id}<br>%{x}<br>%{y:.2%}<extra></extra>`,
      });
    });

    const cumLayout = {
      ...PLOT_LAYOUT,
      yaxis: {
        ...PLOT_LAYOUT.yaxis,
        title: 'Rebased (100)',
        type: this.tsScale === 'log' ? 'log' : 'linear',
      },
      xaxis: { ...PLOT_LAYOUT.xaxis },
      showlegend: true,
      legend: { ...PLOT_LAYOUT.legend, orientation: 'v', x: 1.01 },
    };

    const ddLayout = {
      ...PLOT_LAYOUT,
      yaxis: { ...PLOT_LAYOUT.yaxis, title: 'Drawdown', tickformat: '.0%' },
      xaxis: { ...PLOT_LAYOUT.xaxis },
      showlegend: false,
      margin: { ...PLOT_LAYOUT.margin, t: 15 },
    };

    Plotly.react('ts-chart', cumTraces, cumLayout, PLOT_CONFIG);
    Plotly.react('dd-chart', ddTraces, ddLayout, PLOT_CONFIG);
  },

  _fundColorIndex(id) {
    const active = this.universe.filter(f => f.active);
    const idx = active.findIndex(f => f.id === id);
    return idx >= 0 ? idx : 0;
  },

  _computeDrawdown(values) {
    let peak = -Infinity;
    return values.map(v => {
      if (v > peak) peak = v;
      return peak > 0 ? (v - peak) / peak : 0;
    });
  },

  /* ── Calendar ────────────────────────────────────────────────────────────── */
  async renderCalendar(force = false) {
    if (!force && this.calendarRenderedFund === this.calFund) return; // already showing this fund
    if (!this.calFund) return;
    const requestedFund = this.calFund;
    try {
      const data = await apiFetch(`/api/calendar?id=${requestedFund}`);
      if (requestedFund !== this.calFund) return;  // fund changed while awaiting — discard
      this._drawCalendarHeatmap(data, requestedFund);
      this._drawAnnualBar(data);
      this.calendarRenderedFund = requestedFund;
      this.rendered.calendar = true;  // keep boolean in sync for activateTab
    } catch (e) {
      console.error('Calendar render failed:', e);
    }
  },

  _drawCalendarHeatmap(data, fundId) {
    const el = document.getElementById('cal-heatmap');
    const years = Object.keys(data).map(Number).sort();
    const meta = this.universe.find(f => f.id === (fundId || this.calFund)) || {};
    const title = meta.name || fundId || this.calFund;

    // Purge first — always do this before any innerHTML manipulation to avoid
    // corrupting Plotly's internal div state (causes stale axis type on next render)
    Plotly.purge('cal-heatmap');

    // No data — show message in cleared div
    if (years.length === 0) {
      el.innerHTML = `<div style="color:var(--muted);padding:40px;text-align:center;">No price data available for ${title}</div>`;
      return;
    }

    const months = [1,2,3,4,5,6,7,8,9,10,11,12];
    const monthLabels = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec','Ann'];

    // z: rows=years, cols=Jan..Dec+Ann
    const z = years.map(yr => {
      const row = months.map(m => {
        const v = data[yr][m];
        return v != null ? v * 100 : null;
      });
      row.push(data[yr]['ann'] != null ? data[yr]['ann'] * 100 : null);
      return row;
    });

    const text = z.map(row => row.map(v => v != null ? `${v > 0 ? '+' : ''}${v.toFixed(1)}%` : ''));
    const maxAbs = Math.max(...z.flat().filter(v => v != null).map(Math.abs), 5);

    const trace = {
      type: 'heatmap',
      z, x: monthLabels,
      y: years.map(String),
      text, texttemplate: '%{text}',
      colorscale: [
        [0,   '#f85149'],
        [0.5, '#161b22'],
        [1,   '#3fb950'],
      ],
      zmid: 0,
      zmin: -maxAbs, zmax: maxAbs,
      showscale: true,
      hoverongaps: false,
      hovertemplate: '%{y} %{x}: %{text}<extra></extra>',
    };

    const layout = {
      ...PLOT_LAYOUT,
      // type:'category' must be explicit — after purge Plotly won't auto-detect
      // string labels correctly and falls back to linear, compressing all data left
      xaxis: { ...PLOT_LAYOUT.xaxis, type: 'category', side: 'top' },
      yaxis: { ...PLOT_LAYOUT.yaxis, type: 'category', autorange: 'reversed', title: '' },
      margin: { t: 60, r: 80, b: 20, l: 50 },
      title: { text: title, font: { color: '#e6edf3', size: 13 }, x: 0.02 },
    };

    Plotly.newPlot('cal-heatmap', [trace], layout, PLOT_CONFIG);
  },

  _drawAnnualBar(data) {
    const el = document.getElementById('cal-annual-bar');
    if (!el) return;
    const years = Object.keys(data).map(Number).sort();
    if (years.length === 0) { Plotly.purge(el); return; }
    const annReturns = years.map(yr => data[yr]['ann'] != null ? data[yr]['ann'] * 100 : null);

    const trace = {
      type: 'bar',
      x: years.map(String),
      y: annReturns,
      marker: {
        color: annReturns.map(v => v == null ? '#30363d' : v >= 0 ? '#3fb950' : '#f85149'),
      },
      hovertemplate: '%{x}: %{y:.1f}%<extra></extra>',
    };

    const layout = {
      ...PLOT_LAYOUT,
      yaxis: { ...PLOT_LAYOUT.yaxis, title: 'Annual Return (%)', tickformat: '.1f' },
      margin: { t: 15, r: 20, b: 40, l: 60 },
      showlegend: false,
    };

    Plotly.purge(el);
    Plotly.newPlot(el, [trace], layout, PLOT_CONFIG);
  },

  /* ── Stats ───────────────────────────────────────────────────────────────── */
  async renderStats() {
    if (this.rendered.stats) return;
    const startDate = windowToStartDate(this.statsWindow, null);
    const params = startDate ? `?start=${startDate}` : '';
    try {
      const data = await apiFetch(`/api/stats${params}`);
      this._drawStatsTable(data);
      this.rendered.stats = true;
    } catch (e) {
      console.error('Stats render failed:', e);
    }
  },

  _drawStatsTable(data) {
    const metaMap = {};
    this.universe.forEach(f => metaMap[f.id] = f);

    const rows = Object.entries(data)
      .filter(([id]) => metaMap[id] && metaMap[id].active)
      .map(([id, s]) => {
        const meta = metaMap[id] || {};
        const hasData = s && s.n_obs != null;
        return `<tr>
          <td><span class="fund-name-link" onclick="App.openModal('${id}')">${meta.name || id}</span></td>
          <td>${meta.currency || '—'}</td>
          <td class="num-col ${colorClass(s.cagr)}">${fmtPct(s.cagr)}</td>
          <td class="num-col">${fmtPctNoSign(s.vol)}</td>
          <td class="num-col">${fmtSharpe(s.sharpe, s.sharpe_lo, s.sharpe_hi)}</td>
          <td class="num-col ${colorClass(s.sortino)}">${fmtNum(s.sortino)}</td>
          <td class="num-col ${colorClass(s.max_dd)}">${fmtPct(s.max_dd)}</td>
          <td class="num-col ${colorClass(s.calmar)}">${fmtNum(s.calmar)}</td>
          <td class="num-col ${colorClass(s.skew)}">${fmtNum(s.skew)}</td>
          <td class="num-col">${fmtNum(s.kurt)}</td>
          <td class="num-col muted">${s.n_obs != null ? s.n_obs : '—'}</td>
        </tr>`;
      }).join('');

    document.getElementById('stats-tbody').innerHTML = rows || `<tr><td colspan="11" class="loading-row muted">No data for selected window.</td></tr>`;
  },

  /* ── Relative ────────────────────────────────────────────────────────────── */
  async renderRelative() {
    if (this.rendered.relative) return;
    if (!this.relFund) return;

    const startDate = windowToStartDate(this.relWindow, null);
    const startParam = startDate ? `&start=${startDate}` : '';
    try {
      const data = await apiFetch(`/api/relative?id=${this.relFund}&bench=${this.relBench}${startParam}`);
      this._drawRelCards(data);
      this._drawRollingBeta(data);
      this.rendered.relative = true;
    } catch (e) {
      console.error('Relative render failed:', e);
    }
  },

  _drawRelCards(data) {
    const cards = [
      { label: 'Alpha (ann.)',      value: fmtPct(data.alpha),      cls: colorClass(data.alpha) },
      { label: 'Beta',              value: fmtNum(data.beta, 2),    cls: colorClass(data.beta ? 1-Math.abs(data.beta) : null) },
      { label: 'Tracking Error',    value: fmtPctNoSign(data.te),   cls: '' },
      { label: 'Info Ratio',        value: fmtNum(data.ir),         cls: colorClass(data.ir) },
      { label: 'Up Capture',        value: data.up_cap != null ? `${(data.up_cap*100).toFixed(0)}%` : '—', cls: colorClass(data.up_cap ? data.up_cap - 1 : null) },
      { label: 'Down Capture',      value: data.dn_cap != null ? `${(data.dn_cap*100).toFixed(0)}%` : '—', cls: colorClass(data.dn_cap ? 1 - data.dn_cap : null) },
    ];

    const html = cards.map(c => `
      <div class="rel-card">
        <div class="card-label">${c.label}</div>
        <div class="card-value ${c.cls}">${c.value}</div>
      </div>`).join('');
    document.getElementById('rel-stats-cards').innerHTML = html;
  },

  _drawRollingBeta(data) {
    const rb = data.rolling_beta;
    if (!rb || !rb.dates || !rb.dates.length) {
      Plotly.purge('rel-rolling-beta');
      return;
    }
    const trace = {
      x: rb.dates, y: rb.values,
      type: 'scatter', mode: 'lines',
      line: { color: '#58a6ff', width: 1.5 },
      name: 'Rolling Beta (252d)',
      hovertemplate: '%{x}<br>Beta: %{y:.3f}<extra></extra>',
    };
    const layout = {
      ...PLOT_LAYOUT,
      yaxis: { ...PLOT_LAYOUT.yaxis, title: 'Beta (252d rolling)' },
      shapes: [{
        type: 'line', x0: rb.dates[0], x1: rb.dates[rb.dates.length-1],
        y0: 0, y1: 0,
        line: { color: '#30363d', width: 1, dash: 'dot' },
      }],
    };
    Plotly.react('rel-rolling-beta', [trace], layout, PLOT_CONFIG);
  },

  /* ── Fund detail modal ───────────────────────────────────────────────────── */
  async openModal(fundId) {
    const overlay = document.getElementById('fund-modal');
    const body = document.getElementById('modal-body');
    const title = document.getElementById('modal-title');
    const meta = this.universe.find(f => f.id === fundId) || {};

    title.textContent = `${meta.name || fundId}  (${meta.currency || ''})`;
    body.innerHTML = '<div class="modal-loading">Loading…</div>';
    overlay.style.display = 'flex';

    try {
      const data = await apiFetch(`/api/fund_detail?id=${fundId}`);
      body.innerHTML = this._buildModalHtml(data, meta);
      this._renderModalCharts(data, fundId);
    } catch (e) {
      body.innerHTML = `<div class="modal-loading" style="color:var(--negative)">Error: ${e.message}</div>`;
    }
  },

  closeModal() {
    document.getElementById('fund-modal').style.display = 'none';
    Plotly.purge('modal-cum-chart');
    Plotly.purge('modal-dd-chart');
    Plotly.purge('modal-cal-chart');
  },

  _buildModalHtml(data, meta) {
    const windows = ['1M','3M','6M','YTD','1Y','3Y','5Y','All'];
    const statsHtml = windows.map(w => {
      const s = (data.stats || {})[w] || {};
      return `<div class="modal-stat-card">
        <div class="modal-stat-label">${w}</div>
        <div class="modal-stat-value ${colorClass(s.cagr)}">${fmtPct(s.cagr)}</div>
        <div class="muted" style="font-size:11px">
          Vol: ${fmtPctNoSign(s.vol)} &nbsp;
          SR: ${fmtNum(s.sharpe)} &nbsp;
          DD: ${fmtPct(s.max_dd)}
        </div>
      </div>`;
    }).join('');

    const rel = data.relative || {};
    return `
      <div class="modal-section">
        <h4>Performance by window</h4>
        <div class="modal-stats-grid">${statsHtml}</div>
      </div>
      <div class="modal-section">
        <h4>Cumulative return (all history)</h4>
        <div id="modal-cum-chart" class="modal-chart-sm plotly-chart"></div>
      </div>
      <div class="modal-section">
        <h4>Drawdown</h4>
        <div id="modal-dd-chart" class="modal-chart-sm" style="min-height:140px;"></div>
      </div>
      <div class="modal-section">
        <h4>Calendar — monthly returns</h4>
        <div id="modal-cal-chart" class="modal-chart-sm" style="min-height:220px;"></div>
      </div>
      <div class="modal-section">
        <h4>Relative vs AQMIX (all history)</h4>
        <div class="rel-cards" style="margin-top:6px;">
          ${[
            ['Alpha (ann.)', fmtPct(rel.alpha), colorClass(rel.alpha)],
            ['Beta', fmtNum(rel.beta), ''],
            ['TE', fmtPctNoSign(rel.te), ''],
            ['IR', fmtNum(rel.ir), colorClass(rel.ir)],
            ['Up Cap', rel.up_cap != null ? `${(rel.up_cap*100).toFixed(0)}%` : '—', ''],
            ['Dn Cap', rel.dn_cap != null ? `${(rel.dn_cap*100).toFixed(0)}%` : '—', ''],
          ].map(([l,v,cls]) => `<div class="rel-card"><div class="card-label">${l}</div><div class="card-value ${cls}">${v}</div></div>`).join('')}
        </div>
      </div>
    `;
  },

  _renderModalCharts(data, fundId) {
    const ts = data.timeseries || {};
    const dates = ts.dates || [];
    const prices = ts.prices_100 || [];
    const dd = ts.drawdown || [];
    const meta = this.universe.find(f => f.id === fundId) || {};
    const color = COLORS[this._fundColorIndex(fundId)];

    if (dates.length) {
      Plotly.newPlot('modal-cum-chart', [{
        x: dates, y: prices,
        type: 'scatter', mode: 'lines',
        line: { color, width: 1.5 },
        name: meta.name || fundId,
        hovertemplate: '%{x}<br>%{y:.2f}<extra></extra>',
      }], {
        ...PLOT_LAYOUT,
        yaxis: { ...PLOT_LAYOUT.yaxis, title: 'Rebased (100)' },
        margin: { t: 10, r: 20, b: 40, l: 60 },
        showlegend: false,
      }, PLOT_CONFIG);

      Plotly.newPlot('modal-dd-chart', [{
        x: dates, y: dd,
        type: 'scatter', mode: 'lines',
        line: { color, width: 1 },
        fill: 'tozeroy', fillcolor: color + '22',
        hovertemplate: '%{x}<br>%{y:.2%}<extra></extra>',
      }], {
        ...PLOT_LAYOUT,
        yaxis: { ...PLOT_LAYOUT.yaxis, title: 'Drawdown', tickformat: '.0%' },
        margin: { t: 10, r: 20, b: 40, l: 60 },
        showlegend: false,
      }, PLOT_CONFIG);
    }

    // Calendar in modal
    const cal = data.calendar || {};
    if (Object.keys(cal).length) {
      const years = Object.keys(cal).map(Number).sort();
      const months = [1,2,3,4,5,6,7,8,9,10,11,12];
      const monthLabels = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec','Ann'];
      const z = years.map(yr => {
        const row = months.map(m => cal[yr][m] != null ? cal[yr][m] * 100 : null);
        row.push(cal[yr]['ann'] != null ? cal[yr]['ann'] * 100 : null);
        return row;
      });
      const text = z.map(row => row.map(v => v != null ? `${v > 0 ? '+' : ''}${v.toFixed(1)}%` : ''));
      const maxAbs = Math.max(...z.flat().filter(v => v != null).map(Math.abs), 5);
      Plotly.newPlot('modal-cal-chart', [{
        type: 'heatmap', z, x: monthLabels,
        y: years.map(String),
        text, texttemplate: '%{text}',
        colorscale: [[0,'#f85149'],[0.5,'#161b22'],[1,'#3fb950']],
        zmid: 0, zmin: -maxAbs, zmax: maxAbs,
        showscale: false,
        hovertemplate: '%{y} %{x}: %{text}<extra></extra>',
      }], {
        ...PLOT_LAYOUT,
        yaxis: { ...PLOT_LAYOUT.yaxis, autorange: 'reversed' },
        xaxis: { ...PLOT_LAYOUT.xaxis, side: 'top' },
        margin: { t: 40, r: 20, b: 10, l: 50 },
      }, PLOT_CONFIG);
    }
  },

  /* ── Universe tab ────────────────────────────────────────────────────────── */
  showAddFundForm() {
    document.getElementById('add-fund-form').style.display = 'block';
  },
  hideAddFundForm() {
    document.getElementById('add-fund-form').style.display = 'none';
  },

  async submitAddFund() {
    const get = id => document.getElementById(id).value.trim();
    const fund = {
      id:              get('af-id'),
      name:            get('af-name'),
      manager:         get('af-manager'),
      ticker:          get('af-ticker') || null,
      isin:            get('af-isin') || null,
      instrument_type: get('af-type'),
      asset_class:     'Managed Futures',
      currency:        get('af-currency'),
      data_source:     get('af-source'),
      active:          true,
      notes:           get('af-notes'),
    };
    if (!fund.id || !fund.name) {
      document.getElementById('af-status').textContent = 'ID and Name required.';
      return;
    }
    try {
      const universe = await apiFetch('/api/universe');
      universe.push(fund);
      await fetch('/api/universe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(universe),
      });
      document.getElementById('af-status').textContent = `Added ${fund.id}. Reload to see.`;
    } catch (e) {
      document.getElementById('af-status').textContent = `Error: ${e.message}`;
    }
  },

  /* ── Overview tab module ─────────────────────────────────────────────────── */
  overviewTab: {
    loaded: false,
    sortCol: 'ytd',
    sortAsc: false,
    data: [],
    lastUpdated: null,

    load: function() {
      document.getElementById('overview-loading').style.display = 'block';
      fetch('/api/overview')
        .then(r => r.json())
        .then(d => {
          App.overviewTab.data = d.rows || [];
          App.overviewTab.lastUpdated = d.last_updated || null;
          const lu = d.last_updated || '—';
          document.getElementById('overview-last-updated').textContent = 'Last updated: ' + lu;
          App.overviewTab.render();
          document.getElementById('overview-loading').style.display = 'none';
          App.overviewTab.loaded = true;
          App.rendered.overview = true;
        })
        .catch(e => {
          console.error('Overview load failed:', e);
          document.getElementById('overview-loading').style.display = 'none';
          document.getElementById('overview-body').innerHTML =
            `<tr><td colspan="16" style="color:var(--negative);padding:12px;">Error loading data: ${e.message}</td></tr>`;
        });
    },

    refresh: function() {
      document.getElementById('refresh-btn').disabled = true;
      document.getElementById('refresh-spinner').style.display = 'inline';
      fetch('/api/refresh', {method: 'POST'})
        .then(r => r.json())
        .then(d => {
          document.getElementById('overview-last-updated').textContent =
            'Last updated: ' + (d.last_updated || '—');
          document.getElementById('refresh-spinner').style.display = 'none';
          document.getElementById('refresh-btn').disabled = false;
          App.overviewTab.loaded = false;
          App.overviewTab.load();
        })
        .catch(e => {
          console.error('Refresh failed:', e);
          document.getElementById('refresh-spinner').style.display = 'none';
          document.getElementById('refresh-btn').disabled = false;
        });
    },

    render: function() {
      const rows = [...this.data];
      const col = this.sortCol, asc = this.sortAsc;
      rows.sort((a, b) => {
        const va = a[col], vb = b[col];
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === 'string') return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        return asc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
      });

      const fmtPctCell = v => v == null
        ? '<td class="num-col muted">—</td>'
        : `<td class="num-col ${v >= 0 ? 'pos' : 'neg'}">${(v * 100).toFixed(2)}%</td>`;

      let html = '';
      rows.forEach(r => {
        const nameLabel = r.name + (!r.has_data ? ' <span class="muted">[M]</span>' : '');
        html += `<tr class="${r.has_data ? '' : 'row-no-data'}" style="cursor:pointer"
                      onclick="App.openModal('${r.id}')">`;
        html += `<td class="fund-name-link">${nameLabel}</td>`;
        html += `<td>${r.manager || '—'}</td>`;
        html += `<td>${r.type || '—'}</td>`;
        html += `<td>${r.currency || '—'}</td>`;
        html += fmtPctCell(r.mtd);
        html += fmtPctCell(r.prev_month);
        html += fmtPctCell(r.qtd);
        html += fmtPctCell(r.prev_qtr);
        html += fmtPctCell(r.ytd);
        html += fmtPctCell(r.ret_12m);
        html += fmtPctCell(r.ret_2025);
        html += fmtPctCell(r.ret_2024);
        html += fmtPctCell(r.ret_2023);
        html += `<td class="num-col">${r.vol != null ? (r.vol * 100).toFixed(1) + '%' : '—'}</td>`;
        html += `<td class="muted">${r.aum || '—'}</td>`;
        html += `<td class="muted">${r.inception || '—'}</td>`;
        html += '</tr>';
      });
      document.getElementById('overview-body').innerHTML = html;

      // Set dynamic column labels from last_updated date
      if (this.lastUpdated) {
        const dt = new Date(this.lastUpdated + 'T00:00:00Z');
        const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        const mo = dt.getUTCMonth(), yr = dt.getUTCFullYear();
        const prevMo = mo === 0 ? 11 : mo - 1;
        const prevYr = mo === 0 ? yr - 1 : yr;
        const q = Math.floor(mo / 3) + 1;
        const prevQ = q === 1 ? 4 : q - 1;
        const prevQYr = q === 1 ? yr - 1 : yr;
        const setLabel = (id, lbl) => { const e = document.getElementById(id); if (e) e.dataset.dynLabel = lbl; };
        setLabel('th-mtd',        `${MONTHS[mo]} ${yr}`);
        setLabel('th-prev-month', `${MONTHS[prevMo]} ${prevYr}`);
        setLabel('th-qtd',        `Q${q} ${yr}`);
        setLabel('th-prev-qtr',  `Q${prevQ} ${prevQYr}`);
      }

      // Wire sort headers + show ▲/▼ indicator on active column
      document.querySelectorAll('#overview-table th.sortable').forEach(th => {
        th.style.cursor = 'pointer';
        const base = th.dataset.dynLabel || (th.dataset.base = th.dataset.base || th.textContent.replace(/ [▲▼]$/, '').trim());
        th.textContent = base + (th.dataset.col === this.sortCol ? (this.sortAsc ? ' ▲' : ' ▼') : '');
        th.onclick = () => {
          const c = th.dataset.col;
          if (App.overviewTab.sortCol === c) {
            App.overviewTab.sortAsc = !App.overviewTab.sortAsc;
          } else {
            App.overviewTab.sortCol = c;
            App.overviewTab.sortAsc = false;
          }
          App.overviewTab.render();
        };
      });
    },
  },

  /* ── Correlation heatmap tab ─────────────────────────────────────────────── */
  corrTab: {
    loaded: false,
    load: function(win) {
      win = win || '3Y';
      document.getElementById('corr-loading').style.display = 'block';
      document.getElementById('corr-container').style.display = 'none';
      fetch('/api/correlation?window=' + win)
        .then(r => r.json())
        .then(d => { App.corrTab.render(d); })
        .catch(e => { console.error(e); });
    },
    render: function(d) {
      const ids = d.ids || [], names = d.names || [], matrix = d.matrix || [];
      const nObs = d.n_obs || {};
      const short = names.map(n => n.length > 20 ? n.slice(0,19)+'…' : n);
      const table = document.getElementById('corr-table');
      let h = '<thead><tr><th class="corr-label-h">Fund</th>';
      short.forEach(n => { h += `<th class="corr-col-h"><div class="corr-rot">${n}</div></th>`; });
      h += '</tr></thead><tbody>';
      matrix.forEach((row, i) => {
        h += `<tr><td class="corr-label" title="${names[i]}">${short[i]}<br><span class="corr-obs">${nObs[ids[i]]||''}d</span></td>`;
        row.forEach((v, j) => {
          if (v === null) { h += '<td class="corr-cell corr-na">—</td>'; return; }
          const bg = App.corrTab.color(v, i===j);
          h += `<td class="corr-cell" style="background:${bg}" title="${names[i]} vs ${names[j]}: ${typeof v==='number'?v.toFixed(3):v}">${i===j?'1.00':typeof v==='number'?v.toFixed(2):'—'}</td>`;
        });
        h += '</tr>';
      });
      h += '</tbody>';
      table.innerHTML = h;
      const info = `${ids.length} funds · ${d.window} window · pairwise on common dates`;
      document.getElementById('corr-info').textContent = info;
      document.getElementById('corr-loading').style.display = 'none';
      document.getElementById('corr-container').style.display = 'block';
      this.loaded = true;
    },
    color: function(v, diag) {
      if (diag) return '#2d333b';
      const t = Math.min(Math.abs(v), 1);
      if (v >= 0) {
        // positive → green (#3fb950)
        const r=Math.round(22+t*(63-22)), g=Math.round(27+t*(185-27)), b=Math.round(34+t*(80-34));
        return `rgb(${r},${g},${b})`;
      } else {
        // negative → red (#f85149)
        const r=Math.round(22+t*(248-22)), g=Math.round(27+t*(81-27)), b=Math.round(34+t*(73-34));
        return `rgb(${r},${g},${b})`;
      }
    }
  },

  /* ── NAV upload forms (universe tab) ─────────────────────────────────────── */
  _initNavUpload() {
    document.querySelectorAll('.nav-upload-form').forEach(form => {
      form.addEventListener('submit', async e => {
        e.preventDefault();
        const fid = form.dataset.fundId;
        const fileInput = form.querySelector('input[type=file]');
        const statusEl = form.querySelector('.upload-status');
        if (!fileInput.files.length) { statusEl.textContent = 'Select a file.'; return; }
        const fd = new FormData();
        fd.append('fund_id', fid);
        fd.append('file', fileInput.files[0]);
        statusEl.textContent = 'Uploading…';
        try {
          const resp = await fetch('/api/upload-nav', { method: 'POST', body: fd });
          const result = await resp.json();
          statusEl.style.color = 'var(--positive)';
          statusEl.textContent = `OK — ${result.rows_loaded} rows`;
        } catch (err) {
          statusEl.style.color = 'var(--negative)';
          statusEl.textContent = `Error: ${err.message}`;
        }
      });
    });
  },
};

/* ── Bootstrap ─────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  App.init();
  App._initNavUpload();

  // Close modal on overlay click
  document.getElementById('fund-modal').addEventListener('click', e => {
    if (e.target === document.getElementById('fund-modal')) App.closeModal();
  });

  // Escape key closes modal
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') App.closeModal();
  });
});
