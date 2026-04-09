/**
 * AstralPrism DeFi Bot v2 — Dashboard
 * TradingView Lightweight Charts · Aurora background · Glassmorphism
 * WebSocket real-time: prices, candles, indicators, AI signals
 */

// ─── State ───────────────────────────────────────────────────────────────────
const S = {
  prices:      {},
  history:     { SOL:[], JUP:[], BONK:[], WIF:[] },
  indicators:  {},
  correlations:{},
  candles:     { SOL:[], JUP:[], BONK:[], WIF:[] },
  portfolio:   { sol:2, usdc:100, pnl:0, pnlPct:0, totalValueUSD:0 },
  trades:      [],
  lastSignal:  null,
  trailing:    {},
  connected:   false,
  paused:      false,
  isLive:      false,
  activeToken: 'SOL',
};

const TOKEN_COLORS = { SOL:'#A66CFA', JUP:'#38E9E2', BONK:'#F5C518', WIF:'#FF6B6B' };
const TOKEN_NAMES  = { SOL:'Solana', JUP:'Jupiter', BONK:'Bonk', WIF:'dogwifhat' };

let ws          = null;
let tvChart     = null;
let candleSeries = null;
let pnlChart    = null;
let pnlSeries   = null;
let pnlData     = [];

// ─── Aurora Background ───────────────────────────────────────────────────────
(function initAurora() {
  const canvas = document.getElementById('auroraCanvas');
  const ctx    = canvas.getContext('2d');
  let W, H, particles = [], t = 0;

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function makeParticle() {
    return {
      x:    Math.random() * W,
      y:    H + Math.random() * 100,
      vx:   (Math.random() - 0.5) * 0.3,
      vy:   -Math.random() * 0.4 - 0.1,
      r:    Math.random() * 1.5 + 0.3,
      alpha: Math.random() * 0.5 + 0.1,
      color: Math.random() > 0.5 ? '#A66CFA' : '#38E9E2',
    };
  }

  for (let i = 0; i < 80; i++) {
    const p = makeParticle();
    p.y = Math.random() * H;  // scatter initially
    particles.push(p);
  }

  function drawAurora() {
    ctx.clearRect(0, 0, W, H);

    // Aurora blobs
    const blobs = [
      { x: W*0.2 + Math.sin(t*0.3)*80,  y: H*0.3 + Math.cos(t*0.2)*60,  r: 280, c: '#A66CFA' },
      { x: W*0.8 + Math.cos(t*0.25)*90, y: H*0.6 + Math.sin(t*0.3)*70,  r: 320, c: '#38E9E2' },
      { x: W*0.5 + Math.sin(t*0.2)*120, y: H*0.15 + Math.cos(t*0.35)*50, r: 220, c: '#6245CC' },
    ];

    blobs.forEach(b => {
      const grad = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.r);
      grad.addColorStop(0, b.c + '18');
      grad.addColorStop(1, b.c + '00');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2);
      ctx.fill();
    });

    // Particles
    particles.forEach((p, i) => {
      p.x += p.vx;
      p.y += p.vy;
      p.alpha -= 0.0008;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color + Math.floor(p.alpha * 255).toString(16).padStart(2,'0');
      ctx.fill();

      if (p.y < -10 || p.alpha <= 0) particles[i] = makeParticle();
    });

    t += 0.008;
    requestAnimationFrame(drawAurora);
  }

  resize();
  window.addEventListener('resize', resize);
  drawAurora();
})();

// ─── TradingView Chart ───────────────────────────────────────────────────────
function initTvChart() {
  const el = document.getElementById('tvChart');
  tvChart = LightweightCharts.createChart(el, {
    width:  el.clientWidth,
    height: el.clientHeight || 260,
    layout: {
      background:  { type: 'solid', color: 'transparent' },
      textColor:   '#7a7a9a',
      fontFamily:  "'JetBrains Mono', monospace",
    },
    grid: {
      vertLines:   { color: 'rgba(166,108,250,0.06)' },
      horzLines:   { color: 'rgba(166,108,250,0.06)' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine:  { color: '#A66CFA88', width: 1, style: 1 },
      horzLine:  { color: '#A66CFA88', width: 1, style: 1 },
    },
    rightPriceScale: {
      borderColor: 'rgba(166,108,250,0.15)',
      textColor:   '#7a7a9a',
    },
    timeScale: {
      borderColor:     'rgba(166,108,250,0.15)',
      timeVisible:     true,
      secondsVisible:  false,
    },
    handleScroll: true,
    handleScale:  true,
  });

  candleSeries = tvChart.addCandlestickSeries({
    upColor:        '#1df5a3',
    downColor:      '#ff4f6b',
    borderUpColor:  '#1df5a3',
    borderDownColor:'#ff4f6b',
    wickUpColor:    '#1df5a3',
    wickDownColor:  '#ff4f6b',
  });

  // Add EMA overlays
  window.ema9Series  = tvChart.addLineSeries({ color: '#A66CFA', lineWidth: 1, title: 'EMA9',  priceLineVisible: false, lastValueVisible: false });
  window.ema21Series = tvChart.addLineSeries({ color: '#38E9E2', lineWidth: 1, title: 'EMA21', priceLineVisible: false, lastValueVisible: false });

  new ResizeObserver(() => {
    tvChart.applyOptions({ width: el.clientWidth, height: el.clientHeight || 260 });
  }).observe(el);
}

function updateCandleChart() {
  const sym     = S.activeToken;
  const candles = S.candles[sym] || [];
  if (!candleSeries || candles.length === 0) return;

  const data = candles
    .filter(c => c.open && c.high && c.low && c.close)
    .map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }));

  if (data.length > 0) {
    try { candleSeries.setData(data); } catch(e) {}
  }

  // EMA overlays from price history
  const hist = S.history[sym] || [];
  if (hist.length >= 21 && candles.length >= 9) {
    const ema9pts  = buildEmaPoints(candles, hist, 9);
    const ema21pts = buildEmaPoints(candles, hist, 21);
    try {
      window.ema9Series.setData(ema9pts);
      window.ema21Series.setData(ema21pts);
    } catch(e) {}
  }

  // Price info
  const price  = S.prices[sym] || 0;
  const hist50 = hist.slice(0, -1);
  const change = hist50.length >= 2 ? ((hist[hist.length-1] - hist50[0]) / hist50[0] * 100) : 0;
  const color  = TOKEN_COLORS[sym];

  document.getElementById('cpiPrice').textContent  = '$' + fmtPrice(price, sym);
  document.getElementById('cpiPrice').style.color  = color;
  const chgEl = document.getElementById('cpiChange');
  chgEl.textContent  = (change >= 0 ? '+' : '') + change.toFixed(3) + '%';
  chgEl.style.color  = change >= 0 ? 'var(--green)' : 'var(--red)';
}

function buildEmaPoints(candles, prices, period) {
  const k = 2 / (period + 1);
  if (prices.length < period) return [];
  let ema = prices.slice(0, period).reduce((a, b) => a + b, 0) / period;
  const pts = [];
  candles.slice(-(prices.length - period)).forEach((c, i) => {
    const p = prices[period + i] || c.close;
    ema = p * k + ema * (1 - k);
    pts.push({ time: c.time, value: ema });
  });
  return pts;
}

// ─── P&L Chart ───────────────────────────────────────────────────────────────
function initPnlChart() {
  const el = document.getElementById('pnlChart');
  pnlChart = LightweightCharts.createChart(el, {
    width:  el.clientWidth,
    height: el.clientHeight || 90,
    layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#7a7a9a' },
    grid:   { vertLines: { visible: false }, horzLines: { color: 'rgba(166,108,250,0.05)' } },
    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.1 } },
    timeScale: { visible: false },
    handleScroll: false, handleScale: false,
  });
  pnlSeries = pnlChart.addAreaSeries({
    lineColor: '#1df5a3', topColor: '#1df5a320', bottomColor: '#1df5a300',
    lineWidth: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
  });
  new ResizeObserver(() => pnlChart.applyOptions({ width: el.clientWidth })).observe(el);
}

function updatePnlChart() {
  if (!pnlSeries || pnlData.length === 0) return;
  const last50 = pnlData.slice(-50);
  const lastV  = last50[last50.length - 1]?.value || 0;
  const col    = lastV >= 0 ? '#1df5a3' : '#ff4f6b';
  pnlSeries.applyOptions({ lineColor: col, topColor: col + '20', bottomColor: col + '00' });
  try { pnlSeries.setData(last50); } catch(e) {}
  const badge = document.getElementById('pnlBadge');
  badge.textContent = (lastV >= 0 ? '+' : '') + '$' + lastV.toFixed(4);
  badge.style.color = lastV >= 0 ? 'var(--green)' : 'var(--red)';
}

// ─── WebSocket ───────────────────────────────────────────────────────────────
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => { setStatus('live', 'Live'); S.connected = true; };
  ws.onmessage = e => handleMsg(JSON.parse(e.data));
  ws.onclose   = () => {
    setStatus('connecting', 'Reconnecting');
    S.connected = false;
    setTimeout(connectWS, 3000);
  };
  ws.onerror = () => ws.close();
}

function handleMsg(msg) {
  switch(msg.type) {
    case 'connected':
    case 'price_update':
      mergeState(msg);
      renderTokens();
      renderPortfolio();
      renderIndicators(S.activeToken);
      renderCorrelations();
      renderTrailing();
      updateCandleChart();
      break;

    case 'analysis_start':
      document.getElementById('thinkingOverlay').classList.remove('hidden');
      break;

    case 'analysis_complete':
      document.getElementById('thinkingOverlay').classList.add('hidden');
      mergeState(msg);
      renderSignal(msg.signal);
      renderPortfolio();
      if (msg.trade && msg.trade.id) {
        S.trades.unshift(msg.trade);
        renderTrades();
        showTradeToast(msg.trade);
        document.querySelector('.signal-panel')?.classList.add('trade-flash');
        setTimeout(() => document.querySelector('.signal-panel')?.classList.remove('trade-flash'), 700);
        // Push P&L point
        pnlData.push({ time: Math.floor(Date.now()/1000), value: S.portfolio.pnl || 0 });
        updatePnlChart();
      }
      renderTrailing();
      break;

    case 'trailing_stop_triggered':
      showToast(`🔁 Trailing stop hit: ${msg.token} @ $${(msg.price||0).toFixed(5)}`, 'warn');
      if (msg.trade) { S.trades.unshift(msg.trade); renderTrades(); }
      mergePortfolio(msg.portfolio);
      break;

    case 'trade_blocked':
      showToast(`⚡ Trade blocked: ${msg.reason}`, 'info');
      break;

    case 'trade_failed':
      showToast(`✗ Trade failed: ${msg.error}`, 'sell');
      break;

    case 'bot_halted':
      showToast(`⬛ Bot halted: ${msg.reason}`, 'sell');
      document.getElementById('liveBanner').classList.add('halted');
      break;
  }
}

function mergeState(msg) {
  if (msg.prices)       S.prices       = {...S.prices, ...msg.prices};
  if (msg.history)      S.history      = {...S.history, ...msg.history};
  if (msg.indicators)   S.indicators   = msg.indicators;
  if (msg.correlations) S.correlations = msg.correlations;
  if (msg.portfolio)    S.portfolio    = msg.portfolio;
  if (msg.trailing)     S.trailing     = msg.trailing;
  if (msg.trades)       S.trades       = msg.trades;
  if (msg.lastSignal)   S.lastSignal   = msg.lastSignal;
  if (msg.isLive !== undefined) { S.isLive = msg.isLive; setLiveMode(msg.isLive, msg.portfolio); }
  if (msg.isDemo !== undefined) setModelMode(msg.isDemo);
  if (msg.wallet)       setWalletInfo(msg);
  if (msg.candles)      mergeCandles(msg.candles);
  if (msg.newCandles)   mergeNewCandles(msg.newCandles);
}

function mergePortfolio(p) { if(p) { S.portfolio = p; renderPortfolio(); } }
function mergeCandles(data) { Object.entries(data).forEach(([sym, cs]) => { if(cs?.length) S.candles[sym] = cs; }); }
function mergeNewCandles(data) {
  Object.entries(data).forEach(([sym, c]) => {
    if (!S.candles[sym]) S.candles[sym] = [];
    const last = S.candles[sym][S.candles[sym].length - 1];
    if (last && last.time === c.time) S.candles[sym][S.candles[sym].length-1] = c;
    else S.candles[sym].push(c);
    if (sym === S.activeToken) updateCandleChart();
  });
}

// ─── Token Cards ─────────────────────────────────────────────────────────────
function renderTokens() {
  const syms = ['SOL','JUP','BONK','WIF'];
  document.getElementById('tokenList').innerHTML = syms.map(sym => {
    const price  = S.prices[sym] || 0;
    const hist   = S.history[sym] || [];
    const prev   = hist.length >= 2 ? hist[hist.length - 2] : price;
    const change = prev ? ((price - prev) / prev * 100) : 0;
    const color  = TOKEN_COLORS[sym];
    const ind    = S.indicators[sym] || {};
    const rsi    = ind.rsi;
    return `
      <div class="token-card ${sym === S.activeToken ? 'active' : ''}"
           onclick="switchChart('${sym}')"
           style="border-left-color:${color}30">
        <div class="tc-top">
          <span class="tc-sym" style="color:${color}">${sym}</span>
          <span class="tc-price">$${fmtPrice(price, sym)}</span>
        </div>
        <div class="tc-bot">
          <span class="tc-name">${TOKEN_NAMES[sym]}${rsi != null ? ` · RSI ${rsi}` : ''}</span>
          <span class="tc-chg ${change >= 0 ? 'up' : 'down'}">${change >= 0 ? '▲' : '▼'} ${Math.abs(change).toFixed(3)}%</span>
        </div>
      </div>`;
  }).join('');
}

function fmtPrice(p, sym) {
  if (!p) return '—';
  if (sym === 'BONK') return p.toFixed(9);
  if (p < 0.001)      return p.toExponential(4);
  if (p < 1)          return p.toFixed(5);
  return p.toFixed(3);
}

// ─── Indicators ──────────────────────────────────────────────────────────────
function renderIndicators(sym) {
  const ind = S.indicators[sym] || {};
  document.getElementById('indToken').textContent = sym;

  const rsi = ind.rsi;
  const rsiEl = document.getElementById('rsiVal');
  rsiEl.textContent = rsi != null ? rsi : '—';
  rsiEl.style.color = rsi == null ? 'var(--text2)' : rsi < 30 ? 'var(--green)' : rsi > 70 ? 'var(--red)' : 'var(--yellow)';
  const rsiBar = document.getElementById('rsiBar');
  if (rsi != null) { rsiBar.style.width = rsi + '%'; rsiBar.style.background = rsi < 30 ? 'var(--green)' : rsi > 70 ? 'var(--red)' : 'var(--yellow)'; }

  const emaCross = ind.emaCross;
  const emaEl = document.getElementById('emaVal');
  emaEl.textContent = emaCross || '—';
  emaEl.style.color = emaCross === 'GOLDEN' ? 'var(--green)' : emaCross === 'DEATH' ? 'var(--red)' : 'var(--text2)';

  const macd = ind.macd || {};
  const macdEl = document.getElementById('macdVal');
  macdEl.textContent = macd.bullish == null ? '—' : macd.bullish ? '↑ Bullish' : '↓ Bearish';
  macdEl.style.color = macd.bullish == null ? 'var(--text2)' : macd.bullish ? 'var(--green)' : 'var(--red)';

  const bb = ind.bollinger || {};
  const bbEl = document.getElementById('bbVal');
  const bbState = bb.overbought ? 'OB' : bb.oversold ? 'OS' : bb.pctB != null ? `%B ${bb.pctB}` : '—';
  bbEl.textContent = bbState;
  bbEl.style.color = bb.overbought ? 'var(--red)' : bb.oversold ? 'var(--green)' : 'var(--text2)';

  const momEl = document.getElementById('momVal');
  const mom = ind.momentum5;
  momEl.textContent = mom != null ? (mom >= 0 ? '+' : '') + mom.toFixed(3) + '%' : '—';
  momEl.style.color = mom == null ? 'var(--text2)' : mom >= 0 ? 'var(--green)' : 'var(--red)';

  const volEl = document.getElementById('volVal');
  const vol = ind.volatility;
  volEl.textContent = vol != null ? vol.toFixed(3) + '%' : '—';
  volEl.style.color = vol == null ? 'var(--text2)' : vol > 2 ? 'var(--red)' : vol > 0.8 ? 'var(--yellow)' : 'var(--green)';
}

// ─── Signal ───────────────────────────────────────────────────────────────────
function renderSignal(sig) {
  if (!sig) return;
  const { signal, token, confidence, reasoning, marketCondition, riskLevel,
          targetPrice, stopLoss, trailPct, indicatorScore } = sig;

  const panel = document.getElementById('signalPanel');
  panel.className = 'panel glass signal-panel ' + (signal === 'BUY' ? 'buy' : signal === 'SELL' ? 'sell' : '');

  const badge = document.getElementById('sigBadge');
  badge.textContent = signal || '—';
  badge.style.color = signal === 'BUY' ? 'var(--green)' : signal === 'SELL' ? 'var(--red)' : 'var(--text2)';

  document.getElementById('sigToken').textContent  = `${token} · ${sig.isDemo ? 'DEMO' : 'NEMOTRON'}`;
  document.getElementById('sigReason').textContent = reasoning || '—';
  if (indicatorScore != null)
    document.getElementById('sigScore').textContent = `Score: ${indicatorScore >= 0 ? '+' : ''}${indicatorScore}`;

  // Gauge
  const conf = confidence || 0;
  const confPct = Math.round(conf * 100);
  document.getElementById('gaugePct').textContent = confPct + '%';
  const arc = document.getElementById('gaugeArc');
  const totalLen = 126;
  arc.style.strokeDashoffset = totalLen * (1 - conf);
  arc.style.stroke = conf > 0.7 ? 'var(--green)' : conf > 0.5 ? 'var(--violet)' : 'var(--red)';

  document.getElementById('ssCond').textContent  = marketCondition || '—';
  document.getElementById('ssCond').style.color  = marketCondition === 'BULLISH' ? 'var(--green)' : marketCondition === 'BEARISH' ? 'var(--red)' : 'var(--text2)';
  document.getElementById('ssRisk').textContent  = riskLevel || '—';
  document.getElementById('ssRisk').style.color  = riskLevel === 'HIGH' ? 'var(--red)' : riskLevel === 'LOW' ? 'var(--green)' : 'var(--yellow)';
  document.getElementById('ssTgt').textContent   = targetPrice ? '$'+fmtPrice(targetPrice, token) : '—';
  document.getElementById('ssStop').textContent  = stopLoss ? '$'+fmtPrice(stopLoss, token) : '—';
  document.getElementById('ssTrail').textContent = trailPct ? (trailPct*100).toFixed(1)+'%' : '—';
}

// ─── Portfolio ────────────────────────────────────────────────────────────────
function renderPortfolio() {
  const p = S.portfolio;
  if (!p) return;
  const pnl    = p.pnl || 0;
  const pnlPct = p.pnlPct || 0;
  document.getElementById('portValue').textContent = '$' + (p.totalValueUSD || 0).toFixed(2);
  const pnlEl = document.getElementById('portPnl');
  pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(3)}%)`;
  pnlEl.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById('piSol').textContent  = (p.sol || 0).toFixed(5) + ' SOL';
  document.getElementById('piUsdc').textContent = '$' + (p.usdc || 0).toFixed(2);
  document.getElementById('piTrades').textContent = p.tradeCount || 0;
  document.getElementById('portMode').textContent = S.isLive ? 'LIVE' : 'DEMO';
  document.getElementById('portMode').style.color = S.isLive ? 'var(--red)' : 'var(--text2)';

  // Win rate
  const wins = S.trades.filter(t => t.pnl > 0).length;
  const total = S.trades.length;
  document.getElementById('piWin').textContent = total > 0 ? Math.round(wins/total*100)+'%' : '—';

  // Live loss budget
  if (S.isLive && p.lossRemaining != null) setLiveMode(true, p);
}

// ─── Trailing Stops ───────────────────────────────────────────────────────────
function renderTrailing() {
  const t = S.trailing || {};
  const keys = Object.keys(t);
  const section = document.getElementById('trailingSection');
  const badge   = document.getElementById('trailBadge');

  if (keys.length === 0) {
    section.classList.add('hidden');
    badge.classList.remove('visible'); badge.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');
  badge.classList.remove('hidden'); badge.classList.add('visible');

  document.getElementById('trailingList').innerHTML = keys.map(sym => {
    const state = t[sym];
    return `<div class="trail-item">
      <span class="trail-sym">📌 ${sym}</span>
      <span>High: $${fmtPrice(state.highest, sym)}</span>
      <span class="trail-stop">Stop: $${fmtPrice(state.stopPrice, sym)}</span>
    </div>`;
  }).join('');
}

// ─── Correlations ─────────────────────────────────────────────────────────────
function renderCorrelations() {
  const corr = S.correlations;
  const syms = ['JUP','BONK','WIF'];
  document.getElementById('corrRow').innerHTML = syms.map(sym => {
    const v  = corr[sym];
    const color = v == null ? 'var(--text2)' : v > 0.6 ? 'var(--green)' : v < -0.4 ? 'var(--red)' : 'var(--yellow)';
    const bw = v != null ? Math.abs(v) * 100 : 0;
    const tc = TOKEN_COLORS[sym];
    return `<div class="corr-item">
      <div class="corr-sym" style="color:${tc}">${sym}/SOL</div>
      <div class="corr-val" style="color:${color}">${v != null ? (v >= 0 ? '+' : '') + v.toFixed(2) : '—'}</div>
      <div class="corr-bar" style="width:${bw}%;background:${color};margin:0 auto"></div>
    </div>`;
  }).join('');
}

// ─── Trades Table ─────────────────────────────────────────────────────────────
function renderTrades() {
  const tbody = document.getElementById('tradeBody');
  const badge = document.getElementById('tradeCountBadge');
  badge.textContent = `${S.trades.length} trade${S.trades.length !== 1 ? 's' : ''}`;

  if (!S.trades.length) {
    tbody.innerHTML = '<tr><td colspan="12" class="empty-cell">No trades yet — building indicator history...</td></tr>';
    return;
  }
  tbody.innerHTML = S.trades.slice(0, 50).map(t => {
    const ts      = t.timestamp ? new Date(t.timestamp*1000).toLocaleTimeString() : '—';
    const isBuy   = t.side === 'BUY';
    const isTrail = t.isTrailingStop;
    const color   = TOKEN_COLORS[t.token] || '#fff';
    return `<tr>
      <td>#${t.id}</td>
      <td style="color:var(--text2)">${ts}</td>
      <td class="${isBuy ? 'buy-cell' : 'sell-cell'}">${isBuy ? '▲ BUY' : '▼ SELL'}${isTrail ? '<br><span class="trail-badge-row">TRAIL</span>' : ''}</td>
      <td style="color:${color};font-weight:700">${t.token}</td>
      <td>${(t.size||0).toFixed(6)}</td>
      <td>$${fmtPrice(t.price||0, t.token)}</td>
      <td>$${(t.cost||0).toFixed(3)}</td>
      <td style="color:${(t.confidence||0)>=0.7?'var(--green)':'var(--yellow)'}">${((t.confidence||0)*100).toFixed(1)}%</td>
      <td style="color:${t.indicatorScore>=0?'var(--green)':'var(--red)'}; font-family:var(--mono)">${t.indicatorScore!=null?(t.indicatorScore>=0?'+':'')+t.indicatorScore:'—'}</td>
      <td style="color:var(--text2)">${t.condition||'—'}</td>
      <td style="color:var(--text3);font-size:10px">${t.route||'Jupiter'}</td>
      <td style="color:var(--green)">✓ ${t.status||'FILLED'}</td>
    </tr>`;
  }).join('');
}

// ─── Chart switching ──────────────────────────────────────────────────────────
function switchChart(sym) {
  S.activeToken = sym;
  document.querySelectorAll('.ctab').forEach(t => t.classList.toggle('active', t.textContent === sym));
  updateCandleChart();
  renderTokens();
  renderIndicators(sym);
}

// ─── Size slider ──────────────────────────────────────────────────────────────
function updateSizeLabel() {
  document.getElementById('sizeLabel').textContent = document.getElementById('tradeSize').value + '%';
}

// ─── UI Helpers ───────────────────────────────────────────────────────────────
function setStatus(type, label) {
  document.getElementById('statusDot').className  = 's-dot ' + type;
  document.getElementById('statusText').textContent = label;
}

function setWalletInfo(msg) {
  if (!msg.wallet) return;
  const addr = msg.wallet;
  document.getElementById('walletAddr').textContent = addr.slice(0,8) + '...' + addr.slice(-8);
  document.getElementById('walletSol').textContent  = (msg.devnetSol||0).toFixed(5) + ' SOL';
  const link = document.getElementById('explorerLink');
  link.href = msg.explorerUrl || `https://explorer.solana.com/address/${addr}?cluster=devnet`;
}

function setModelMode(isDemo) {
  const tag = document.getElementById('modeTag');
  tag.textContent = isDemo ? 'DEMO' : 'LIVE AI';
  tag.style.color = isDemo ? 'var(--yellow)' : 'var(--green)';
}

function setLiveMode(isLive, port) {
  const banner = document.getElementById('liveBanner');
  if (!isLive) { banner.classList.add('hidden'); return; }
  banner.classList.remove('hidden');
  document.getElementById('networkLabel').textContent = 'Solana Mainnet';
  const cap = port?.lossCapUSD || 10;
  const rem = port?.lossRemaining ?? cap;
  const pct = Math.max(0, Math.min(100, (rem/cap)*100));
  const budgetEl = document.getElementById('lossBudget');
  const barEl    = document.getElementById('lossBar');
  budgetEl.textContent = '$' + rem.toFixed(2);
  const col = rem > cap*0.6 ? 'var(--green)' : rem > cap*0.25 ? 'var(--yellow)' : 'var(--red)';
  budgetEl.style.color = col;
  barEl.style.width    = pct + '%';
  barEl.style.background = col;
  if (port?.halted) {
    banner.classList.add('halted');
    banner.querySelector('.live-label').textContent = '⬛ BOT HALTED';
  }
}

function showTradeToast(t) {
  const el = document.createElement('div');
  el.className = `toast ${t.side.toLowerCase()}`;
  el.innerHTML = `<strong>${t.side==='BUY'?'▲ BUY':'▼ SELL'} ${t.token}${t.isTrailingStop?' <span style="color:var(--yellow);font-size:10px">TRAIL</span>':''}</strong>
    <div style="margin-top:4px;color:var(--text2);font-size:11px">${(t.size||0).toFixed(5)} @ $${fmtPrice(t.price||0,t.token)} · ${((t.confidence||0)*100).toFixed(1)}% conf · Score ${t.indicatorScore>=0?'+':''}${t.indicatorScore}</div>`;
  document.getElementById('toastContainer').prepend(el);
  setTimeout(() => el.remove(), 5000);
}

function showToast(msg, type='info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toastContainer').prepend(el);
  setTimeout(() => el.remove(), 4000);
}

// ─── API actions ──────────────────────────────────────────────────────────────
async function togglePause() {
  const r = await fetch('/api/bot/pause', { method:'POST' });
  const d = await r.json();
  S.paused = d.status === 'paused';
  document.getElementById('btnPause').textContent = S.paused ? '▶ Resume' : '⏸ Pause';
  showToast(S.paused ? 'Bot paused' : 'Bot resumed', 'info');
}

async function requestAirdrop() {
  showToast('Requesting 1 SOL from devnet (3 retries)...', 'info');
  const r = await fetch('/api/airdrop', { method:'POST' });
  const d = await r.json();
  if (d.success) {
    document.getElementById('walletSol').textContent = d.balance.toFixed(5) + ' SOL';
    showToast(`Airdrop received! ${d.amount} SOL · Balance: ${d.balance.toFixed(4)} SOL`, 'buy');
  } else if (d.faucetUrl) {
    const el = document.createElement('div');
    el.className = 'toast warn';
    el.innerHTML = `<strong>Devnet rate-limited</strong><br>
      <a href="${d.faucetUrl}" target="_blank" style="color:var(--violet)">Use faucet.solana.com ↗</a>`;
    document.getElementById('toastContainer').prepend(el);
    setTimeout(() => el.remove(), 8000);
  } else {
    showToast('Airdrop failed — try faucet.solana.com', 'warn');
  }
}

async function manualTrade(side) {
  const token   = document.getElementById('tradeToken').value;
  const sizePct = parseFloat(document.getElementById('tradeSize').value) || 10;
  showToast(`Manual ${side} ${token} ${sizePct}%...`, 'info');
  const r = await fetch('/api/trade', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ side, token, sizePct }),
  });
  const d = await r.json();
  if (d.error) showToast(d.error, 'warn');
  else if (d.id) { S.trades.unshift(d); renderTrades(); showTradeToast(d); }
}

async function haltBot() {
  if (!confirm('Halt the bot immediately?')) return;
  await fetch('/api/bot/pause', { method:'POST' });
  showToast('⬛ Bot halted — no further trades', 'sell');
  document.getElementById('liveBanner').classList.add('halted');
}

// ─── Bootstrap ────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initTvChart();
  initPnlChart();
  connectWS();

  // Fallback polling
  setInterval(async () => {
    if (S.connected) return;
    try {
      const d = await fetch('/api/state').then(r => r.json());
      mergeState({...d, type:'price_update'});
      if (d.lastSignal)  renderSignal(d.lastSignal);
      if (d.trades)      { S.trades = d.trades; renderTrades(); }
      if (d.candles)     mergeCandles(d.candles);
      renderTokens(); renderPortfolio(); renderIndicators(S.activeToken);
      renderCorrelations(); updateCandleChart();
    } catch(e) {}
  }, 8000);
});
