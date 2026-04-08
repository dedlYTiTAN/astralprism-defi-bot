/**
 * AstralPrism DeFi Bot — Dashboard Client
 * WebSocket-driven real-time UI: prices, AI signals, trades, portfolio
 */

// ─── State ──────────────────────────────────────────────────────────────────
let state = {
  prices:    {},
  history:   { SOL: [], JUP: [], BONK: [], WIF: [] },
  portfolio: { sol: 2, usdc: 100, pnl: 0, pnlPct: 0, totalValueUSD: 0 },
  trades:    [],
  lastSignal: null,
  paused:    false,
  connected: false,
  tick:      0,
};

let activeToken = 'SOL';
let priceChart  = null;
let pnlChart    = null;
let pnlHistory  = [];
let ws          = null;

const TOKEN_COLORS = {
  SOL:  '#9945FF',
  JUP:  '#C7F284',
  BONK: '#F7931A',
  WIF:  '#FF6B6B',
  USDC: '#2775CA',
};

// ─── WebSocket ───────────────────────────────────────────────────────────────
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    setStatus('live', 'Connected');
    state.connected = true;
  };

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    handleMessage(msg);
  };

  ws.onclose = () => {
    setStatus('connecting', 'Reconnecting...');
    state.connected = false;
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => ws.close();
}

function handleMessage(msg) {
  switch (msg.type) {
    case 'connected':
    case 'price_update':
      mergeState(msg);
      renderPrices();
      renderPortfolio();
      updateChart();
      break;

    case 'analysis_start':
      showThinking(true);
      break;

    case 'analysis_complete':
      showThinking(false);
      mergeState(msg);
      renderSignal(msg.signal);
      renderPortfolio();
      if (msg.trade && msg.trade.id) {
        state.trades.unshift(msg.trade);
        renderTrades();
        showTradeToast(msg.trade);
      }
      pnlHistory.push({
        t: Date.now(),
        v: state.portfolio.pnl || 0,
      });
      updatePnlChart();
      break;

    case 'ping':
      break;
  }
}

function mergeState(msg) {
  if (msg.prices)    state.prices    = { ...state.prices, ...msg.prices };
  if (msg.history)   state.history   = { ...state.history, ...msg.history };
  if (msg.portfolio) state.portfolio = msg.portfolio;
  if (msg.trades)    state.trades    = msg.trades;
  if (msg.lastSignal) state.lastSignal = msg.lastSignal;
  if (msg.wallet)    setWalletInfo(msg);
  if (msg.isDemo !== undefined) setModelMode(msg.isDemo);
  if (msg.isLive !== undefined) setLiveMode(msg.isLive, msg.portfolio || state.portfolio);
  if (msg.tick)      state.tick = msg.tick;
}

// ─── Price Rendering ─────────────────────────────────────────────────────────
function renderPrices() {
  const container = document.getElementById('tokenCards');
  const tokens    = ['SOL', 'JUP', 'BONK', 'WIF'];

  const cards = tokens.map(sym => {
    const price   = state.prices[sym] || 0;
    const hist    = state.history[sym] || [];
    const prev    = hist.length >= 2 ? hist[hist.length - 2] : price;
    const change  = prev ? ((price - prev) / prev * 100) : 0;
    const isUp    = change >= 0;
    const color   = TOKEN_COLORS[sym];

    return `
      <div class="token-card ${sym === activeToken ? 'active' : ''}"
           onclick="switchChart('${sym}')"
           style="border-left: 3px solid ${color}20;">
        <div class="tc-row">
          <div>
            <div class="tc-sym" style="color:${color}">${sym}</div>
          </div>
          <div class="tc-price">$${formatPrice(price, sym)}</div>
        </div>
        <div class="tc-row" style="margin-top:4px">
          <span class="tc-name">${getTokenName(sym)}</span>
          <span class="tc-change ${isUp ? 'up' : 'down'}">
            ${isUp ? '▲' : '▼'} ${Math.abs(change).toFixed(3)}%
          </span>
        </div>
      </div>`;
  });

  container.innerHTML = cards.join('');
}

function formatPrice(p, sym) {
  if (!p || p === 0) return '—';
  if (sym === 'BONK')  return p.toFixed(8);
  if (p < 0.001)       return p.toExponential(4);
  if (p < 1)           return p.toFixed(5);
  return p.toFixed(3);
}

function getTokenName(sym) {
  const names = { SOL: 'Solana', JUP: 'Jupiter', BONK: 'Bonk', WIF: 'dogwifhat' };
  return names[sym] || sym;
}

// ─── Chart ───────────────────────────────────────────────────────────────────
function initChart() {
  const ctx = document.getElementById('priceChart').getContext('2d');
  priceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: 'Price',
        data: [],
        borderColor: TOKEN_COLORS.SOL,
        backgroundColor: TOKEN_COLORS.SOL + '15',
        borderWidth: 2,
        tension: 0.35,
        fill: true,
        pointRadius: 0,
        pointHoverRadius: 4,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#0c1120',
          borderColor: '#6378ff40',
          borderWidth: 1,
          callbacks: {
            label: ctx => `$${ctx.raw.toFixed(6)}`,
          }
        }
      },
      scales: {
        x: { display: false },
        y: {
          grid: { color: 'rgba(99,120,255,0.06)' },
          border: { color: 'transparent' },
          ticks: { color: '#8899aa', font: { family: 'JetBrains Mono', size: 11 },
            callback: v => '$' + formatPriceRaw(v) },
        }
      }
    }
  });
}

function formatPriceRaw(v) {
  if (v < 0.0001) return v.toExponential(2);
  if (v < 1) return v.toFixed(5);
  return v.toFixed(3);
}

function updateChart() {
  if (!priceChart) return;
  const hist  = (state.history[activeToken] || []).slice(-60);
  const color = TOKEN_COLORS[activeToken];
  const price = state.prices[activeToken] || 0;

  priceChart.data.labels   = hist.map((_, i) => i);
  priceChart.data.datasets[0].data        = hist;
  priceChart.data.datasets[0].borderColor = color;
  priceChart.data.datasets[0].backgroundColor = color + '15';
  priceChart.data.datasets[0].label = activeToken;
  priceChart.update('none');

  // Update meta
  const meta = document.getElementById('chartMeta');
  const change = hist.length >= 2 ? ((hist[hist.length-1] - hist[0]) / hist[0] * 100) : 0;
  meta.innerHTML = `<span style="color:${price}">${activeToken}</span>
    $${formatPrice(price, activeToken)}
    <span style="color:${change >= 0 ? 'var(--green)' : 'var(--red)'}">
      ${change >= 0 ? '+' : ''}${change.toFixed(3)}%
    </span>`;
}

function switchChart(sym) {
  activeToken = sym;
  document.querySelectorAll('.chart-tab').forEach(t => {
    t.classList.toggle('active', t.textContent === sym);
  });
  updateChart();
  renderPrices(); // refresh active state on cards
}

// ─── Signal ───────────────────────────────────────────────────────────────────
function renderSignal(signal) {
  if (!signal) return;

  const bar       = document.getElementById('signalBar');
  const icon      = document.getElementById('signalIcon');
  const label     = document.getElementById('signalLabel');
  const token     = document.getElementById('signalToken');
  const reason    = document.getElementById('signalReason');
  const conf      = document.getElementById('confVal');
  const risk      = document.getElementById('riskVal');
  const cond      = document.getElementById('condVal');

  const side = signal.signal;
  bar.className = 'signal-bar ' + (side === 'BUY' ? 'buy' : side === 'SELL' ? 'sell' : '');

  icon.textContent = side === 'BUY' ? '▲' : side === 'SELL' ? '▼' : '━';
  icon.style.color = side === 'BUY' ? 'var(--green)' : side === 'SELL' ? 'var(--red)' : 'var(--text2)';

  label.innerHTML = `<span class="signal-label-text" style="color:${side === 'BUY' ? 'var(--green)' : side === 'SELL' ? 'var(--red)' : 'var(--text2)'}">${side}</span>`;
  token.textContent = signal.token + (signal.isDemo ? ' · DEMO' : ' · NEMOTRON');
  reason.textContent = signal.reasoning || '—';

  conf.textContent  = ((signal.confidence || 0) * 100).toFixed(1) + '%';
  conf.style.color  = signal.confidence >= 0.7 ? 'var(--green)' : signal.confidence >= 0.5 ? 'var(--yellow)' : 'var(--red)';

  risk.textContent  = signal.riskLevel || '—';
  risk.style.color  = signal.riskLevel === 'HIGH' ? 'var(--red)' : signal.riskLevel === 'LOW' ? 'var(--green)' : 'var(--yellow)';

  cond.textContent  = signal.marketCondition || '—';
  cond.style.color  = signal.marketCondition === 'BULLISH' ? 'var(--green)' :
                      signal.marketCondition === 'BEARISH' ? 'var(--red)' : 'var(--text2)';

  state.lastSignal = signal;
}

// ─── Portfolio ────────────────────────────────────────────────────────────────
function renderPortfolio() {
  const p = state.portfolio;
  if (!p) return;

  document.getElementById('portTotal').textContent = '$' + (p.totalValueUSD || 0).toFixed(2);
  document.getElementById('portSol').textContent   = (p.sol || 0).toFixed(4) + ' SOL';
  document.getElementById('portUsdc').textContent  = '$' + (p.usdc || 0).toFixed(2);

  const pnlEl = document.getElementById('portPnl');
  const pnl   = p.pnl || 0;
  const pct   = p.pnlPct || 0;
  pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)} (${pct.toFixed(3)}%)`;
  pnlEl.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
}

// ─── P&L Chart ────────────────────────────────────────────────────────────────
function initPnlChart() {
  const ctx = document.getElementById('pnlChart').getContext('2d');
  pnlChart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [{
      data: [], borderColor: '#22c98a', backgroundColor: '#22c98a18',
      borderWidth: 2, fill: true, tension: 0.4, pointRadius: 0,
    }]},
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 200 },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: {
        x: { display: false },
        y: {
          grid: { color: 'rgba(99,120,255,0.06)' },
          border: { color: 'transparent' },
          ticks: { color: '#8899aa', font: { size: 10 }, callback: v => `$${v.toFixed(2)}` }
        }
      }
    }
  });
}

function updatePnlChart() {
  if (!pnlChart || pnlHistory.length === 0) return;
  const last50 = pnlHistory.slice(-50);
  pnlChart.data.labels   = last50.map((_, i) => i);
  pnlChart.data.datasets[0].data = last50.map(d => d.v);
  const lastV = last50[last50.length - 1]?.v || 0;
  const col   = lastV >= 0 ? '#22c98a' : '#ff4f6b';
  pnlChart.data.datasets[0].borderColor     = col;
  pnlChart.data.datasets[0].backgroundColor = col + '18';
  pnlChart.update('none');
}

// ─── Trades Table ─────────────────────────────────────────────────────────────
function renderTrades() {
  const tbody = document.getElementById('tradeBody');
  const count = document.getElementById('tradeCount');
  count.textContent = `${state.trades.length} trade${state.trades.length !== 1 ? 's' : ''}`;

  if (!state.trades.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="empty-row">No trades yet — bot is analysing markets...</td></tr>';
    return;
  }

  tbody.innerHTML = state.trades.slice(0, 50).map(t => {
    const ts = t.timestamp ? new Date(t.timestamp * 1000).toLocaleTimeString() : '—';
    return `<tr>
      <td>#${t.id}</td>
      <td>${ts}</td>
      <td class="side-${t.side.toLowerCase()}">${t.side === 'BUY' ? '▲ BUY' : '▼ SELL'}</td>
      <td style="color:${TOKEN_COLORS[t.token] || '#fff'}">${t.token}</td>
      <td>${(t.size || 0).toFixed(5)}</td>
      <td>$${(t.price || 0).toFixed(5)}</td>
      <td>$${(t.cost || 0).toFixed(3)}</td>
      <td style="color:${(t.confidence||0) >= 0.7 ? 'var(--green)' : 'var(--yellow)'}">
        ${((t.confidence||0)*100).toFixed(1)}%
      </td>
      <td>${t.condition || '—'}</td>
      <td style="font-size:10px;color:var(--text2)">${t.route || 'Jupiter'}</td>
      <td style="color:var(--green)">✓ ${t.status || 'FILLED'}</td>
    </tr>`;
  }).join('');
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function setStatus(type, label) {
  const dot = document.getElementById('statusDot');
  const lbl = document.getElementById('statusLabel');
  dot.className = `dot dot--${type}`;
  lbl.textContent = label;
}

function setWalletInfo(msg) {
  if (msg.wallet) {
    const addr = msg.wallet;
    document.getElementById('walletAddr').textContent =
      addr.slice(0, 8) + '...' + addr.slice(-8);
    document.getElementById('devnetSol').textContent =
      (msg.devnetSol || 0).toFixed(4) + ' SOL';
    const link = document.getElementById('explorerLink');
    link.href = msg.explorerUrl || `https://explorer.solana.com/address/${addr}?cluster=devnet`;
  }
}

function setModelMode(isDemo) {
  const tag = document.getElementById('modeLabel');
  tag.textContent = isDemo ? 'DEMO' : 'LIVE AI';
  tag.style.color = isDemo ? 'var(--yellow)' : 'var(--green)';
}

function setLiveMode(isLive, portfolio) {
  const banner = document.getElementById('liveBanner');
  if (!isLive) { banner.classList.add('hidden'); return; }
  banner.classList.remove('hidden');

  const cap       = portfolio?.lossCapUSD || 10;
  const remaining = portfolio?.lossRemaining ?? cap;
  const pct       = Math.max(0, Math.min(100, (remaining / cap) * 100));

  const budgetEl = document.getElementById('lossBudget');
  const barEl    = document.getElementById('lossBar');

  budgetEl.textContent = `$${remaining.toFixed(2)}`;
  budgetEl.style.color = remaining > 5 ? 'var(--green)' : remaining > 2 ? 'var(--yellow)' : 'var(--red)';
  barEl.style.width    = pct + '%';
  barEl.style.background = remaining > 5 ? 'var(--green)' : remaining > 2 ? 'var(--yellow)' : 'var(--red)';

  // Halt state
  if (portfolio?.halted) {
    banner.classList.add('halted');
    banner.querySelector('.live-banner-icon').textContent = '🛑 BOT HALTED';
    toast(`Bot halted: ${portfolio.haltReason}`, 'sell');
  }
}

async function haltBot() {
  if (!confirm('Halt the bot immediately? All pending trades will stop.')) return;
  try {
    await fetch('/api/bot/pause', { method: 'POST' });
    toast('🛑 Bot halted — no further trades will execute', 'sell');
    document.getElementById('liveBanner').classList.add('halted');
    document.querySelector('.live-banner-icon').textContent = '🛑 BOT HALTED';
  } catch(e) { toast('Halt request failed', 'info'); }
}

function showThinking(show) {
  const overlay = document.getElementById('thinkingOverlay');
  overlay.classList.toggle('hidden', !show);
}

function showTradeToast(trade) {
  const el = document.createElement('div');
  el.className = `toast ${trade.side.toLowerCase()}`;
  el.innerHTML = `
    <strong>${trade.side === 'BUY' ? '▲ BUY' : '▼ SELL'} ${trade.token}</strong>
    <div style="margin-top:4px;color:#8899aa;font-size:12px">
      ${(trade.size||0).toFixed(5)} @ $${(trade.price||0).toFixed(5)} · ${((trade.confidence||0)*100).toFixed(1)}% conf
    </div>`;
  document.getElementById('toasts').prepend(el);
  setTimeout(() => el.remove(), 4000);
}

function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toasts').prepend(el);
  setTimeout(() => el.remove(), 3500);
}

// ─── API Actions ──────────────────────────────────────────────────────────────
async function togglePause() {
  const btn = document.getElementById('btnPause');
  try {
    const r = await fetch('/api/bot/pause', { method: 'POST' });
    const d = await r.json();
    state.paused = d.status === 'paused';
    btn.textContent = state.paused ? '▶ Resume Bot' : '⏸ Pause Bot';
    toast(state.paused ? 'Bot paused — prices still updating' : 'Bot resumed', 'info');
  } catch (e) { toast('API error', 'info'); }
}

async function requestAirdrop() {
  toast('Requesting 1 SOL airdrop from devnet (retrying up to 3x)...', 'info');
  try {
    const r = await fetch('/api/airdrop', { method: 'POST' });
    const d = await r.json();
    if (d.success) {
      document.getElementById('devnetSol').textContent = d.balance.toFixed(4) + ' SOL';
      toast(`Airdrop received! ${d.amount} SOL — Balance: ${d.balance.toFixed(4)} SOL`, 'buy');
    } else if (d.faucetUrl) {
      // Show faucet link as clickable toast
      const el = document.createElement('div');
      el.className = 'toast info';
      el.innerHTML = `<strong>Devnet rate-limited</strong><br/>
        <span style="font-size:12px;color:#8899aa">Use the web faucet instead:</span><br/>
        <a href="${d.faucetUrl}" target="_blank" 
           style="color:var(--accent);font-size:12px;word-break:break-all">
          faucet.solana.com ↗</a>`;
      document.getElementById('toasts').prepend(el);
      setTimeout(() => el.remove(), 8000);
    } else {
      toast('Airdrop failed — devnet may be rate-limiting', 'info');
    }
  } catch (e) { toast('Airdrop request failed', 'info'); }
}

async function manualTrade(side) {
  const token   = document.getElementById('tradeToken').value;
  const sizePct = parseFloat(document.getElementById('tradeSize').value) || 10;
  try {
    const r = await fetch('/api/trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ side, token, sizePct }),
    });
    const d = await r.json();
    if (d.error) { toast(d.error, 'info'); return; }
    toast(`Manual ${side} ${token} executed`, side === 'BUY' ? 'buy' : 'sell');
    if (d.id) {
      state.trades.unshift(d);
      renderTrades();
    }
  } catch (e) { toast('Trade request failed', 'info'); }
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initChart();
  initPnlChart();
  connectWS();

  // Fallback polling if WS drops
  setInterval(async () => {
    if (state.connected) return;
    try {
      const r = await fetch('/api/state');
      const d = await r.json();
      mergeState({ type: 'price_update', ...d });
      if (d.lastSignal) renderSignal(d.lastSignal);
      if (d.trades) { state.trades = d.trades; renderTrades(); }
      renderPrices();
      renderPortfolio();
      updateChart();
    } catch {}
  }, 8000);
});
