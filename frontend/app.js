const $ = (selector, root = document) => root.querySelector(selector)
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)]
const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })
const compactMoney = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 })
const number = new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 })
const dateTime = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })
const relative = new Intl.RelativeTimeFormat('en-US', { numeric: 'auto' })

const state = {
  data: null,
  connected: false,
  loading: true,
  error: null,
  range: 'ALL',
  tradeFilter: 'all',
  trade: null,
  tradeLoading: false,
  tradeError: null,
  tradeTab: 'journey',
  selectedRun: null,
  menuOpen: false,
  lastTrigger: null,
}

const routes = ['overview', 'portfolio', 'trades', 'runs', 'system']
const route = () => routes.includes(location.hash.slice(2)) ? location.hash.slice(2) : 'overview'
const esc = value => String(value ?? '—').replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character])
const cls = value => String(value ?? '').toLowerCase().replace(/[^a-z0-9_-]/g, '')
const formatMoney = value => value === null || value === undefined ? '—' : money.format(Number(value))
const formatPct = (value, digits = 1) => value === null || value === undefined ? '—' : `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(digits)}%`
const formatBps = value => value === null || value === undefined ? '—' : `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(1)} bps`
const formatDate = value => value ? dateTime.format(new Date(value)) : '—'
const age = seconds => {
  if (seconds === null || seconds === undefined) return 'never'
  if (seconds < 90) return relative.format(-Math.round(seconds), 'second')
  if (seconds < 5400) return relative.format(-Math.round(seconds / 60), 'minute')
  if (seconds < 129600) return relative.format(-Math.round(seconds / 3600), 'hour')
  return relative.format(-Math.round(seconds / 86400), 'day')
}
const safeUrl = value => {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '#'
  } catch { return '#' }
}
const json = value => esc(JSON.stringify(value, null, 2))

async function load() {
  state.loading = true
  state.error = null
  try {
    const response = await fetch('/api/control-plane')
    if (!response.ok) throw new Error(`Operator API returned ${response.status}`)
    state.data = await response.json()
    state.connected = true
  } catch (error) {
    state.connected = false
    state.error = error.message || 'The local operator API is unavailable.'
    state.data = emptyModel()
  } finally {
    state.loading = false
    render()
  }
}

function emptyModel() {
  return {
    generated_at: new Date().toISOString(), source: 'unavailable', has_history: false,
    health: { status: 'disconnected', reasons: ['The local operator API could not be reached.'], snapshot: { runs_by_status: {}, unresolved_order_count: 0, trading_halted: false } },
    mandates: [], portfolio: { status: 'unavailable', positions: [], history: [] }, performance: [], runs: [], trades: [], events: [], proposals: [],
  }
}

function icon(name) {
  const icons = {
    overview: '<path d="M3 3h7v7H3zM14 3h7v4h-7zM14 11h7v10h-7zM3 14h7v7H3z"/>',
    portfolio: '<path d="M4 19V9m5 10V5m5 14v-7m5 7V3"/>',
    trades: '<path d="M4 17 10 11l4 4 6-8M15 7h5v5"/>',
    runs: '<path d="M12 3a9 9 0 1 0 9 9M12 7v5l3 2"/>',
    system: '<path d="M12 3 4 7v5c0 5 3.4 8 8 9 4.6-1 8-4 8-9V7zM9 12l2 2 4-4"/>',
    refresh: '<path d="M20 6v5h-5M4 18v-5h5M18 9a7 7 0 0 0-12-2L4 11M6 15a7 7 0 0 0 12 2l2-4"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    arrow: '<path d="m9 18 6-6-6-6"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    alert: '<path d="M12 3 2 21h20zM12 9v5m0 3h.01"/>',
    database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/>',
  }
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.system}</svg>`
}

function navItem(id, label) {
  return `<a href="#/${id}" class="nav-item ${route() === id ? 'active' : ''}" ${route() === id ? 'aria-current="page"' : ''}>${icon(id)}<span>${label}</span></a>`
}

function shell(content) {
  const data = state.data
  const health = data.health || { status: 'unknown', snapshot: {} }
  const mode = data.mandates?.[0]?.mode || 'unconfigured'
  return `<div class="app-shell">
    <aside class="sidebar ${state.menuOpen ? 'open' : ''}">
      <a class="brand" href="#/overview" aria-label="Edgecraft overview"><span class="brand-mark">E</span><span><b>EDGECRAFT</b><small>OPERATOR LEDGER</small></span></a>
      <nav aria-label="Primary navigation">
        <p class="nav-label">Fund</p>
        ${navItem('overview', 'Overview')}${navItem('portfolio', 'Portfolio')}${navItem('trades', 'Trades')}
        <p class="nav-label">Operations</p>
        ${navItem('runs', 'Agent runs')}${navItem('system', 'System & method')}
      </nav>
      <div class="sidebar-status">
        <div><span class="status-light ${cls(health.status)}"></span><span><small>SYSTEM</small><b>${esc(health.status)}</b></span></div>
        <dl><div><dt>Mode</dt><dd>${esc(mode)}</dd></div><div><dt>Open orders</dt><dd>${health.snapshot?.unresolved_order_count ?? 0}</dd></div></dl>
        <p>Local, read-only operator surface</p>
      </div>
    </aside>
    <div class="mobile-scrim" data-menu-close></div>
    <section class="workspace">
      <header class="topbar">
        <div><button class="icon-button menu-button" data-menu aria-label="Open navigation">${icon('menu')}</button><span class="breadcrumb">EDGECRAFT <i>/</i> ${route().toUpperCase()}</span></div>
        <div class="connection"><span class="status-light ${state.connected ? 'ready' : 'disconnected'}"></span><span>${state.connected ? 'LEDGER CONNECTED' : 'DISCONNECTED'}</span><button class="icon-button" data-refresh aria-label="Refresh operator data">${icon('refresh')}</button></div>
      </header>
      ${state.error ? `<div class="global-alert">${icon('alert')}<span><b>Operator API unavailable.</b> ${esc(state.error)}</span></div>` : ''}
      <main id="main-content">${content}</main>
    </section>
    ${state.tradeLoading ? tradeLoading() : state.trade ? tradeDossier(state.trade) : ''}
  </div>`
}

function pageHeader(kicker, title, copy, aside = '') {
  return `<header class="page-header"><div><p>${esc(kicker)}</p><h1>${esc(title)}</h1><span>${esc(copy)}</span></div>${aside}</header>`
}

function badge(status, label = status) {
  return `<span class="badge ${cls(status)}"><i></i>${esc(String(label).replaceAll('_', ' '))}</span>`
}

function stat(label, value, note = '', tone = '') {
  return `<article class="metric ${tone}"><small>${esc(label)}</small><strong>${esc(value)}</strong>${note ? `<span>${esc(note)}</span>` : ''}</article>`
}

function render() {
  if (state.loading && !state.data) {
    $('#root').innerHTML = '<div class="boot"><span></span><b>Opening the operator ledger</b></div>'
    return
  }
  const pages = { overview, portfolio, trades, runs, system }
  $('#root').innerHTML = shell(pages[route()]())
  document.body.classList.toggle('modal-open', Boolean(state.trade || state.tradeLoading))
  bind()
}

function overview() {
  const data = state.data
  const portfolio = data.portfolio || {}
  const performance = selectedPerformance()
  const report = performance?.report || {}
  const latestTrade = data.trades?.[0]
  const latestRun = data.runs?.[0]
  const portfolioKnown = portfolio.portfolio_value !== null && portfolio.portfolio_value !== undefined
  const subtitle = portfolio.status === 'stale_after_trade'
    ? 'The last verified account snapshot predates a broker fill. Values below are point-in-time, not inferred.'
    : 'Broker observations, autonomous decisions, safety controls, and fills in one auditable surface.'
  return `${pageHeader('FUND / OVERVIEW', 'Capital, decisions, and control.', subtitle, `<div class="as-of"><small>GENERATED</small><b>${formatDate(data.generated_at)}</b></div>`)}
    ${portfolio.status === 'stale_after_trade' ? stalePortfolioBanner(portfolio) : ''}
    <section class="overview-grid">
      <article class="panel portfolio-hero">
        <div class="panel-heading"><div><small>LAST VERIFIED PORTFOLIO</small><h2>${portfolioKnown ? formatMoney(portfolio.portfolio_value) : 'Awaiting snapshot'}</h2><p>${portfolio.as_of ? `Observed ${formatDate(portfolio.as_of)}` : 'No canonical broker snapshot has been recorded.'}</p></div>${badge(portfolio.status || 'unavailable')}</div>
        <div class="hero-chart">${portfolioChart(portfolio.history || [])}</div>
        <div class="metric-row">
          ${stat('Buying power', formatMoney(portfolio.buying_power), portfolio.stale_after_trade ? 'Before latest fill' : 'Broker observed')}
          ${stat('Invested', formatMoney(portfolio.invested_value), portfolio.invested_value === null ? 'Not retained in summary' : 'Marked at observation')}
          ${stat('Unrealized P&L', formatMoney(portfolio.unrealized_pnl), portfolio.unrealized_return_on_cost === null || portfolio.unrealized_return_on_cost === undefined ? 'Cost basis unavailable' : formatPct(portfolio.unrealized_return_on_cost))}
        </div>
      </article>
      <div class="overview-rail">
        ${healthPanel(data.health, data.mandates?.[0])}
        <article class="panel latest-decision">
          <div class="panel-label"><span>LATEST RUN</span>${latestRun ? badge(latestRun.status) : ''}</div>
          ${latestRun ? `<h3>${esc(latestRun.detail || latestRun.status)}</h3><p>${esc(latestRun.cycle_key)}</p><dl><div><dt>Started</dt><dd>${formatDate(latestRun.started_at)}</dd></div><div><dt>Mode</dt><dd>${esc(latestRun.mode)}</dd></div></dl><a href="#/runs">Open run timeline ${icon('arrow')}</a>` : empty('No autonomous run has been recorded yet.')}
        </article>
      </div>
    </section>
    <section class="overview-lower">
      <article class="panel performance-card">
        <div class="section-heading"><div><small>CASH-FLOW-MATCHED EVALUATION</small><h2>Agent vs benchmark</h2></div>${badge(report.status || 'no_history')}</div>
        ${performance && performance.series.length ? `${comparisonChart(performance.series)}${performanceMetrics(report)}` : empty('The strategy evaluation book has no retained observations yet. Future cycles will compare the agent, benchmark, and fixed strategic sleeve with identical cash flows.')}
      </article>
      <article class="panel latest-trade">
        <div class="section-heading"><div><small>LATEST ORDER</small><h2>Broker truth</h2></div><a href="#/trades">All trades</a></div>
        ${latestTrade ? tradeCard(latestTrade, true) : empty('No proposed broker order has been recorded.')}
      </article>
    </section>
    <section class="metric-strip">
      ${stat('Confirmed fills', String((data.trades || []).filter(item => item.confirmed_execution).length), 'Placement + terminal fill + reconciled run')}
      ${stat('Audited runs', String((data.runs || []).length), 'Idempotent cycle records')}
      ${stat('Policy rejections', String(data.health?.snapshot?.runs_by_status?.risk_rejected || 0), 'Deterministic controls held')}
      ${stat('Kill switch', data.health?.snapshot?.trading_halted ? 'ACTIVE' : 'Clear', data.health?.snapshot?.trading_halted ? 'Live trading disabled' : 'No global halt', data.health?.snapshot?.trading_halted ? 'negative' : 'positive')}
    </section>`
}

function stalePortfolioBanner(portfolio) {
  return `<aside class="data-warning">${icon('alert')}<div><b>Holdings refresh required</b><p>The last account snapshot was captured ${formatDate(portfolio.as_of)}; a broker event completed ${formatDate(portfolio.last_broker_trade_at)}. Edgecraft will not infer current holdings from an order event.</p></div><span>FAIL-CLOSED DATA</span></aside>`
}

function healthPanel(health, mandate) {
  const reasons = health?.reasons || []
  const status = health?.status || 'unknown'
  return `<article class="health-panel ${cls(status)}"><div class="health-orbit"><span></span></div><small>AUTONOMY HEALTH</small><h2>${status === 'ready' ? 'Operating inside hard limits' : esc(status.replaceAll('_', ' '))}</h2><p>${esc(reasons[0] || 'No kill switch, unresolved order, or recent failure is blocking operation.')}</p><dl><div><dt>Mandate</dt><dd>${esc(mandate?.mandate_id || 'none')}</dd></div><div><dt>Budget</dt><dd>${formatMoney(mandate?.cycle_budget)}</dd></div><div><dt>Last success</dt><dd>${age(health?.last_success_age_seconds)}</dd></div></dl></article>`
}

function portfolio() {
  const view = state.data.portfolio || {}
  const performance = selectedPerformance()
  const report = performance?.report || {}
  const quality = performance?.execution_quality || {}
  const holdings = view.positions || []
  return `${pageHeader('FUND / PORTFOLIO', 'Portfolio truth without guesswork.', 'Verified broker snapshots are kept separate from the controlled strategy experiment and execution-quality analytics.')}
    ${view.status === 'stale_after_trade' ? stalePortfolioBanner(view) : ''}
    ${view.audit_note ? `<aside class="audit-note">${icon('database')}<div><b>Historical retention boundary</b><p>${esc(view.audit_note)}</p></div></aside>` : ''}
    <section class="portfolio-summary">
      ${stat('Portfolio value', formatMoney(view.portfolio_value), view.as_of ? `As of ${formatDate(view.as_of)}` : 'No snapshot')}
      ${stat('Buying power', formatMoney(view.buying_power), view.stale_after_trade ? 'Pre-fill value' : 'Broker observed')}
      ${stat('Positions', String(view.position_count ?? holdings.length), view.audit_note ? 'Summary only' : holdings.some(item => item.detail_available === false) ? 'Symbols only' : 'Fully valued')}
      ${stat('Largest weight', view.largest_position_weight === undefined ? '—' : formatPct(view.largest_position_weight), 'At last full snapshot')}
    </section>
    <section class="portfolio-layout">
      <article class="panel holdings-panel">
        <div class="section-heading"><div><small>VERIFIED HOLDINGS</small><h2>Position inventory</h2></div><span class="timestamp">${view.as_of ? formatDate(view.as_of) : 'No observation'}</span></div>
        ${holdings.length ? holdingsTable(holdings, view.portfolio_value) : empty(view.stale_after_trade ? 'The latest retained snapshot showed no positions before the recorded fill. A new broker observation is required to display the resulting holding.' : 'No equity positions were present in the latest verified snapshot.')}
      </article>
      <article class="panel allocation-panel">
        <div class="section-heading"><div><small>CAPITAL MIX</small><h2>Observed allocation</h2></div></div>
        ${allocationVisual(view)}
      </article>
    </section>
    <section class="performance-section">
      <article class="panel strategy-performance">
        <div class="section-heading"><div><small>CONTROLLED EXPERIMENT</small><h2>Performance vs ${esc(performance?.benchmark || 'benchmark')}</h2><p>Identical contributions and point-in-time prices across all sleeves.</p></div>${badge(report.status || 'no_history')}</div>
        ${performance?.series?.length ? `${comparisonChart(performance.series, true)}${performanceMetrics(report)}` : empty('No evaluation history was retained for this mandate. This is an audit gap, not a zero return.')}
      </article>
      <article class="panel execution-quality">
        <div class="section-heading"><div><small>EXECUTION QUALITY</small><h2>Decision price to fill</h2></div>${badge(quality.status || 'no_history')}</div>
        <div class="quality-value"><strong>${formatBps(quality.notional_weighted_slippage_bps)}</strong><span>Notional-weighted slippage</span></div>
        <dl><div><dt>Measured fills</dt><dd>${quality.measured_fill_count ?? 0}</dd></div><div><dt>Filled notional</dt><dd>${formatMoney(quality.filled_notional)}</dd></div><div><dt>Fees</dt><dd>${formatMoney(quality.fees)}</dd></div><div><dt>Worst adverse</dt><dd>${formatBps(quality.worst_adverse_slippage_bps)}</dd></div></dl>
        <p class="measurement-note">Directional until at least 20 measured fills. The dashboard never turns a one-trade sample into a quality claim.</p>
      </article>
    </section>`
}

function holdingsTable(holdings, portfolioValue) {
  return `<div class="table-wrap"><table><thead><tr><th>Asset</th><th class="numeric">Quantity</th><th class="numeric">Price</th><th class="numeric">Market value</th><th class="numeric">Weight</th><th class="numeric">Unrealized</th></tr></thead><tbody>${holdings.map(item => `<tr><td><b>${esc(item.symbol)}</b></td><td class="numeric">${item.quantity === undefined ? '—' : number.format(item.quantity)}</td><td class="numeric">${formatMoney(item.market_price)}</td><td class="numeric"><b>${formatMoney(item.market_value)}</b></td><td class="numeric">${item.weight === undefined && item.market_value ? formatPct(item.market_value / portfolioValue) : formatPct(item.weight)}</td><td class="numeric ${Number(item.unrealized_pnl) < 0 ? 'negative-text' : ''}">${formatMoney(item.unrealized_pnl)}</td></tr>`).join('')}</tbody></table></div>`
}

function allocationVisual(view) {
  const positions = view.positions?.filter(item => item.weight !== undefined) || []
  const cashWeight = view.cash_weight ?? (view.portfolio_value && view.buying_power !== undefined ? view.buying_power / view.portfolio_value : null)
  if (!positions.length && cashWeight === null) return empty('A full valued snapshot is required to calculate allocation weights.')
  const segments = [...positions.slice(0, 5).map(item => ({ label: item.symbol, weight: item.weight })), { label: 'Cash', weight: Math.max(0, cashWeight || 0) }].filter(item => item.weight > 0)
  let cursor = 0
  const rings = segments.map((item, index) => {
    const weight = Math.max(0, Math.min(100, item.weight * 100))
    const offset = -cursor
    cursor += weight
    return `<circle class="series-${(index % 5) + 1}" cx="50" cy="50" r="42" pathLength="100" stroke-dasharray="${weight} ${100 - weight}" stroke-dashoffset="${offset}"/>`
  }).join('')
  return `<div class="allocation-visual"><div class="allocation-donut"><svg viewBox="0 0 100 100" role="img" aria-label="Observed portfolio allocation"><circle class="track" cx="50" cy="50" r="42" pathLength="100"/>${rings}</svg><span><b>${view.position_count ?? positions.length}</b><small>POSITIONS</small></span></div><div class="allocation-list">${segments.map((item, index) => `<p><i class="series-${(index % 5) + 1}"></i><b>${esc(item.label)}</b><span>${formatPct(item.weight, 1).replace('+', '')}</span></p>`).join('')}</div></div>`
}

function trades() {
  const all = state.data.trades || []
  const filtered = all.filter(item => state.tradeFilter === 'all' || (state.tradeFilter === 'confirmed' ? item.confirmed_execution : state.tradeFilter === 'broker' ? item.broker_event_count > 0 && !item.confirmed_execution : item.broker_event_count === 0))
  return `${pageHeader('AUDIT / TRADES', 'Trading history, fully auditable.', 'Open an order to inspect the exact reasoning, cited evidence, policy result, authority, broker transitions, reconciliation, and raw retained record.')}
    <div class="trade-toolbar" role="group" aria-label="Filter orders">
      <span>${all.length} ORDER${all.length === 1 ? '' : 'S'}</span>
      ${[['all', 'All'], ['confirmed', 'Confirmed fills'], ['broker', 'Other broker states'], ['intent', 'Proposal only']].map(([id, label]) => `<button data-trade-filter="${id}" class="${state.tradeFilter === id ? 'active' : ''}" aria-pressed="${state.tradeFilter === id}">${label}</button>`).join('')}
    </div>
    <section class="trades-list" aria-live="polite">
      ${filtered.length ? filtered.map(item => tradeRow(item)).join('') : empty('No orders match this view.')}
    </section>
    <aside class="trade-legend"><span><i class="confirmed"></i><b>Confirmed execution</b> requires placement, terminal fill, and a completed reconciled run.</span><span><i class="recorded"></i><b>Recorded state</b> may be reviewed, placed, rejected, canceled, or unresolved.</span><span><i class="intent"></i><b>Proposal only</b> never reached the broker.</span></aside>`
}

function tradeRow(item) {
  const priceDelta = item.average_fill_price && item.expected_price ? (Number(item.average_fill_price) / Number(item.expected_price) - 1) * 10000 : null
  return `<button class="trade-row" data-trade="${esc(item.order_key)}">
    <span class="trade-symbol"><i>${esc((item.side || '?').slice(0, 1).toUpperCase())}</i><span><b>${esc(item.symbol || 'Unknown')}</b><small>${esc(item.side)} · ${esc(item.mode)}</small></span></span>
    <span><small>STATUS</small>${badge(item.confirmed_execution ? 'confirmed' : item.status, item.confirmed_execution ? 'confirmed fill' : item.status)}</span>
    <span><small>NOTIONAL</small><b>${formatMoney(item.filled_notional ?? item.notional)}</b></span>
    <span><small>PRICE</small><b>${formatMoney(item.average_fill_price ?? item.expected_price)}</b>${priceDelta === null ? '' : `<em class="${priceDelta > 0 ? 'negative-text' : ''}">${formatBps(priceDelta)}</em>`}</span>
    <span><small>RECORDED</small><b>${formatDate(item.occurred_at)}</b></span>
    <span class="row-arrow">${icon('arrow')}</span>
  </button>`
}

function tradeCard(item, compact = false) {
  return `<button class="trade-card ${compact ? 'compact' : ''}" data-trade="${esc(item.order_key)}"><div><span class="asset-mark">${esc(item.symbol?.slice(0, 2) || '?')}</span><span><small>${esc(item.side)} · ${formatDate(item.occurred_at)}</small><b>${esc(item.symbol)} ${formatMoney(item.filled_notional ?? item.notional)}</b></span></div>${badge(item.confirmed_execution ? 'confirmed' : item.status, item.confirmed_execution ? 'confirmed fill' : item.status)}<p>${item.confirmed_execution ? 'Broker placement, terminal fill, and run reconciliation are all present.' : 'Open the dossier to inspect the retained state and any missing proof.'}</p><span class="open-dossier">OPEN FULL DOSSIER ${icon('arrow')}</span></button>`
}

function runs() {
  const data = state.data
  const selected = data.runs.find(item => item.run_id === state.selectedRun) || data.runs[0]
  const events = selected ? data.events.filter(item => item.run_id === selected.run_id).sort((a, b) => a.occurred_at.localeCompare(b.occurred_at)) : []
  const orders = selected ? data.trades.filter(item => item.run_id === selected.run_id) : []
  return `${pageHeader('OPERATIONS / RUNS', 'The autonomous cycle, readable.', 'Each run is an idempotent state machine. Select one to inspect what advanced, what held, and what reached the broker.')}
    <section class="runs-layout">
      <div class="run-list" role="list">${data.runs.length ? data.runs.map(item => `<button role="listitem" data-run="${esc(item.run_id)}" class="run-row ${selected?.run_id === item.run_id ? 'active' : ''}"><span class="run-state ${cls(item.status)}">${item.status === 'completed' || item.status === 'shadow_complete' ? icon('check') : item.status === 'failed' || item.status === 'risk_rejected' ? icon('alert') : '<i></i>'}</span><span><small>${esc(item.cycle_key)}</small><b>${esc(item.status.replaceAll('_', ' '))}</b><p>${esc(item.detail || 'No operator detail recorded.')}</p></span><time>${formatDate(item.started_at)}</time></button>`).join('') : empty('No autonomous runs have been recorded.')}</div>
      <aside class="panel run-inspector">
        ${selected ? `<div class="panel-heading"><div><small>SELECTED RUN</small><h2>${esc(selected.status.replaceAll('_', ' '))}</h2><p><code>${esc(selected.run_id)}</code></p></div>${badge(selected.status)}</div>
          <dl class="run-facts"><div><dt>Mandate</dt><dd>${esc(selected.mandate_id)}</dd></div><div><dt>Mode</dt><dd>${esc(selected.mode)}</dd></div><div><dt>Started</dt><dd>${formatDate(selected.started_at)}</dd></div><div><dt>Updated</dt><dd>${formatDate(selected.updated_at)}</dd></div></dl>
          <h3>Recorded timeline</h3>${events.length ? `<ol class="run-timeline">${events.map(item => `<li><i></i><span><b>${esc(friendlyEvent(item.event_type))}</b><small>${formatDate(item.occurred_at)}</small>${eventSummary(item)}</span></li>`).join('')}</ol>` : empty('No runtime events were retained for this run.')}
          ${orders.length ? `<div class="linked-orders"><h3>Linked orders</h3>${orders.map(item => tradeCard(item, true)).join('')}</div>` : '<p class="no-orders">No broker order was proposed in this run.</p>'}` : empty('Select a run to inspect it.')}
      </aside>
    </section>`
}

function system() {
  const data = state.data
  const mandate = data.mandates?.[0]
  const snapshot = data.health?.snapshot || {}
  const stages = [
    ['01', 'Observe broker truth', 'Account, positions, open orders, quotes, and freshness enter a typed snapshot.'],
    ['02', 'Research current conditions', 'Completed-session market intelligence and attributed external sources are content-addressed.'],
    ['03', 'Form a bounded decision', 'The model chooses invest or hold, cites evidence, states uncertainty, and proposes exact allocations.'],
    ['04', 'Apply deterministic policy', 'Budget, cash, concentration, liquidity, drawdown, turnover, session, and freshness rules authorize or reject.'],
    ['05', 'Issue narrow authority', 'A live order needs a short-lived, single-use permit tied to the exact reviewed request.'],
    ['06', 'Reconcile external truth', 'Placement and terminal broker state are read back. Ambiguity fails closed and may halt trading.'],
  ]
  return `${pageHeader('SYSTEM / METHOD', 'The model proposes. Code authorizes.', 'A model can suggest. It cannot authorize itself. Edgecraft keeps that boundary deterministic.')}
    <section class="trust-boundary">
      <div><small>TRUST BOUNDARY</small><h2>Three actors.<br>One narrow handoff.</h2><p>Every live side effect must cross both deterministic policy and an exact-order permit.</p></div>
      <div class="actors"><article><span>01</span><small>PROBABILISTIC</small><h3>Model proposes</h3><p>Interprets evidence and may elect to hold cash.</p></article><b>→</b><article><span>02</span><small>DETERMINISTIC</small><h3>Policy authorizes</h3><p>Enforces rules the model cannot bypass at runtime.</p></article><b>→</b><article><span>03</span><small>EXTERNAL TRUTH</small><h3>Broker executes</h3><p>Final state is independently reconciled and audited.</p></article></div>
    </section>
    <section class="method-grid">${stages.map(([id, title, copy]) => `<article><span>${id}</span><div><h3>${title}</h3><p>${copy}</p></div></article>`).join('')}</section>
    <section class="system-grid">
      <article class="panel"><div class="section-heading"><div><small>ACTIVE MANDATE</small><h2>${esc(mandate?.mandate_id || 'Not configured')}</h2></div>${mandate ? badge(mandate.mode) : ''}</div>${mandate ? `<dl class="system-facts"><div><dt>Frequency</dt><dd>${esc(mandate.cycle_frequency)}</dd></div><div><dt>Cycle ceiling</dt><dd>${formatMoney(mandate.cycle_budget)}</dd></div><div><dt>Benchmark</dt><dd>${esc(mandate.benchmark)}</dd></div><div><dt>Risk posture</dt><dd>${esc(mandate.risk_level)}</dd></div><div class="wide"><dt>Eligible universe</dt><dd>${mandate.universe.map(symbol => `<span>${esc(symbol)}</span>`).join('')}</dd></div></dl>` : empty('No mandate is registered in the ledger.')}</article>
      <article class="panel"><div class="section-heading"><div><small>CONTROL SNAPSHOT</small><h2>Authority and recovery</h2></div>${badge(data.health?.status || 'unknown')}</div><dl class="system-facts"><div><dt>Kill switch</dt><dd>${snapshot.trading_halted ? 'ACTIVE' : 'Clear'}</dd></div><div><dt>Unresolved orders</dt><dd>${snapshot.unresolved_order_count ?? 0}</dd></div><div><dt>Failed runs · 24h</dt><dd>${snapshot.failed_runs_24h ?? 0}</dd></div><div><dt>Issued permits</dt><dd>${snapshot.permits_by_status?.issued || 0}</dd></div><div class="wide"><dt>Safety status</dt><dd>${esc(data.health?.reasons?.join(' · ') || 'No active control-plane reason requires operator action.')}</dd></div></dl></article>
    </section>
    <aside class="read-only-boundary">${icon('database')}<div><b>This interface is deliberately read-only.</b><p>It can expose mandate, evidence, policy, permits, and broker outcomes. It cannot issue authority, place an order, or disable a safety control.</p></div></aside>`
}

function selectedPerformance() {
  if (!state.data.performance?.length) return null
  const activeMandate = state.data.mandates?.[0]?.mandate_id
  return state.data.performance.find(item => item.mandate_id === activeMandate) || state.data.performance[0]
}

function portfolioChart(points) {
  if (!points.length) return emptyChart('No portfolio observations')
  const values = points.map(item => Number(item.portfolio_value)).filter(Number.isFinite)
  if (!values.length) return emptyChart('No valued observations')
  const width = 800, height = 238, left = 22, right = 22, top = 22, bottom = 34
  const min = Math.min(...values), max = Math.max(...values), spread = Math.max(max - min, Math.max(max * 0.04, 1))
  const x = index => left + index * (width - left - right) / Math.max(1, values.length - 1)
  const y = value => top + (max + spread * 0.35 - value) * (height - top - bottom) / (spread * 1.7)
  const path = values.map((value, index) => `${index ? 'L' : 'M'}${x(index)},${y(value)}`).join(' ')
  const area = `${path}L${x(values.length - 1)},${height - bottom}L${x(0)},${height - bottom}Z`
  return `<svg class="line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Verified portfolio values across ${values.length} observations"><defs><linearGradient id="portfolio-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".18"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>${[0, 1, 2, 3].map(index => `<line x1="${left}" x2="${width - right}" y1="${top + index * (height - top - bottom) / 3}" y2="${top + index * (height - top - bottom) / 3}"/>`).join('')}<path class="area" d="${area}"/><path class="main-line" d="${path}"/>${values.map((value, index) => `<circle cx="${x(index)}" cy="${y(value)}" r="4"><title>${formatDate(points[index].as_of)} · ${formatMoney(value)}</title></circle>`).join('')}<text x="${left}" y="${height - 7}">${esc(formatDate(points[0].as_of).split(',')[0])}</text><text x="${width - right}" y="${height - 7}" text-anchor="end">${esc(formatDate(points.at(-1).as_of).split(',')[0])}</text></svg>`
}

function comparisonChart(points, tall = false) {
  if (!points?.length) return emptyChart('No evaluation observations')
  const width = 820, height = tall ? 310 : 240, left = 52, right = 24, top = 24, bottom = 38
  const keys = ['agent', 'benchmark', 'strategic']
  const values = points.flatMap(point => keys.map(key => Number(point[key]))).filter(Number.isFinite)
  const min = Math.min(...values), max = Math.max(...values), spread = Math.max(max - min, Math.max(max * 0.03, 1))
  const x = index => left + index * (width - left - right) / Math.max(1, points.length - 1)
  const y = value => top + (max + spread * 0.2 - value) * (height - top - bottom) / (spread * 1.4)
  const path = key => points.map((point, index) => `${index ? 'L' : 'M'}${x(index)},${y(Number(point[key]))}`).join(' ')
  return `<div class="comparison-chart"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Cash-flow-matched agent, benchmark, and strategic sleeve values">${[0, 1, 2, 3].map(index => `<line class="gridline" x1="${left}" x2="${width - right}" y1="${top + index * (height - top - bottom) / 3}" y2="${top + index * (height - top - bottom) / 3}"/>`).join('')}${keys.map(key => `<path class="${key}" d="${path(key)}"/>`).join('')}<text x="${left}" y="${height - 8}">${esc(formatDate(points[0].observed_at).split(',')[0])}</text><text x="${width - right}" y="${height - 8}" text-anchor="end">${esc(formatDate(points.at(-1).observed_at).split(',')[0])}</text></svg><div class="chart-legend"><span><i class="agent"></i>Agent</span><span><i class="benchmark"></i>Benchmark</span><span><i class="strategic"></i>Strategic</span></div></div>`
}

function performanceMetrics(report) {
  const sleeves = report.sleeves || {}
  return `<div class="performance-metrics"><span><small>Agent return</small><b>${formatPct(sleeves.agent?.return_on_contributions)}</b></span><span><small>Benchmark return</small><b>${formatPct(sleeves.benchmark?.return_on_contributions)}</b></span><span><small>Excess</small><b>${formatPct(report.agent_excess_return_on_contributions)}</b></span><span><small>Observations</small><b>${report.observation_count ?? 0}</b></span></div>${report.minimum_interpretation ? `<p class="measurement-note">${esc(report.minimum_interpretation)}</p>` : ''}`
}

function emptyChart(label) {
  return `<div class="empty-chart" role="img" aria-label="${esc(label)}"><span></span><span></span><span></span><p>${esc(label)}</p></div>`
}

function empty(message) {
  return `<div class="empty-state"><span>—</span><p>${esc(message)}</p></div>`
}

async function openTrade(orderKey, trigger) {
  state.lastTrigger = trigger || document.activeElement
  state.tradeLoading = true
  state.trade = null
  state.tradeError = null
  state.tradeTab = 'journey'
  render()
  try {
    const response = await fetch(`/api/trades/${encodeURIComponent(orderKey)}`)
    if (!response.ok) throw new Error(`Trade dossier returned ${response.status}`)
    state.trade = await response.json()
  } catch (error) {
    state.tradeError = error.message || 'The trade dossier is unavailable.'
  } finally {
    state.tradeLoading = false
    render()
    $('[data-close-trade]')?.focus()
  }
}

function closeTrade() {
  state.trade = null
  state.tradeLoading = false
  state.tradeError = null
  render()
  state.lastTrigger?.focus?.()
}

function tradeLoading() {
  return `<div class="modal-backdrop" data-close-trade></div><aside class="trade-dossier loading" role="dialog" aria-modal="true" aria-label="Loading trade dossier"><button class="dossier-close" data-close-trade aria-label="Close trade dossier">${icon('close')}</button><div class="dossier-loader"><span></span><b>Joining the immutable trade record</b><p>Decision · evidence · policy · permit · broker · reconciliation</p>${state.tradeError ? `<em>${esc(state.tradeError)}</em>` : ''}</div></aside>`
}

function tradeDossier(detail) {
  const order = detail.order || {}
  const packet = detail.decision_packet?.payload || {}
  const decision = packet.observation?.decision || detail.recovered_decision_reasoning || detail.proposal?.payload?.decision_reasoning || {}
  const events = detail.order_events || []
  const fill = [...events].reverse().find(item => ['filled', 'partially_filled'].includes(item.event_type))?.payload || {}
  const tabs = { journey: () => dossierJourney(detail, decision), evidence: () => dossierEvidence(detail, decision), data: () => dossierData(detail) }
  return `<div class="modal-backdrop" data-close-trade></div><aside class="trade-dossier" role="dialog" aria-modal="true" aria-labelledby="dossier-title">
    <header class="dossier-header"><button class="dossier-close" data-close-trade aria-label="Close trade dossier">${icon('close')}</button><small>IMMUTABLE ORDER DOSSIER</small><div><span class="dossier-symbol">${esc(order.symbol?.slice(0, 2) || '?')}</span><span><h2 id="dossier-title">${esc(order.side?.toUpperCase())} ${esc(order.symbol)}</h2><p><code>${esc(order.order_key)}</code></p></span></div><div class="dossier-summary">${badge(detail.reconciliation?.confirmed_execution ? 'confirmed' : order.status, detail.reconciliation?.confirmed_execution ? 'confirmed execution' : order.status)}<span><small>REQUESTED</small><b>${formatMoney(order.notional)}</b></span><span><small>FILLED</small><b>${formatMoney(fill.filled_notional)}</b></span><span><small>AVG PRICE</small><b>${formatMoney(fill.average_fill_price)}</b></span></div></header>
    <nav class="dossier-tabs" aria-label="Trade dossier sections">${[['journey', 'Full journey'], ['evidence', `Evidence (${decision.evidence_items?.length || 0})`], ['data', 'Complete record']].map(([id, label]) => `<button data-trade-tab="${id}" class="${state.tradeTab === id ? 'active' : ''}" aria-selected="${state.tradeTab === id}">${label}</button>`).join('')}</nav>
    <div class="dossier-body">${tabs[state.tradeTab]()}</div>
  </aside>`
}

function dossierJourney(detail, decision) {
  const packet = detail.decision_packet?.payload || {}
  const observation = packet.observation || {}
  const risk = detail.proposal?.payload?.risk || {}
  const permit = detail.permits?.at(-1)
  const reconciliation = detail.reconciliation || {}
  const gaps = detail.audit_gaps || []
  const steps = [
    { id: '01', name: 'Observe', state: observation.account ? 'complete' : 'partial', meta: observation.account ? `${formatMoney(observation.account.portfolio_value)} portfolio · ${formatMoney(observation.account.buying_power)} buying power` : 'Summary retained; full canonical account snapshot missing', body: observation.account ? `<dl class="stage-facts"><div><dt>Snapshot time</dt><dd>${formatDate(observation.account.as_of)}</dd></div><div><dt>Positions</dt><dd>${observation.account.positions?.length || 0}</dd></div><div><dt>Open orders</dt><dd>${observation.account.open_orders?.length || 0}</dd></div><div><dt>Quotes</dt><dd>${observation.quotes?.length || 0}</dd></div></dl>` : eventStageDetail(detail, 'observation_completed') },
    { id: '02', name: 'Research', state: packet.market_intelligence || packet.external_context || eventByType(detail, 'external_context_collected') ? 'complete' : 'missing', meta: `${decision.evidence_items?.length || 0} typed evidence items · ${decision.data_sources?.length || 0} named data sources`, body: sourceSummary(packet, detail) },
    { id: '03', name: 'Decide', state: decision.hypothesis ? (detail.decision_packet ? 'complete' : 'partial') : 'missing', meta: `${esc(decision.action || 'unknown')} · ${decision.confidence !== undefined ? formatPct(Number(decision.confidence), 0) + ' confidence' : 'confidence unavailable'}`, body: `<blockquote>${esc(decision.hypothesis || 'No complete decision hypothesis was retained.')}</blockquote>${listBlock('Alternatives considered', decision.alternatives_considered)}${listBlock('Risks named before execution', decision.risks)}` },
    { id: '04', name: 'Gate', state: risk.approved_for_review ? 'complete' : 'blocked', meta: risk.approved_for_review ? `Approved · ${formatMoney(risk.gross_notional)} gross notional` : `${risk.violations?.length || 0} policy violations`, body: `<dl class="stage-facts"><div><dt>Policy</dt><dd>${esc(detail.proposal?.payload?.policy_name)}</dd></div><div><dt>Policy digest</dt><dd><code>${esc(detail.proposal?.payload?.policy_digest)}</code></dd></div><div><dt>Projected cash</dt><dd>${formatMoney(risk.projected_cash)}</dd></div><div><dt>Spread</dt><dd>${formatBps(Object.values(risk.spread_bps || {})[0])}</dd></div></dl>${listBlock('Violations', risk.violations)}${listBlock('Warnings', risk.warnings)}` },
    { id: '05', name: 'Permit', state: permit ? 'complete' : 'missing', meta: permit ? `${esc(permit.status)} · ${esc(permit.allowed_tool)}` : 'No execution permit retained', body: permit ? `<dl class="stage-facts"><div><dt>Issued</dt><dd>${formatDate(permit.issued_at)}</dd></div><div><dt>Expires</dt><dd>${formatDate(permit.expires_at)}</dd></div><div><dt>Claimed</dt><dd>${formatDate(permit.claimed_at)}</dd></div><div><dt>Exact constraints</dt><dd><code>${esc(JSON.stringify(permit.constraints))}</code></dd></div></dl>` : empty('A live placement cannot be considered authorized without a matching permit record.') },
    { id: '06', name: 'Broker', state: detail.order_events?.length ? 'complete' : 'missing', meta: `${detail.order_events?.length || 0} immutable broker transitions`, body: brokerEvents(detail.order_events || []) },
    { id: '07', name: 'Reconcile', state: reconciliation.confirmed_execution ? 'complete' : reconciliation.terminal_state_recorded ? 'partial' : 'missing', meta: reconciliation.confirmed_execution ? 'Placement + fill + completed run confirmed' : 'Execution proof is incomplete', body: `<div class="reconciliation-proof ${reconciliation.confirmed_execution ? 'confirmed' : ''}">${icon(reconciliation.confirmed_execution ? 'check' : 'alert')}<div><b>${reconciliation.confirmed_execution ? 'Confirmed execution' : 'Not fully confirmed'}</b><p>Placement recorded: ${reconciliation.broker_placement_recorded ? 'yes' : 'no'} · Terminal state: ${esc(reconciliation.terminal_status || 'missing')} · Run: ${esc(reconciliation.run_status || 'missing')}</p></div></div>` },
  ]
  return `${gaps.length ? `<aside class="audit-gaps">${icon('alert')}<div><b>${gaps.length} retention gap${gaps.length === 1 ? '' : 's'} on this historical trade</b><ul>${gaps.map(item => `<li>${esc(item)}</li>`).join('')}</ul></div></aside>` : `<aside class="integrity-proof">${icon('check')}<div><b>Decision packet integrity ${detail.packet_integrity?.verified ? 'verified' : 'available'}</b><p>${detail.packet_integrity?.recorded_sha256 ? `SHA-256 ${esc(detail.packet_integrity.recorded_sha256)}` : 'Complete retained packet available.'}</p></div></aside>`}
    <section class="journey">${steps.map(step => `<article class="journey-step ${step.state}"><div class="step-rail"><span>${step.state === 'complete' ? icon('check') : step.state === 'blocked' || step.state === 'missing' ? icon('alert') : step.id}</span><i></i></div><div class="step-content"><small>STAGE ${step.id} · ${esc(step.state.toUpperCase())}</small><h3>${esc(step.name)}</h3><p class="step-meta">${step.meta}</p><div class="step-detail">${step.body}</div></div></article>`).join('')}</section>
    <section class="immutable-timeline"><div class="dossier-section-title"><small>ALL RETAINED TRANSITIONS</small><h3>Run and broker timeline</h3></div>${timeline(detail.timeline || [])}</section>`
}

function dossierEvidence(detail, decision) {
  const packet = detail.decision_packet?.payload || {}
  const items = decision.evidence_items || []
  const context = packet.external_context || eventByType(detail, 'external_context_collected')?.payload || {}
  const sources = context.sources || []
  const quotes = packet.observation?.quotes || []
  return `<section class="evidence-intro"><div><small>DECISION INVENTORY</small><h3>Every cited input, source, and value</h3><p>Evidence is shown exactly as retained. Missing historical data is labeled; it is never reconstructed from the outcome.</p></div><dl><div><dt>Typed items</dt><dd>${items.length}</dd></div><div><dt>Quotes</dt><dd>${quotes.length}</dd></div><div><dt>External sources</dt><dd>${sources.length}</dd></div></dl></section>
    ${items.length ? `<section class="evidence-grid">${items.map(evidenceCard).join('')}</section>` : `<aside class="audit-gaps compact">${icon('alert')}<div><b>No typed evidence inventory was retained for this historical order.</b><p>${esc(detail.recovered_decision_reasoning?.recovery_note || 'Future decision packets are required to include every material evidence item.')}</p></div></aside>`}
    ${quotes.length ? `<section class="evidence-section"><div class="dossier-section-title"><small>POINT-IN-TIME MARKET DATA</small><h3>${quotes.length} retained quotes</h3></div><div class="quote-grid">${quotes.map(item => `<article><b>${esc(item.symbol)}</b><strong>${formatMoney(item.last)}</strong><span>Bid ${formatMoney(item.bid)} · Ask ${formatMoney(item.ask)}</span><small>${esc(item.market_session)} · ${formatDate(item.as_of)}</small></article>`).join('')}</div></section>` : ''}
    ${sources.length ? `<section class="evidence-section"><div class="dossier-section-title"><small>EXTERNAL CONTEXT</small><h3>${sources.length} attributed sources collected</h3></div><div class="source-list">${sources.map(source => `<a href="${esc(safeUrl(source.url))}" target="_blank" rel="noreferrer"><span><small>${esc(source.channel || 'source')} · ${formatDate(source.published_at || source.retrieved_at)}</small><b>${esc(source.title || source.url)}</b><p>${esc(source.author || source.url)}</p></span>${icon('arrow')}</a>`).join('')}</div></section>` : ''}`
}

function evidenceCard(item) {
  return `<article class="evidence-card"><header><span>${esc(item.category)}</span>${item.symbol ? `<b>${esc(item.symbol)}</b>` : ''}</header><h3>${esc(item.summary)}</h3><p>${esc(item.source)}</p>${item.metrics?.length ? `<dl>${item.metrics.map(metric => `<div><dt>${esc(metric.name)}</dt><dd>${esc(metric.value)}${metric.unit ? ` ${esc(metric.unit)}` : ''}</dd></div>`).join('')}</dl>` : ''}<footer><code>${esc(item.evidence_id)}</code><time>${formatDate(item.source_timestamp || item.observed_at)}</time></footer></article>`
}

function dossierData(detail) {
  const records = [
    ['Decision packet', detail.decision_packet || { missing: true, audit_gaps: detail.audit_gaps }],
    ['Proposal + policy result', detail.proposal],
    ['Permit records', detail.permits],
    ['Broker order events', detail.order_events],
    ['Runtime events', detail.runtime_events],
    ['Performance observation', detail.evaluation || { missing: true }],
    ['Reconciliation proof', detail.reconciliation],
  ]
  return `<aside class="complete-record-note">${icon('database')}<div><b>Complete privacy-safe retained record</b><p>Account identifiers are one-way references and permit constraints are redacted before storage. No credential or OAuth material is exposed.</p></div></aside><section class="raw-records">${records.map(([label, value], index) => `<details ${index === 0 ? 'open' : ''}><summary><span>${esc(label)}</span><b>${Array.isArray(value) ? `${value.length} records` : value?.missing ? 'missing' : 'JSON'}</b></summary><pre><code>${json(value)}</code></pre></details>`).join('')}</section>`
}

function sourceSummary(packet, detail) {
  const context = packet.external_context || eventByType(detail, 'external_context_collected')?.payload
  const intelligence = packet.market_intelligence
  return `<dl class="stage-facts"><div><dt>External provider</dt><dd>${esc(context?.provider || 'not retained')}</dd></div><div><dt>Attributed sources</dt><dd>${context?.sources?.length || 0}</dd></div><div><dt>Fresh sources</dt><dd>${context?.fresh_source_count ?? '—'}</dd></div><div><dt>Market snapshot</dt><dd>${intelligence ? 'content-addressed' : 'not retained'}</dd></div></dl>`
}

function eventByType(detail, type) {
  return detail.runtime_events?.find(item => item.event_type === type)
}

function eventStageDetail(detail, type) {
  const event = eventByType(detail, type)
  return event ? `<pre class="inline-json"><code>${json(event.payload)}</code></pre>` : empty('No retained event summary is available.')
}

function listBlock(title, items) {
  return items?.length ? `<div class="list-block"><b>${esc(title)}</b><ul>${items.map(item => `<li>${esc(item)}</li>`).join('')}</ul></div>` : ''
}

function brokerEvents(events) {
  return events.length ? `<ol class="broker-events">${events.map(event => `<li><span>${badge(event.event_type)}</span><div><b>${formatDate(event.occurred_at)}</b><p>${event.payload.broker_state ? `Broker state: ${esc(event.payload.broker_state)}` : ''}${event.payload.filled_notional ? ` · Filled ${formatMoney(event.payload.filled_notional)} at ${formatMoney(event.payload.average_fill_price)}` : ''}</p></div></li>`).join('')}</ol>` : empty('No broker transition is recorded for this proposal.')
}

function timeline(items) {
  return items.length ? `<ol class="full-timeline">${items.map(item => `<li><span class="timeline-dot ${cls(item.stream)}"></span><div><small>${esc(item.stream)} · ${formatDate(item.occurred_at)}</small><b>${esc(friendlyEvent(item.event_type))}</b><p>${esc(summaryFromPayload(item.payload))}</p></div></li>`).join('')}</ol>` : empty('No runtime or broker timeline was retained.')
}

function friendlyEvent(value) {
  return String(value || '').replace(/^run_/, '').replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase())
}

function summaryFromPayload(payload = {}) {
  if (payload.detail) return payload.detail
  if (payload.reason) return payload.reason
  if (payload.proposal_id) return `Proposal ${payload.proposal_id}${payload.order_key ? ` · order ${payload.order_key}` : ''}`
  if (payload.decision_action) return `${payload.decision_action} decision · ${payload.allocation_notional || 0} allocation`
  if (payload.status) return String(payload.status)
  if (payload.cycle_key) return payload.cycle_key
  return Object.keys(payload).slice(0, 4).join(' · ') || 'No summary fields retained.'
}

function eventSummary(event) {
  const summary = summaryFromPayload(event.payload)
  return summary ? `<p>${esc(summary)}</p>` : ''
}

function bind() {
  $$('[data-refresh]').forEach(button => button.addEventListener('click', load))
  $$('[data-menu]').forEach(button => button.addEventListener('click', () => { state.menuOpen = true; render() }))
  $$('[data-menu-close]').forEach(button => button.addEventListener('click', () => { state.menuOpen = false; render() }))
  $$('.nav-item').forEach(link => link.addEventListener('click', () => { state.menuOpen = false }))
  $$('[data-trade]').forEach(button => button.addEventListener('click', () => openTrade(button.dataset.trade, button)))
  $$('[data-close-trade]').forEach(button => button.addEventListener('click', closeTrade))
  $$('[data-trade-tab]').forEach(button => button.addEventListener('click', () => { state.tradeTab = button.dataset.tradeTab; render(); $(`[data-trade-tab="${state.tradeTab}"]`)?.focus() }))
  $$('[data-trade-filter]').forEach(button => button.addEventListener('click', () => { state.tradeFilter = button.dataset.tradeFilter; render() }))
  $$('[data-run]').forEach(button => button.addEventListener('click', () => { state.selectedRun = button.dataset.run; render() }))
}

window.addEventListener('hashchange', () => { state.menuOpen = false; render() })
window.addEventListener('keydown', event => { if (event.key === 'Escape' && (state.trade || state.tradeLoading)) closeTrade() })
load()
