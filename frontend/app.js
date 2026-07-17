const COLORS = ['#6be4b3', '#8bacff', '#f4bd6a', '#df8cff', '#ff7d8d', '#77d7e8']
const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const state = { schemas: [], selected: new Map(), result: null, active: '' }

const pct = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`
const dec = value => value == null ? '—' : Number(value).toFixed(2)
const esc = value => String(value).replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char])

document.getElementById('root').innerHTML = `
  <div class="shell">
    <header class="topbar">
      <div class="brand"><div class="mark">⌁</div><span>EDGECRAFT</span><small>RESEARCH TERMINAL</small></div>
      <div class="system"><span class="pulse"></span> POINT-IN-TIME ENGINE <span>v0.1</span></div>
    </header>
    <main>
      <section class="hero">
        <div><p class="eyebrow">ADVERSARIAL STRATEGY LAB</p><h1>Build less convincing<br><em>backtests.</em></h1></div>
        <p class="hero-copy">Design, falsify, and compare systematic stock strategies with next-bar execution, realistic costs, resampled uncertainty, and multiple-testing penalties.</p>
      </section>
      <div class="workspace">
        <aside class="config-panel">
          <section class="config-section">
            <h3>⌘ Experiment</h3>
            <label>Symbols<input id="symbols" value="SPY, QQQ" placeholder="SPY, QQQ"></label>
            <div class="two-col"><label>Start<input id="start" type="date" value="2015-01-01"></label><label>End<input id="end" type="date" value="2026-07-15"></label></div>
            <div class="two-col"><label>Initial capital<input id="capital" type="number" value="10000"></label><label>Contribution<input id="contribution" type="number" value="250"></label></div>
            <div class="two-col"><label>Schedule<select id="frequency"><option value="daily">Daily</option><option value="weekly" selected>Weekly</option><option value="monthly">Monthly</option></select></label><label>Data<select id="source"><option value="synthetic">Synthetic demo</option><option value="market">Yahoo market</option></select></label></div>
          </section>
          <section class="config-section">
            <h3>◈ Execution model</h3>
            ${rangeHTML('slippage', 'Slippage', 2, 0, 25, .5, ' bps')}
            ${rangeHTML('spread', 'Spread', 1, 0, 25, .5, ' bps')}
            ${rangeHTML('bootstrap', 'Bootstrap', 300, 0, 1000, 50, ' samples')}
          </section>
          <section class="config-section">
            <h3>◇ Strategies · <span id="strategy-count">0</span></h3>
            <div id="strategies" class="strategy-list"><div class="no-trades">Loading strategy catalog…</div></div>
          </section>
          <button id="run" class="run-button">▶ RUN BACKTEST MATRIX</button>
          <div id="error"></div>
        </aside>
        <section id="results" class="results">${emptyHTML(false)}</section>
      </div>
    </main>
  </div>`

function rangeHTML(id, label, value, min, max, step, suffix = '') {
  return `<label class="range-label"><span>${esc(label)}<output id="${id}-out">${value}${suffix}</output></span><input id="${id}" type="range" value="${value}" min="${min}" max="${max}" step="${step}" data-suffix="${suffix}"></label>`
}

function emptyHTML(loading) {
  return `<div class="empty"><div class="radar"><div></div><div></div><b>${loading ? '⋯' : '⌁'}</b></div><p class="eyebrow">${loading ? 'SIMULATING' : 'EXPERIMENT READY'}</p><h2>${loading ? 'Walking forward through history…' : 'Configure the assumptions. Then try to break the idea.'}</h2><p>${loading ? 'Signals, next-open fills, costs, resampling, and multiple-testing controls are being evaluated.' : 'Start with the synthetic demo for a deterministic run, then switch to adjusted market data.'}</p></div>`
}

document.querySelectorAll('input[type="range"]').forEach(input => input.addEventListener('input', event => {
  document.getElementById(`${event.target.id}-out`).textContent = `${event.target.value}${event.target.dataset.suffix || ''}`
}))

fetch('/api/strategies').then(response => response.json()).then(schemas => {
  state.schemas = schemas
  schemas.slice(0, 3).forEach(schema => state.selected.set(schema.name, Object.fromEntries(schema.params.map(param => [param.key, param.value]))))
  renderStrategies()
}).catch(() => showError('Could not load strategy definitions.'))

function renderStrategies() {
  document.getElementById('strategy-count').textContent = state.selected.size
  document.getElementById('strategies').innerHTML = state.schemas.map(schema => {
    const chosen = state.selected.get(schema.name)
    const params = chosen ? schema.params.map(param => `
      <label class="range-label"><span>${esc(param.label)}<output>${chosen[param.key]}</output></span>
      <input type="range" min="${param.min}" max="${param.max}" step="${param.step}" value="${chosen[param.key]}" data-strategy="${schema.name}" data-param="${param.key}"></label>`).join('') : ''
    return `<div class="strategy-card ${chosen ? 'selected' : ''}">
      <button class="strategy-toggle" data-toggle="${schema.name}"><span class="check">${chosen ? '✓' : ''}</span><span><strong>${esc(schema.label)}</strong><small>${esc(schema.description)}</small></span><span>⌄</span></button>
      ${chosen && params ? `<div class="params">${params}</div>` : ''}
    </div>`
  }).join('')
  document.querySelectorAll('[data-toggle]').forEach(button => button.addEventListener('click', () => {
    const schema = state.schemas.find(item => item.name === button.dataset.toggle)
    if (state.selected.has(schema.name)) state.selected.delete(schema.name)
    else state.selected.set(schema.name, Object.fromEntries(schema.params.map(param => [param.key, param.value])))
    renderStrategies()
  }))
  document.querySelectorAll('[data-param]').forEach(input => input.addEventListener('input', () => {
    state.selected.get(input.dataset.strategy)[input.dataset.param] = Number(input.value)
    input.previousElementSibling.querySelector('output').textContent = input.value
  }))
}

document.getElementById('run').addEventListener('click', runBacktest)

async function runBacktest() {
  if (!state.selected.size) return showError('Select at least one strategy.')
  const run = document.getElementById('run')
  run.disabled = true
  run.textContent = '◌ RUNNING EXPERIMENT'
  document.getElementById('error').innerHTML = ''
  document.getElementById('results').innerHTML = emptyHTML(true)
  const body = {
    symbols: document.getElementById('symbols').value.split(',').map(value => value.trim()).filter(Boolean),
    start: document.getElementById('start').value,
    end: document.getElementById('end').value,
    initial_capital: Number(document.getElementById('capital').value),
    contribution_amount: Number(document.getElementById('contribution').value),
    contribution_frequency: document.getElementById('frequency').value,
    costs: { commission_per_order: 0, slippage_bps: Number(document.getElementById('slippage').value), spread_bps: Number(document.getElementById('spread').value) },
    strategies: [...state.selected].map(([name, params]) => ({ name, params })),
    validation: { bootstrap_samples: Number(document.getElementById('bootstrap').value), bootstrap_block_size: 20, cscv_slices: 8, random_seed: 7 },
  }
  try {
    const source = document.getElementById('source').value
    const response = await fetch(`/api/backtests?data_source=${source}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.detail || 'Backtest failed')
    state.result = payload
    state.active = payload.results[0].strategy
    renderResults()
  } catch (error) {
    document.getElementById('results').innerHTML = emptyHTML(false)
    showError(error.message)
  } finally {
    run.disabled = false
    run.textContent = '▶ RUN BACKTEST MATRIX'
  }
}

function showError(message) {
  document.getElementById('error').innerHTML = `<div class="error">⚠ ${esc(message)}</div>`
}

function renderResults() {
  const result = state.result
  const best = result.results.reduce((winner, item) => (item.metrics.sharpe ?? -Infinity) > (winner.metrics.sharpe ?? -Infinity) ? item : winner)
  document.getElementById('results').innerHTML = `
    <div class="run-meta"><span><span class="pulse"></span> COMPLETE</span><span>${result.meta.sessions.toLocaleString()} SESSIONS</span><span>${result.meta.start} → ${result.meta.end}</span><span>${esc(result.meta.execution.toUpperCase())}</span></div>
    <div class="metric-grid">
      ${metricHTML('Leader by Sharpe', best.strategy.replaceAll('_', ' '), `Sharpe ${dec(best.metrics.sharpe)}`)}
      ${metricHTML('Overfit probability', pct(result.validation.probability_backtest_overfitting), `CSCV · ${result.validation.cscv_slices} slices`, (result.validation.probability_backtest_overfitting ?? 0) > .5)}
      ${metricHTML('Strategies tested', result.meta.strategies_tested, `${result.validation.bootstrap_samples} bootstrap paths`)}
    </div>
    <div class="panel chart-panel"><div class="panel-head"><div><p class="eyebrow">PORTFOLIO VALUE</p><h2>Equity curves</h2></div><span>USD · POINT-IN-TIME</span></div><div id="equity-chart" class="native-chart"></div></div>
    <div class="panel"><div class="panel-head"><div><p class="eyebrow">ROBUSTNESS TABLE</p><h2>Risk-adjusted comparison</h2></div><span>CLICK A ROW FOR FILLS</span></div>${tableHTML(result.results)}</div>
    <div id="trade-log"></div>`
  renderChart(result.results)
  document.querySelectorAll('[data-result]').forEach(row => row.addEventListener('click', () => { state.active = row.dataset.result; renderTradeLog(); document.querySelectorAll('[data-result]').forEach(item => item.classList.toggle('active-row', item.dataset.result === state.active)) }))
  renderTradeLog()
}

function metricHTML(label, value, note, warn = false) {
  return `<div class="metric ${warn ? 'warn' : ''}"><small>${esc(label)}</small><strong>${esc(value)}</strong><span>${esc(note)}</span></div>`
}

function tableHTML(results) {
  return `<div class="table-scroll"><table><thead><tr><th>Strategy</th><th>End value</th><th>Ann. return</th><th>Sharpe</th><th>95% Sharpe CI</th><th>Max DD</th><th>DSR prob.</th><th>Cash drag</th><th>Fills</th></tr></thead><tbody>${results.map((item, index) => `<tr data-result="${item.strategy}" class="${state.active === item.strategy ? 'active-row' : ''}"><td><span class="row-dot" style="background:${COLORS[index % COLORS.length]}"></span>${esc(item.strategy.replaceAll('_', ' '))}</td><td>${money.format(item.metrics.ending_equity || 0)}</td><td>${pct(item.metrics.annual_return)}</td><td>${dec(item.metrics.sharpe)}</td><td>${dec(item.metrics.sharpe_low)} – ${dec(item.metrics.sharpe_high)}</td><td>${pct(item.metrics.max_drawdown)}</td><td>${pct(item.metrics.deflated_sharpe_probability)}</td><td>${pct(item.metrics.cash_drag)}</td><td>${item.metrics.fills}</td></tr>`).join('')}</tbody></table></div>`
}

function renderChart(results) {
  const width = 1000, height = 330, pad = { left: 70, right: 24, top: 24, bottom: 38 }
  const all = results.flatMap(result => result.series.map(point => point.equity))
  const min = Math.min(...all) * .96, max = Math.max(...all) * 1.04
  const x = (i, n) => pad.left + i / Math.max(1, n - 1) * (width - pad.left - pad.right)
  const y = value => pad.top + (max - value) / (max - min || 1) * (height - pad.top - pad.bottom)
  const grid = Array.from({ length: 5 }, (_, i) => {
    const value = min + (max - min) * (4 - i) / 4
    const yy = pad.top + i * (height - pad.top - pad.bottom) / 4
    return `<line x1="${pad.left}" y1="${yy}" x2="${width - pad.right}" y2="${yy}"/><text x="${pad.left - 10}" y="${yy + 4}" text-anchor="end">$${Math.round(value / 1000)}k</text>`
  }).join('')
  const lines = results.map((result, index) => `<path d="${result.series.map((point, i) => `${i ? 'L' : 'M'}${x(i, result.series.length).toFixed(1)},${y(point.equity).toFixed(1)}`).join(' ')}" stroke="${COLORS[index % COLORS.length]}"/><g class="chart-label"><circle cx="${pad.left + index * 180}" cy="${height - 8}" r="4" fill="${COLORS[index % COLORS.length]}"></circle><text x="${pad.left + 10 + index * 180}" y="${height - 4}">${esc(result.strategy.replaceAll('_', ' '))}</text></g>`).join('')
  document.getElementById('equity-chart').innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Equity curves for tested strategies"><g class="grid">${grid}</g><g class="series">${lines}</g></svg>`
}

function renderTradeLog() {
  const result = state.result.results.find(item => item.strategy === state.active)
  const fills = result.fills.slice(-12).reverse()
  document.getElementById('trade-log').innerHTML = `<div class="panel"><div class="panel-head"><div><p class="eyebrow">AUDIT TRAIL</p><h2>${esc(result.strategy.replaceAll('_', ' '))} · recent fills</h2></div><span>${result.fills.length} FILLS RETURNED</span></div>${fills.length ? `<div class="table-scroll"><table><thead><tr><th>Date</th><th>Side</th><th>Symbol</th><th>Quantity</th><th>Price</th><th>Notional</th><th>Reason</th></tr></thead><tbody>${fills.map(fill => `<tr><td>${fill.date}</td><td><span class="side ${fill.side}">${fill.side}</span></td><td>${esc(fill.symbol)}</td><td>${fill.quantity.toFixed(4)}</td><td>${money.format(fill.price)}</td><td>${money.format(fill.notional)}</td><td>${esc(fill.reason.replaceAll('_', ' '))}</td></tr>`).join('')}</tbody></table></div>` : '<div class="no-trades">No fills generated for this configuration.</div>'}</div>`
}
