const COLORS = ['#b9ff66', '#71a7ff', '#ffbd69', '#d88cff', '#ff7184', '#57d5d0']
const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const preciseMoney = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })
const compactMoney = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 })
const state = {
  schemas: [],
  selected: new Map(),
  result: null,
  active: '',
  chartMode: 'equity',
  chartRange: 'all',
  visible: new Set(),
  hoverIndex: null,
  guide: null,
  activeCycleStep: 'mandate',
  learningResult: null,
}

const pct = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`
const signedPct = value => value == null ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
const dec = value => value == null ? '—' : Number(value).toFixed(2)
const esc = value => String(value).replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char])
const title = value => String(value).replaceAll('_', ' ')
const dateLabel = value => new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(`${value}T12:00:00`))

const CHART_MODES = {
  equity: {
    label: 'Portfolio value',
    unit: 'USD · CONTRIBUTED CAPITAL SHOWN AS DASHED LINE',
    value: point => point.equity,
    format: value => money.format(value),
    axis: value => compactMoney.format(value),
  },
  gain: {
    label: 'Gain vs deposits',
    unit: 'USD · EQUITY LESS CUMULATIVE CONTRIBUTED CAPITAL',
    value: point => point.equity - point.net_invested,
    format: value => `${value >= 0 ? '+' : ''}${money.format(value)}`,
    axis: value => compactMoney.format(value),
  },
  drawdown: {
    label: 'Drawdown',
    unit: '% FROM EACH STRATEGY’S PRIOR PEAK',
    value: point => point.drawdown,
    format: pct,
    axis: value => `${Math.round(value * 100)}%`,
  },
  cash: {
    label: 'Idle cash',
    unit: 'USD · UNDEPLOYED CAPITAL',
    value: point => point.cash,
    format: value => money.format(value),
    axis: value => compactMoney.format(value),
  },
  exposure: {
    label: 'Market exposure',
    unit: '% OF PORTFOLIO VALUE INVESTED',
    value: point => point.exposure,
    format: pct,
    axis: value => `${Math.round(value * 100)}%`,
  },
}

document.getElementById('root').innerHTML = `
  <div class="shell">
    <header class="topbar">
      <a class="brand" href="#top" aria-label="Edgecraft home"><div class="mark">⌁</div><span>EDGECRAFT</span><small>AUTONOMY WORKBENCH</small></a>
      <nav class="topnav" aria-label="Primary"><a href="#cycle">How it works</a><a href="#safety-lab">Safety lab</a><a href="#research">Research lab</a></nav>
      <div class="system"><span class="pulse"></span> SHADOW LEARNING MODE <span>v0.3</span></div>
    </header>
    <main id="top">
      <section class="hero learning-hero">
        <div><p class="eyebrow">THE AUTONOMY WORKBENCH</p><h1>See how the agent thinks.<br><em>Then see where code says no.</em></h1></div>
        <div class="hero-side">
          <p class="hero-copy">Follow one weekly contribution from your mandate, through broker observation and model reasoning, into deterministic policy gates. Nothing in this lesson can place a trade.</p>
          <div class="hero-actions"><a class="primary-link" href="#cycle">START THE GUIDED CYCLE ↓</a><a href="#research">OPEN THE RESEARCH LAB</a></div>
        </div>
      </section>
      <section class="trust-model" aria-label="Edgecraft trust model">
        <article><span>01 · PROBABILISTIC</span><h2>Model proposes</h2><p>Codex interprets fresh evidence and returns a typed weekly recommendation—including the option to hold cash.</p></article>
        <i>→</i>
        <article><span>02 · DETERMINISTIC</span><h2>Policy authorizes</h2><p>Python checks every hard boundary. The reasoning model cannot enlarge its own budget or weaken a rule.</p></article>
        <i>→</i>
        <article><span>03 · EXTERNAL TRUTH</span><h2>Broker executes</h2><p>Robinhood is refreshed, reviews the exact order, and receives it only with a valid single-use permit.</p></article>
      </section>
      <section id="cycle" class="learning-section cycle-section">
        <div class="about-intro">
          <p class="eyebrow">01 · GUIDED CYCLE</p>
          <h2>One weekly decision. Six distinct responsibilities.</h2>
          <p>Select a stage to see who owns it, what question it answers, and which real module implements the boundary.</p>
        </div>
        <div id="cycle-map" class="cycle-map loading-card">Loading the real system map…</div>
        <div id="cycle-detail" class="cycle-detail"></div>
      </section>
      <section id="safety-lab" class="learning-section safety-section">
        <div class="about-intro">
          <p class="eyebrow">02 · POLICY SANDBOX</p>
          <h2>Try to break the proposal.</h2>
          <p>This sandbox calls the production mandate and risk-gate modules with synthetic inputs. It is hard-wired to shadow mode and never contacts Robinhood.</p>
        </div>
        <div class="preset-row" aria-label="Learning scenarios">
          <button class="preset active" data-preset="healthy">Healthy cycle</button>
          <button class="preset" data-preset="stale">Stale data</button>
          <button class="preset" data-preset="budget">Over budget</button>
          <button class="preset" data-preset="confidence">Low confidence</button>
          <button class="preset" data-preset="tilt">Excess tilt</button>
          <button class="preset" data-preset="open-order">Open order</button>
        </div>
        <div class="safety-grid">
          <aside class="scenario-controls">
            <div class="control-heading"><span>SYNTHETIC INPUTS</span><strong>Change one boundary at a time</strong></div>
            <div class="control-grid">
              ${rangeHTML('learning-budget', 'Weekly ceiling', 10, 1, 25, 1, ' USD')}
              ${rangeHTML('learning-confidence', 'Model confidence', .7, .2, .95, .05)}
              ${rangeHTML('learning-vti', 'VTI allocation', 6, 0, 20, .5, ' USD')}
              ${rangeHTML('learning-vxus', 'VXUS allocation', 2.5, 0, 20, .5, ' USD')}
              ${rangeHTML('learning-bnd', 'BND allocation', 1.5, 0, 20, .5, ' USD')}
              ${rangeHTML('learning-buying-power', 'Buying power', 250, 0, 250, 5, ' USD')}
            </div>
            <div class="two-col">
              <label>Snapshot age<select id="learning-snapshot-age"><option value="30">30 sec · fresh</option><option value="600">10 min · stale</option></select></label>
              <label>Quote age<select id="learning-quote-age"><option value="30">30 sec · fresh</option><option value="600">10 min · stale</option></select></label>
            </div>
            <div class="check-row">
              <label><input id="learning-eligible" type="checkbox" checked> Agentic account eligible</label>
              <label><input id="learning-open-order" type="checkbox"> Existing open order</label>
            </div>
            <button id="run-learning" class="run-button learning-run">▶ RUN REAL POLICY GATE</button>
            <p class="sandbox-note"><span>SAFE BY CONSTRUCTION</span> Synthetic account · shadow only · no broker session · no order placement</p>
          </aside>
          <section id="learning-result" class="scenario-result" aria-live="polite">
            <div class="loading-card">Preparing the default shadow cycle…</div>
          </section>
        </div>
      </section>
      <section id="interfaces" class="learning-section interface-section">
        <div class="about-intro">
          <p class="eyebrow">03 · INTERFACES</p>
          <h2>One engine. Three doors.</h2>
          <p>The web app, CLI, and MCP are adapters for different users. They should stay thin so policy and financial math have one source of truth.</p>
        </div>
        <div id="interface-cards" class="interface-cards"></div>
        <div id="protocol-invariants" class="protocol-panel"></div>
      </section>
      <section id="research" class="about-section research-intro">
        <div class="about-intro">
          <p class="eyebrow">04 · RESEARCH LAB</p>
          <h2>Before autonomy, try to falsify the strategy.</h2>
          <p>Backtests answer “what might have happened?” They do not authorize trades. Edgecraft keeps research evidence upstream of the weekly decision and policy gate.</p>
        </div>
        <div class="method-flow" aria-label="Four-stage research process">
          ${aboutStep('01', 'Configure', 'Choose the universe, deposits, costs, and candidates before seeing the outcome.')}
          ${aboutStep('02', 'Walk forward', 'Each close produces an intention. Orders execute no earlier than the next session open.')}
          ${aboutStep('03', 'Stress test', 'Bootstrap ranges, Deflated Sharpe, and CSCV challenge fragile winners.')}
          ${aboutStep('04', 'Inspect', 'Compare every run, trace drawdowns and cash drag, then audit the underlying fills.')}
        </div>
        <div class="causal-strip">
          <span>SESSION t · CLOSE</span><b>Signal observes history</b><i>→</i><span>SESSION t+1 · OPEN</span><b>Order simulates a fill</b><i>→</i><span>OUT-OF-SAMPLE</span><b>Evidence faces stress tests</b>
        </div>
      </section>
      <section id="lab" class="workspace">
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
        <section id="results" class="results" aria-live="polite">${emptyHTML(false)}</section>
      </section>
    </main>
  </div>`

function aboutStep(number, heading, copy) {
  return `<article class="method-step"><span>${number}</span><div><h3>${esc(heading)}</h3><p>${esc(copy)}</p></div></article>`
}

function rangeHTML(id, label, value, min, max, step, suffix = '') {
  return `<label class="range-label"><span>${esc(label)}<output id="${id}-out">${value}${suffix}</output></span><input id="${id}" type="range" value="${value}" min="${min}" max="${max}" step="${step}" data-suffix="${suffix}"></label>`
}

function emptyHTML(loading) {
  return `<div class="empty"><div class="radar"><div></div><div></div><b>${loading ? '⋯' : '⌁'}</b></div><p class="eyebrow">${loading ? 'SIMULATING' : 'EXPERIMENT READY'}</p><h2>${loading ? 'Walking forward through history…' : 'Configure the assumptions. Then try to break the idea.'}</h2><p>${loading ? 'Signals, next-open fills, costs, resampling, and multiple-testing controls are being evaluated.' : 'Start with the synthetic demo for a deterministic run, then switch to adjusted market data.'}</p></div>`
}

const LEARNING_PRESETS = {
  healthy: { budget: 10, confidence: .7, vti: 6, vxus: 2.5, bnd: 1.5, buyingPower: 250, snapshotAge: 30, quoteAge: 30, eligible: true, openOrder: false },
  stale: { budget: 10, confidence: .7, vti: 6, vxus: 2.5, bnd: 1.5, buyingPower: 250, snapshotAge: 600, quoteAge: 600, eligible: true, openOrder: false },
  budget: { budget: 10, confidence: .8, vti: 7, vxus: 3, bnd: 2, buyingPower: 250, snapshotAge: 30, quoteAge: 30, eligible: true, openOrder: false },
  confidence: { budget: 10, confidence: .4, vti: 6, vxus: 2.5, bnd: 1.5, buyingPower: 250, snapshotAge: 30, quoteAge: 30, eligible: true, openOrder: false },
  tilt: { budget: 10, confidence: .8, vti: 10, vxus: 0, bnd: 0, buyingPower: 250, snapshotAge: 30, quoteAge: 30, eligible: true, openOrder: false },
  'open-order': { budget: 10, confidence: .7, vti: 6, vxus: 2.5, bnd: 1.5, buyingPower: 250, snapshotAge: 30, quoteAge: 30, eligible: true, openOrder: true },
}

fetch('/api/learn').then(response => response.json()).then(guide => {
  state.guide = guide
  renderLearningGuide()
}).catch(() => {
  document.getElementById('cycle-map').innerHTML = '<div class="error">Could not load the system guide.</div>'
})

function renderLearningGuide() {
  document.getElementById('cycle-map').classList.remove('loading-card')
  document.getElementById('cycle-map').innerHTML = state.guide.cycle.map((step, index) => `
    <button data-cycle-step="${step.id}" class="${step.id === state.activeCycleStep ? 'active' : ''}" aria-pressed="${step.id === state.activeCycleStep}">
      <span>${String(index + 1).padStart(2, '0')}</span>
      <strong>${esc(step.label)}</strong>
      <small>${esc(step.owner)}</small>
    </button>`).join('')
  document.querySelectorAll('[data-cycle-step]').forEach(button => button.addEventListener('click', () => {
    state.activeCycleStep = button.dataset.cycleStep
    renderLearningGuide()
  }))
  const step = state.guide.cycle.find(item => item.id === state.activeCycleStep)
  document.getElementById('cycle-detail').innerHTML = `
    <div><span>THE QUESTION</span><h3>${esc(step.question)}</h3></div>
    <p>${esc(step.detail)}</p>
    <code>${esc(step.source)}</code>`
  document.getElementById('interface-cards').innerHTML = state.guide.interfaces.map((item, index) => `
    <article><span>0${index + 1}</span><div><p>${esc(item.audience)}</p><h3>${esc(item.name)}</h3><strong>${esc(item.path)}</strong><small>${esc(item.job)}</small></div></article>`).join('')
  document.getElementById('protocol-invariants').innerHTML = `
    <div><p class="eyebrow">NON-NEGOTIABLE INVARIANTS</p><h3>The agent can reason inside the box. It cannot redraw the box.</h3></div>
    <ol>${state.guide.protocol.invariants.slice(0, 4).map(item => `<li>${esc(item)}</li>`).join('')}</ol>`
}

function applyLearningPreset(name) {
  const preset = LEARNING_PRESETS[name]
  const assignments = {
    'learning-budget': preset.budget,
    'learning-confidence': preset.confidence,
    'learning-vti': preset.vti,
    'learning-vxus': preset.vxus,
    'learning-bnd': preset.bnd,
    'learning-buying-power': preset.buyingPower,
  }
  Object.entries(assignments).forEach(([id, value]) => {
    const input = document.getElementById(id)
    input.value = value
    document.getElementById(`${id}-out`).textContent = `${value}${input.dataset.suffix || ''}`
  })
  document.getElementById('learning-snapshot-age').value = preset.snapshotAge
  document.getElementById('learning-quote-age').value = preset.quoteAge
  document.getElementById('learning-eligible').checked = preset.eligible
  document.getElementById('learning-open-order').checked = preset.openOrder
  document.querySelectorAll('[data-preset]').forEach(button => button.classList.toggle('active', button.dataset.preset === name))
  runLearningScenario()
}

document.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click', () => applyLearningPreset(button.dataset.preset)))
document.getElementById('run-learning').addEventListener('click', runLearningScenario)

async function runLearningScenario() {
  const button = document.getElementById('run-learning')
  button.disabled = true
  button.textContent = '◌ RUNNING POLICY GATE'
  document.getElementById('learning-result').innerHTML = '<div class="loading-card">Evaluating the typed mandate, decision, snapshot, quotes, and policy…</div>'
  const value = id => Number(document.getElementById(id).value)
  const body = {
    weekly_budget: value('learning-budget'),
    confidence: value('learning-confidence'),
    vti_notional: value('learning-vti'),
    vxus_notional: value('learning-vxus'),
    bnd_notional: value('learning-bnd'),
    buying_power: value('learning-buying-power'),
    snapshot_age_seconds: value('learning-snapshot-age'),
    quote_age_seconds: value('learning-quote-age'),
    account_eligible: document.getElementById('learning-eligible').checked,
    has_open_order: document.getElementById('learning-open-order').checked,
  }
  try {
    const response = await fetch('/api/learn/scenarios', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.detail?.[0]?.msg || payload.detail || 'Learning scenario failed')
    state.learningResult = payload
    renderLearningResult()
  } catch (error) {
    document.getElementById('learning-result').innerHTML = `<div class="error">⚠ ${esc(error.message)}</div>`
  } finally {
    button.disabled = false
    button.textContent = '▶ RUN REAL POLICY GATE'
  }
}

function renderLearningResult() {
  const result = state.learningResult
  const detail = result.approved
    ? `<div class="order-preview"><span>SHADOW PROPOSAL</span>${result.orders.map(order => `<div><strong>${esc(order.symbol)}</strong><b>${preciseMoney.format(order.notional)}</b><small>@ synthetic ${preciseMoney.format(order.expected_price)}</small></div>`).join('')}</div>`
    : `<div class="violation-list"><span>EXACT BLOCKERS</span>${result.risk.violations.map(item => `<p>× ${esc(item)}</p>`).join('')}</div>`
  document.getElementById('learning-result').innerHTML = `
    <div class="result-summary ${result.approved ? 'approved' : 'blocked'}">
      <span>${result.approved ? '✓ SHADOW-APPROVED' : '× BLOCKED BY CODE'}</span>
      <h3>${esc(result.headline)}</h3>
      <p>${esc(result.summary)}</p>
    </div>
    <div class="learning-trace">${result.trace.map((step, index) => `
      <article class="${step.status}">
        <span>${String(index + 1).padStart(2, '0')}</span>
        <div><small>${esc(step.status.replaceAll('_', ' '))}</small><strong>${esc(step.title)}</strong><p>${esc(step.detail)}</p></div>
      </article>`).join('')}</div>
    ${detail}
    <div class="result-foot"><span>HANDOFF · ${esc(result.handoff_status.replaceAll('_', ' '))}</span><code>${esc(result.proposal_id)}</code></div>`
}

document.querySelectorAll('input[type="range"]').forEach(input => input.addEventListener('input', event => {
  document.getElementById(`${event.target.id}-out`).textContent = `${event.target.value}${event.target.dataset.suffix || ''}`
}))

runLearningScenario()

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
      <button class="strategy-toggle" data-toggle="${schema.name}" aria-pressed="${Boolean(chosen)}"><span class="check">${chosen ? '✓' : ''}</span><span><strong>${esc(schema.label)}</strong><small>${esc(schema.description)}</small></span><span>⌄</span></button>
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
    state.visible = new Set(payload.results.map(item => item.strategy))
    state.chartMode = 'equity'
    state.chartRange = 'all'
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
  const pbo = result.validation.probability_backtest_overfitting
  document.getElementById('results').innerHTML = `
    <div class="run-meta"><span><span class="pulse"></span> COMPLETE</span><span>${result.meta.sessions.toLocaleString()} SESSIONS</span><span>${result.meta.start} → ${result.meta.end}</span><span>${esc(result.meta.execution.toUpperCase())}</span></div>
    <div class="metric-grid">
      ${metricHTML('Leader by Sharpe', title(best.strategy), `Sharpe ${dec(best.metrics.sharpe)}`)}
      ${metricHTML('Overfit probability', pct(pbo), `CSCV · ${result.validation.cscv_slices} slices`, (pbo ?? 0) > .5)}
      ${metricHTML('Strategies tested', result.meta.strategies_tested, `${result.validation.bootstrap_samples} bootstrap paths`)}
      ${metricHTML('Universe', result.meta.symbols.join(' · '), `${result.meta.sessions.toLocaleString()} aligned sessions`)}
    </div>
    <div class="panel chart-panel">
      <div class="panel-head chart-head"><div><p class="eyebrow">RUN EXPLORER</p><h2 id="chart-title">${CHART_MODES[state.chartMode].label}</h2></div><span id="chart-unit">${CHART_MODES[state.chartMode].unit}</span></div>
      <div class="chart-toolbar">
        <div class="segmented" aria-label="Chart metric">${Object.entries(CHART_MODES).map(([key, mode]) => `<button data-chart-mode="${key}" class="${state.chartMode === key ? 'active' : ''}" aria-pressed="${state.chartMode === key}">${mode.label}</button>`).join('')}</div>
        <div class="segmented compact" aria-label="Chart date range">${[['all', 'All'], ['5', '5Y'], ['3', '3Y'], ['1', '1Y']].map(([key, label]) => `<button data-chart-range="${key}" class="${state.chartRange === key ? 'active' : ''}" aria-pressed="${state.chartRange === key}">${label}</button>`).join('')}</div>
      </div>
      <div class="chart-stage"><div id="equity-chart" class="native-chart"></div><div id="chart-tooltip" class="chart-tooltip" role="status"></div></div>
      <div id="chart-legend" class="chart-legend"></div>
    </div>
    <div id="active-inspector"></div>
    <div class="panel"><div class="panel-head"><div><p class="eyebrow">ROBUSTNESS TABLE</p><h2>Risk-adjusted comparison</h2></div><span>SELECT A RUN TO INSPECT</span></div>${tableHTML(result.results)}</div>
    <div id="trade-log"></div>`
  bindChartControls()
  renderChart()
  renderActiveInspector()
  bindResultRows()
  renderTradeLog()
}

function metricHTML(label, value, note, warn = false) {
  return `<div class="metric ${warn ? 'warn' : ''}"><small>${esc(label)}</small><strong>${esc(value)}</strong><span>${esc(note)}</span></div>`
}

function tableHTML(results) {
  return `<div class="table-scroll"><table><thead><tr><th>Strategy</th><th>End value</th><th>Gain vs deposits</th><th>Ann. return</th><th>Sharpe</th><th>95% Sharpe CI</th><th>Max DD</th><th>DSR prob.</th><th>Cash drag</th><th>Fills</th></tr></thead><tbody>${results.map((item, index) => `<tr data-result="${item.strategy}" class="${state.active === item.strategy ? 'active-row' : ''}" tabindex="0"><td><span class="row-dot" style="background:${COLORS[index % COLORS.length]}"></span>${esc(title(item.strategy))}</td><td>${money.format(item.metrics.ending_equity || 0)}</td><td class="${(item.metrics.net_gain ?? 0) >= 0 ? 'positive' : 'negative'}">${item.metrics.net_gain >= 0 ? '+' : ''}${money.format(item.metrics.net_gain || 0)}</td><td>${pct(item.metrics.annual_return)}</td><td>${dec(item.metrics.sharpe)}</td><td>${dec(item.metrics.sharpe_low)} – ${dec(item.metrics.sharpe_high)}</td><td>${pct(item.metrics.max_drawdown)}</td><td>${pct(item.metrics.deflated_sharpe_probability)}</td><td>${pct(item.metrics.cash_drag)}</td><td>${item.metrics.fills}</td></tr>`).join('')}</tbody></table></div>`
}

function bindResultRows() {
  document.querySelectorAll('[data-result]').forEach(row => {
    const select = () => selectResult(row.dataset.result)
    row.addEventListener('click', select)
    row.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        select()
      }
    })
  })
}

function selectResult(strategy) {
  state.active = strategy
  state.visible.add(strategy)
  document.querySelectorAll('[data-result]').forEach(item => item.classList.toggle('active-row', item.dataset.result === state.active))
  renderChart()
  renderActiveInspector()
  renderTradeLog()
}

function bindChartControls() {
  document.querySelectorAll('[data-chart-mode]').forEach(button => button.addEventListener('click', () => {
    state.chartMode = button.dataset.chartMode
    document.querySelectorAll('[data-chart-mode]').forEach(item => {
      const active = item.dataset.chartMode === state.chartMode
      item.classList.toggle('active', active)
      item.setAttribute('aria-pressed', active)
    })
    document.getElementById('chart-title').textContent = CHART_MODES[state.chartMode].label
    document.getElementById('chart-unit').textContent = CHART_MODES[state.chartMode].unit
    renderChart()
  }))
  document.querySelectorAll('[data-chart-range]').forEach(button => button.addEventListener('click', () => {
    state.chartRange = button.dataset.chartRange
    document.querySelectorAll('[data-chart-range]').forEach(item => {
      const active = item.dataset.chartRange === state.chartRange
      item.classList.toggle('active', active)
      item.setAttribute('aria-pressed', active)
    })
    renderChart()
  }))
}

function filteredSeries(series) {
  if (state.chartRange === 'all' || series.length < 2) return series
  const end = new Date(`${series.at(-1).date}T12:00:00`)
  const cutoff = new Date(end)
  cutoff.setFullYear(cutoff.getFullYear() - Number(state.chartRange))
  const filtered = series.filter(point => new Date(`${point.date}T12:00:00`) >= cutoff)
  return filtered.length > 1 ? filtered : series.slice(-2)
}

function renderChart() {
  const results = state.result.results
  const visibleResults = results.filter(item => state.visible.has(item.strategy))
  const mode = CHART_MODES[state.chartMode]
  const width = 1120
  const height = 410
  const pad = { left: 76, right: 24, top: 26, bottom: 46 }
  const plotted = new Map(visibleResults.map(item => [item.strategy, filteredSeries(item.series)]))
  let values = visibleResults.flatMap(item => plotted.get(item.strategy).map(mode.value)).filter(Number.isFinite)
  if (state.chartMode === 'equity' && visibleResults.length) values = values.concat(plotted.get(visibleResults[0].strategy).map(point => point.net_invested))
  if (state.chartMode === 'gain') values.push(0)
  let min = Math.min(...values)
  let max = Math.max(...values)
  if (!Number.isFinite(min) || !Number.isFinite(max)) { min = 0; max = 1 }
  const spread = Math.max(max - min, Math.abs(max) * .02, 1)
  if (state.chartMode === 'drawdown') max = 0
  else if (state.chartMode === 'exposure') { min = Math.min(0, min); max = Math.max(1, max) }
  else { min -= spread * .08; max += spread * .08 }
  const x = (index, length) => pad.left + index / Math.max(1, length - 1) * (width - pad.left - pad.right)
  const y = value => pad.top + (max - value) / (max - min || 1) * (height - pad.top - pad.bottom)
  const pathFor = (series, accessor = mode.value) => series.map((point, index) => `${index ? 'L' : 'M'}${x(index, series.length).toFixed(1)},${y(accessor(point)).toFixed(1)}`).join(' ')
  const grid = Array.from({ length: 6 }, (_, index) => {
    const value = max - (max - min) * index / 5
    const yy = pad.top + index * (height - pad.top - pad.bottom) / 5
    return `<line x1="${pad.left}" y1="${yy}" x2="${width - pad.right}" y2="${yy}"/><text x="${pad.left - 12}" y="${yy + 4}" text-anchor="end">${esc(mode.axis(value))}</text>`
  }).join('')
  const reference = plotted.get(visibleResults[0]?.strategy) || []
  const dateTicks = Array.from({ length: Math.min(5, reference.length) }, (_, index) => Math.round(index * (reference.length - 1) / Math.max(1, Math.min(5, reference.length) - 1)))
    .map(index => `<text x="${x(index, reference.length)}" y="${height - 12}" text-anchor="middle">${new Intl.DateTimeFormat('en-US', { month: 'short', year: '2-digit' }).format(new Date(`${reference[index].date}T12:00:00`))}</text>`).join('')
  const baseline = state.chartMode === 'equity' && visibleResults.length
    ? `<path class="invested-line" d="${pathFor(plotted.get(visibleResults[0].strategy), point => point.net_invested)}"/>`
    : state.chartMode === 'gain' ? `<line class="zero-line" x1="${pad.left}" y1="${y(0)}" x2="${width - pad.right}" y2="${y(0)}"/>` : ''
  const activeResult = visibleResults.find(item => item.strategy === state.active)
  const activeSeries = activeResult ? plotted.get(activeResult.strategy) : null
  const activeArea = activeSeries ? `<path class="active-area" d="${pathFor(activeSeries)} L${x(activeSeries.length - 1, activeSeries.length)},${height - pad.bottom} L${x(0, activeSeries.length)},${height - pad.bottom} Z" fill="url(#active-fill)"/>` : ''
  const paths = visibleResults.map(item => {
    const index = results.findIndex(result => result.strategy === item.strategy)
    const series = plotted.get(item.strategy)
    const active = item.strategy === state.active
    return `<path class="strategy-line ${active ? 'active' : ''}" d="${pathFor(series)}" stroke="${COLORS[index % COLORS.length]}"/><circle class="hover-point" data-hover-point="${esc(item.strategy)}" r="5" fill="${COLORS[index % COLORS.length]}"/>`
  }).join('')
  document.getElementById('equity-chart').innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" tabindex="0" aria-label="Interactive ${esc(mode.label.toLowerCase())} chart for ${visibleResults.length} strategy runs"><defs><linearGradient id="active-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#b9ff66" stop-opacity=".16"/><stop offset="1" stop-color="#b9ff66" stop-opacity="0"/></linearGradient></defs><g class="grid">${grid}<line class="axis-base" x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}"/></g><g class="date-axis">${dateTicks}</g>${baseline}<g class="series">${activeArea}${paths}</g><line id="chart-crosshair" class="chart-crosshair" y1="${pad.top}" y2="${height - pad.bottom}"/><rect class="chart-hitbox" x="${pad.left}" y="${pad.top}" width="${width - pad.left - pad.right}" height="${height - pad.top - pad.bottom}"/></svg>`
  renderChartLegend(results)
  bindChartInspection({ plotted, visibleResults, mode, x, y, pad, width, height })
}

function renderChartLegend(results) {
  document.getElementById('chart-legend').innerHTML = results.map((item, index) => {
    const visible = state.visible.has(item.strategy)
    const active = state.active === item.strategy
    return `<div class="legend-item ${visible ? '' : 'muted'} ${active ? 'active' : ''}"><button class="legend-focus" data-focus-series="${item.strategy}" title="Inspect ${esc(title(item.strategy))}"><span class="legend-dot" style="--series:${COLORS[index % COLORS.length]}"></span><span><strong>${esc(title(item.strategy))}</strong><small>${money.format(item.metrics.ending_equity || 0)} · Sharpe ${dec(item.metrics.sharpe)}</small></span></button><button class="legend-toggle" data-toggle-series="${item.strategy}" aria-label="${visible ? 'Hide' : 'Show'} ${esc(title(item.strategy))}" aria-pressed="${visible}">${visible ? '●' : '○'}</button></div>`
  }).join('')
  document.querySelectorAll('[data-focus-series]').forEach(button => button.addEventListener('click', () => selectResult(button.dataset.focusSeries)))
  document.querySelectorAll('[data-toggle-series]').forEach(button => button.addEventListener('click', () => {
    const strategy = button.dataset.toggleSeries
    if (state.visible.has(strategy)) {
      if (state.visible.size === 1) return
      state.visible.delete(strategy)
      if (state.active === strategy) state.active = [...state.visible][0]
    } else state.visible.add(strategy)
    renderChart()
    renderActiveInspector()
    renderTradeLog()
    document.querySelectorAll('[data-result]').forEach(item => item.classList.toggle('active-row', item.dataset.result === state.active))
  }))
}

function bindChartInspection(context) {
  const svg = document.querySelector('#equity-chart svg')
  const tooltip = document.getElementById('chart-tooltip')
  const crosshair = document.getElementById('chart-crosshair')
  const pointElements = new Map([...document.querySelectorAll('[data-hover-point]')].map(element => [element.dataset.hoverPoint, element]))
  const reference = context.plotted.get(context.visibleResults[0]?.strategy) || []
  if (!reference.length) return

  const showIndex = (index, left) => {
    state.hoverIndex = Math.max(0, Math.min(reference.length - 1, index))
    const xx = context.x(state.hoverIndex, reference.length)
    crosshair.setAttribute('x1', xx)
    crosshair.setAttribute('x2', xx)
    crosshair.classList.add('visible')
    const rows = context.visibleResults.map(item => {
      const series = context.plotted.get(item.strategy)
      const point = series[Math.min(state.hoverIndex, series.length - 1)]
      const node = pointElements.get(item.strategy)
      node.setAttribute('cx', context.x(Math.min(state.hoverIndex, series.length - 1), series.length))
      node.setAttribute('cy', context.y(context.mode.value(point)))
      node.classList.add('visible')
      const color = COLORS[state.result.results.findIndex(result => result.strategy === item.strategy) % COLORS.length]
      return `<div><span><i style="--series:${color}"></i>${esc(title(item.strategy))}</span><strong>${esc(context.mode.format(context.mode.value(point)))}</strong></div>`
    }).join('')
    tooltip.innerHTML = `<time>${dateLabel(reference[state.hoverIndex].date)}</time>${rows}`
    tooltip.classList.add('visible')
    const chart = document.querySelector('.chart-stage').getBoundingClientRect()
    const desired = left ?? (xx / context.width * chart.width)
    const tooltipWidth = tooltip.offsetWidth || 230
    tooltip.style.left = `${Math.max(10, Math.min(chart.width - tooltipWidth - 10, desired + 14))}px`
    tooltip.style.top = '18px'
  }
  const hide = () => {
    crosshair.classList.remove('visible')
    tooltip.classList.remove('visible')
    pointElements.forEach(node => node.classList.remove('visible'))
  }
  svg.addEventListener('pointermove', event => {
    const bounds = svg.getBoundingClientRect()
    const viewX = (event.clientX - bounds.left) / bounds.width * context.width
    const ratio = (viewX - context.pad.left) / (context.width - context.pad.left - context.pad.right)
    showIndex(Math.round(Math.max(0, Math.min(1, ratio)) * (reference.length - 1)), event.clientX - bounds.left)
  })
  svg.addEventListener('pointerleave', hide)
  svg.addEventListener('focus', () => showIndex(state.hoverIndex ?? reference.length - 1))
  svg.addEventListener('blur', hide)
  svg.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const current = state.hoverIndex ?? reference.length - 1
    if (event.key === 'Home') showIndex(0)
    else if (event.key === 'End') showIndex(reference.length - 1)
    else showIndex(current + (event.key === 'ArrowRight' ? 1 : -1))
  })
}

function renderActiveInspector() {
  const result = state.result.results.find(item => item.strategy === state.active)
  if (!result) return
  const metrics = result.metrics
  const params = Object.entries(result.params || {})
  document.getElementById('active-inspector').innerHTML = `<div class="panel inspector"><div class="panel-head"><div><p class="eyebrow">SELECTED RUN</p><h2>${esc(title(result.strategy))}</h2></div><span>${params.length ? params.map(([key, value]) => `${title(key)} ${value}`).join(' · ') : 'DEFAULT PARAMETERS'}</span></div><div class="inspector-grid">${inspectorStat('Ending value', money.format(metrics.ending_equity || 0), signedPct(metrics.return_on_contributions))}${inspectorStat('Net gain', `${(metrics.net_gain ?? 0) >= 0 ? '+' : ''}${money.format(metrics.net_gain || 0)}`, 'after contributed capital')}${inspectorStat('Max drawdown', pct(metrics.max_drawdown), `Calmar ${dec(metrics.calmar)}`)}${inspectorStat('Risk-adjusted', `Sharpe ${dec(metrics.sharpe)}`, `Sortino ${dec(metrics.sortino)}`)}${inspectorStat('DSR probability', pct(metrics.deflated_sharpe_probability), 'multiple-test adjusted')}${inspectorStat('Capital use', pct(metrics.average_exposure), `${pct(metrics.cash_drag)} cash drag`)}</div></div>`
}

function inspectorStat(label, value, note) {
  return `<div><small>${esc(label)}</small><strong>${esc(value)}</strong><span>${esc(note)}</span></div>`
}

function renderTradeLog() {
  const result = state.result.results.find(item => item.strategy === state.active)
  const fills = result.fills.slice(-20).reverse()
  document.getElementById('trade-log').innerHTML = `<div class="panel"><div class="panel-head"><div><p class="eyebrow">AUDIT TRAIL</p><h2>${esc(title(result.strategy))} · recent fills</h2></div><span>LATEST ${fills.length} OF ${result.fills.length} RETURNED</span></div>${fills.length ? `<div class="table-scroll"><table><thead><tr><th>Date</th><th>Side</th><th>Symbol</th><th>Quantity</th><th>Price</th><th>Notional</th><th>Costs</th><th>Reason</th></tr></thead><tbody>${fills.map(fill => `<tr><td>${fill.date}</td><td><span class="side ${fill.side}">${fill.side}</span></td><td>${esc(fill.symbol)}</td><td>${fill.quantity.toFixed(4)}</td><td>${money.format(fill.price)}</td><td>${money.format(fill.notional)}</td><td>${money.format(fill.costs)}</td><td>${esc(title(fill.reason))}</td></tr>`).join('')}</tbody></table></div>` : '<div class="no-trades">No fills generated for this configuration.</div>'}</div>`
}
