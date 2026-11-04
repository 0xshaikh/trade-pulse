/* TradePulse — live strategy signals & leaderboard
 * Data: Binance public REST + WebSocket (no key, CORS open)
 * Chart: TradingView Lightweight Charts v4
 * Strategy: Donchian 20 breakout + MA100 trend filter, 2xATR stop / 3xATR target
 * Signals computed on CLOSED bars only (per market-prediction discipline)
 */
'use strict';

/* ==================== Config ==================== */
/* Binance USDT-M PERPETUAL FUTURES — user trades futures, not spot */
const REST = 'https://fapi.binance.com/fapi/v1';
const WS   = 'wss://fstream.binance.com/ws';

const ASSETS = [
  { sym: 'BTCUSDT',  label: 'BTC/USDT',   color: '#f7931a' },
  { sym: 'ETHUSDT',  label: 'ETH/USDT',   color: '#627eea' },
  { sym: 'SOLUSDT',  label: 'SOL/USDT',   color: '#9945ff' },
  { sym: 'XAUUSDT',  label: 'XAU/USDT (Gold)',   color: '#ffd700' },
  { sym: 'XAGUSDT',  label: 'XAG/USDT (Silver)', color: '#c0c0c0' },
  { sym: 'BNBUSDT',  label: 'BNB/USDT',   color: '#f0b90b' },
  { sym: 'XRPUSDT',  label: 'XRP/USDT',   color: '#23292f' },
  { sym: 'ADAUSDT',  label: 'ADA/USDT',   color: '#0033ad' },
  { sym: 'DOGEUSDT', label: 'DOGE/USDT',  color: '#c2a633' },
  { sym: 'AVAXUSDT', label: 'AVAX/USDT',  color: '#e84142' },
  { sym: 'LINKUSDT', label: 'LINK/USDT',  color: '#2a5ada' },
  { sym: 'LTCUSDT',  label: 'LTC/USDT',   color: '#bfbbbb' },
  { sym: 'DOTUSDT',  label: 'DOT/USDT',   color: '#e6007a' },
  { sym: 'MATICUSDT',label: 'MATIC/USDT', color: '#8247e5' },
];
const TF_MAP = { '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d' };
const BARS = 500;          // history bars for chart + backtest
const DONCHIAN_N = 20;     // breakout channel
const MA_N = 100;          // trend filter
const ATR_N = 14;          // volatility stop
const ATR_MULT_STOP = 2;   // 2xATR stop
const ATR_MULT_TP   = 3;   // 3xATR target
const MIN_MA_SLOPE = 0.10; // chop filter: |MA100 slope| (as % of price over 5 bars) must exceed this
const DAILY_MA_N   = 200;  // daily regime gate: trade only in direction of daily MA200

/* ==================== State ==================== */
const state = {
  symbol: 'BTCUSDT',
  interval: '4h',
  klines: [],          // {time, open, high, low, close, volume}
  dailyKlines: [],     // 1d klines for regime gate
  ws: null,
  wsSubscribed: false,
  currentAsset: null,  // active leaderboard row
};

const $ = (id) => document.getElementById(id);

/* ==================== Indicators (closed-bar) ==================== */
function sma(vals, n) {
  const out = new Array(vals.length).fill(null);
  let sum = 0;
  for (let i = 0; i < vals.length; i++) {
    sum += vals[i];
    if (i >= n) sum -= vals[i - n];
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}
function atr(klines, n) {
  const out = new Array(klines.length).fill(null);
  for (let i = 0; i < klines.length; i++) {
    if (i < n) continue;
    let s = 0;
    for (let j = i - n + 1; j <= i; j++) {
      const h = klines[j].high, l = klines[j].low, pc = klines[j - 1].close;
      s += Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc));
    }
    out[i] = s / n;
  }
  return out;
}
function donchian(klines, n) {
  const upper = new Array(klines.length).fill(null);
  const lower = new Array(klines.length).fill(null);
  for (let i = 0; i < klines.length; i++) {
    if (i < n - 1) continue;
    let hi = -Infinity, lo = Infinity;
    for (let j = i - n + 1; j <= i; j++) {
      hi = Math.max(hi, klines[j].high);
      lo = Math.min(lo, klines[j].low);
    }
    upper[i] = hi; lower[i] = lo;
  }
  return { upper, lower };
}
function maSlope(maArr, i) {
  if (i < MA_N + 5 || maArr[i] == null || maArr[i - 5] == null) return 0;
  return maArr[i] - maArr[i - 5];
}
// Slope as % of price over 5 bars (used for chop filter)
function maSlopePct(maArr, close, i) {
  if (i < MA_N + 5 || maArr[i] == null || maArr[i - 5] == null || close[i - 1] == null || close[i - 1] === 0) return 0;
  return ((maArr[i] - maArr[i - 5]) / close[i - 1]) * 100;
}
// Daily regime gate: returns +1 (uptrend), -1 (downtrend), or 0 (no data) based on daily close vs daily MA200
function dailyGate(dailyKlines, ts) {
  if (!dailyKlines || dailyKlines.length < DAILY_MA_N) return 0;
  const dclose = dailyKlines.map(k => k.close);
  const dma = sma(dclose, DAILY_MA_N);
  let idx = -1;
  for (let j = 0; j < dailyKlines.length; j++) {
    if (dailyKlines[j].time <= ts) idx = j; else break;
  }
  if (idx < DAILY_MA_N - 1 || dma[idx] == null) return 0;
  return dclose[idx] > dma[idx] ? 1 : -1;
}

/* ==================== Strategy backtest (closed bars) ==================== */
function backtest(klines) {
  const close = klines.map(k => k.close);
  const ma = sma(close, MA_N);
  const atrVals = atr(klines, ATR_N);
  const dc = donchian(klines, DONCHIAN_N);

  const trades = [];
  let pos = null; // {dir, entry, stop, target, entryIdx, barsHeld}
  const entryCost = 0.0010; // futures taker 0.05% x2 round trip (honest)
  const eq = 10000;
  let equity = eq;

  for (let i = 0; i < klines.length; i++) {
    // --- manage open position on this bar (closed) ---
    if (pos) {
      const bar = klines[i];
      let exitPrice = null, reason = null;
      if (pos.dir === 1) {
        if (bar.low <= pos.stop) { exitPrice = pos.stop; reason = 'stop'; }
        else if (bar.high >= pos.target) { exitPrice = pos.target; reason = 'target'; }
        else if (bar.close < dc.lower[i]) { exitPrice = bar.close; reason = 'channel'; }
      } else {
        if (bar.high >= pos.stop) { exitPrice = pos.stop; reason = 'stop'; }
        else if (bar.low <= pos.target) { exitPrice = pos.target; reason = 'target'; }
        else if (bar.close > dc.upper[i]) { exitPrice = bar.close; reason = 'channel'; }
      }
      if (exitPrice != null && bar.time > pos.entryIdx) {
        const gross = (exitPrice - pos.entry) / pos.entry * pos.dir;
        const net = gross - entryCost;
        trades.push({ dir: pos.dir, entry: pos.entry, exit: exitPrice, net, reason, barsHeld: i - pos.entryIdx, entryTime: klines[pos.entryIdx].time, exitTime: bar.time });
        equity *= (1 + net);
        pos = null;
      }
    }
    // --- signal on closed bar i (only once indicators ready) ---
    if (i < MA_N + 5 || ma[i] == null || atrVals[i] == null || dc.upper[i] == null || dc.upper[i - 1] == null) continue;
    if (pos) continue;
    const slope = maSlopePct(ma, close, i);
    // Chop filter: skip if MA100 too flat (chop regime — the #1 loss cause)
    if (Math.abs(slope) < MIN_MA_SLOPE) continue;
    const prevClose = close[i - 1];
    // Daily regime gate: only long in daily uptrend, only short in daily downtrend
    const gate = dailyGate(state.dailyKlines, klines[i].time);
    // Long: close breaks above PRIOR 20-bar high (no look-ahead) AND MA100 rising
    if (prevClose <= dc.upper[i - 1] && close[i] > dc.upper[i - 1] && slope > 0 && close[i] > ma[i] && gate !== -1) {
      const entry = close[i];
      pos = { dir: 1, entry, stop: entry - ATR_MULT_STOP * atrVals[i], target: entry + ATR_MULT_TP * atrVals[i], entryIdx: i };
    }
    // Short: close breaks below PRIOR 20-bar low (no look-ahead) AND MA100 falling
    else if (prevClose >= dc.lower[i - 1] && close[i] < dc.lower[i - 1] && slope < 0 && close[i] < ma[i] && gate !== 1) {
      const entry = close[i];
      pos = { dir: -1, entry, stop: entry + ATR_MULT_STOP * atrVals[i], target: entry - ATR_MULT_TP * atrVals[i], entryIdx: i };
    }
  }

  // --- metrics ---
  const wins = trades.filter(t => t.net > 0);
  const losses = trades.filter(t => t.net <= 0);
  const grossW = wins.reduce((s, t) => s + t.net, 0);
  const grossL = Math.abs(losses.reduce((s, t) => s + t.net, 0));
  const netReturn = (equity / eq - 1) * 100;
  return {
    trades,
    metrics: {
      total: trades.length,
      winRate: trades.length ? (wins.length / trades.length) * 100 : 0,
      netReturn,
      profitFactor: grossL > 0 ? grossW / grossL : (grossW > 0 ? Infinity : 0),
      avgR: trades.length ? trades.reduce((s, t) => s + t.net, 0) / trades.length : 0,
      maxWin: wins.length ? Math.max(...wins.map(t => t.net)) : 0,
    },
  };
}

/* ==================== Data fetch ==================== */
async function fetchKlines(symbol, interval, limit = BARS) {
  const url = `${REST}/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Binance ${r.status}`);
  const raw = await r.json();
  return raw.map(k => ({
    time: Math.floor(k[0] / 1000),
    open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5],
  }));
}
async function fetch24h(symbol) {
  const r = await fetch(`${REST}/ticker/24hr?symbol=${symbol}`);
  if (!r.ok) return null;
  return r.json();
}
async function fetchDaily(symbol) {
  const r = await fetch(`${REST}/klines?symbol=${symbol}&interval=1d&limit=${DAILY_MA_N + 20}`);
  if (!r.ok) return [];
  const raw = await r.json();
  return raw.map(k => ({ time: Math.floor(k[0] / 1000), open: +k[1], high: +k[2], low: +k[3], close: +k[4] }));
}

/* ==================== Chart ==================== */
let chart = null, candleSeries = null, donkHiSeries = null, donkLoSeries = null, maSeries = null;

function initChart() {
  chart = LightweightCharts.createChart($('chart'), {
    layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#9ca3af', fontFamily: "'Inter', sans-serif" },
    grid: { vertLines: { color: 'rgba(31,41,55,0.4)' }, horzLines: { color: 'rgba(31,41,55,0.4)' } },
    rightPriceScale: { borderColor: 'rgba(0,245,255,0.15)' },
    timeScale: { borderColor: 'rgba(0,245,255,0.15)', timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    autoSize: true,
  });
  candleSeries = chart.addCandlestickSeries({
    upColor: '#00ff88', downColor: '#ff4444',
    wickUpColor: '#00ff88', wickDownColor: '#ff4444',
    borderVisible: false,
  });
  donkHiSeries = chart.addLineSeries({ color: '#00f5ff', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, title: 'Donchian 20 High' });
  donkLoSeries = chart.addLineSeries({ color: '#0099ff', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, title: 'Donchian 20 Low' });
  maSeries = chart.addLineSeries({ color: '#ffaa00', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, title: 'MA100' });
}

/* ==================== Render chart ==================== */
function renderChart(klines) {
  const candles = klines.map(k => ({ time: k.time, open: k.open, high: k.high, low: k.low, close: k.close }));
  candleSeries.setData(candles);

  const close = klines.map(k => k.close);
  const ma = sma(close, MA_N);
  const dc = donchian(klines, DONCHIAN_N);

  const donkHi = [], donkLo = [], maData = [];
  for (let i = 0; i < klines.length; i++) {
    if (dc.upper[i] != null) donkHi.push({ time: klines[i].time, value: dc.upper[i] });
    if (dc.lower[i] != null) donkLo.push({ time: klines[i].time, value: dc.lower[i] });
    if (ma[i] != null) maData.push({ time: klines[i].time, value: ma[i] });
  }
  donkHiSeries.setData(donkHi);
  donkLoSeries.setData(donkLo);
  maSeries.setData(maData);

  // Buy/sell markers at each breakout signal (closed-bar, Donchian+MA100 + chop/daily gates)
  const sigMarkers = [];
  let lastTrade = 0;
  for (let i = 1; i < klines.length && sigMarkers.length < 40; i++) {
    if (i < lastTrade) continue;
    const prevClose = close[i - 1];
    const slope = maSlopePct(ma, close, i);
    if (ma[i] == null || dc.upper[i] == null) continue;
    if (Math.abs(slope) < MIN_MA_SLOPE) continue;
    const gate = dailyGate(state.dailyKlines, klines[i].time);
    const isLong = prevClose <= dc.upper[i - 1] && close[i] > dc.upper[i - 1] && slope > 0 && close[i] > ma[i] && gate !== -1;
    const isShort = prevClose >= dc.lower[i - 1] && close[i] < dc.lower[i - 1] && slope < 0 && close[i] < ma[i] && gate !== 1;
    if (isLong) {
      sigMarkers.push({ time: klines[i].time, position: 'belowBar', color: '#00ff88', shape: 'arrowUp', text: 'BUY' });
      lastTrade = i + 20; // don't re-signal inside channel period
    } else if (isShort) {
      sigMarkers.push({ time: klines[i].time, position: 'aboveBar', color: '#ff4444', shape: 'arrowDown', text: 'SELL' });
      lastTrade = i + 20;
    }
  }
  candleSeries.setMarkers(sigMarkers);
  chart.timeScale().fitContent();
}

/* ==================== WebSocket live updates ==================== */
function connectWS() {
  if (state.ws) { try { state.ws.close(); } catch(e){} }
  const stream = `${state.symbol.toLowerCase()}@kline_${state.interval}`;
  const ws = new WebSocket(`${WS}/${stream}`);
  state.ws = ws;

  ws.onopen = () => { $('live-status').textContent = 'LIVE'; };
  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    const k = msg.k;
    if (!k) return;
    const bar = { time: Math.floor(k.t / 1000), open: +k.o, high: +k.h, low: +k.l, close: +k.c, volume: +k.v };
    const idx = state.klines.findIndex(x => x.time === bar.time);
    if (idx >= 0) state.klines[idx] = bar;
    else state.klines.push(bar);

    // update live candle on chart
    const last = state.klines[state.klines.length - 1];
    if (last && last.time === bar.time) {
      candleSeries.update({ time: last.time, open: last.open, high: last.high, low: last.low, close: last.close });
    }
    $('live-price').innerHTML = fmtPrice(last.close) + '<span class="chg" id="price-chg"></span>';
    updateSignalUI();
  };
  ws.onerror = () => { $('live-status').textContent = 'RECONNECTING'; };
  ws.onclose = () => { $('live-status').textContent = 'RECONNECTING'; setTimeout(connectWS, 4000); };
}

/* ==================== Signal + stats UI ==================== */
function updateSignalUI() {
  if (state.klines.length < MA_N + 5) return;
  const klines = state.klines;
  const close = klines.map(k => k.close);
  const ma = sma(close, MA_N);
  const dc = donchian(klines, DONCHIAN_N);
  const i = klines.length - 1;
  if (i < 1) return;
  const slope = maSlopePct(ma, close, i);
  const sv = $('signal-value');
  const gate = dailyGate(state.dailyKlines, klines[i].time);
  if (close[i] > dc.upper[i - 1] && slope > MIN_MA_SLOPE && close[i] > ma[i] && gate !== -1) {
    sv.textContent = 'BUY SIGNAL'; sv.className = 'signal-value buy';
  } else if (close[i] < dc.lower[i - 1] && slope < -MIN_MA_SLOPE && close[i] < ma[i] && gate !== 1) {
    sv.textContent = 'SELL SIGNAL'; sv.className = 'signal-value sell';
  } else {
    sv.textContent = 'NO TRADE'; sv.className = 'signal-value wait';
  }
}

function fmtPrice(v) {
  if (v == null) return '—';
  if (v >= 1000) return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (v >= 1) return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 5 });
}
function fmtPct(v) { return (v >= 0 ? '+' : '') + v.toFixed(1) + '%'; }

/* ==================== Trade history ==================== */
function fmtDateTime(ts) {
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}
function fmtReason(r) {
  return { stop: 'Stop', target: 'Target', channel: 'Channel exit' }[r] || r;
}
function renderTradeHistory(klines, symbol, interval) {
  const bt = backtest(klines);
  const trades = bt.trades;
  const asset = ASSETS.find(a => a.sym === symbol);
  const sub = $('history-sub');
  sub.textContent = `${asset ? asset.label : symbol} · ${interval} · ${trades.length} trades`;
  const empty = $('history-empty');
  const table = $('history-table');
  const none = $('history-none');
  if (!trades.length) {
    table.style.display = 'none'; none.style.display = 'block';
    empty.classList.add('hidden');
    return;
  }
  table.style.display = ''; none.style.display = 'none';
  empty.classList.add('hidden');
  const body = $('history-body');
  const rows = trades.map((t, i) => {
    const dollar = t.net * 10000; // $10k equity base
    const dstr = (dollar >= 0 ? '+' : '−') + '$' + Math.abs(dollar).toFixed(2);
    return `<tr>
      <td>${i + 1}</td>
      <td>${fmtDateTime(t.entryTime)} → ${fmtDateTime(t.exitTime)}</td>
      <td><span class="side-badge ${t.dir === 1 ? 'buy' : 'sell'}">${t.dir === 1 ? 'BUY' : 'SELL'}</span></td>
      <td>${fmtPrice(t.entry)}</td>
      <td>${fmtPrice(t.exit)}</td>
      <td><span class="reason-badge">${fmtReason(t.reason)}</span></td>
      <td>${t.barsHeld}</td>
      <td class="${t.net >= 0 ? 'pos' : 'neg'}">${fmtPct(t.net * 100)}</td>
      <td class="${t.net >= 0 ? 'pos' : 'neg'}">${dstr}</td>
    </tr>`;
  });
  body.innerHTML = rows.join('');
}

function showStats(m) {
  $('stat-winrate').textContent = m.winRate.toFixed(0) + '%';
  $('stat-trades').textContent = m.total;
  const retEl = $('stat-return');
  retEl.textContent = fmtPct(m.netReturn);
  retEl.className = 'stat-value mono ' + (m.netReturn >= 0 ? 'positive' : 'negative');
  const pfEl = $('stat-pf');
  pfEl.textContent = m.profitFactor === Infinity ? '∞' : m.profitFactor.toFixed(2);
  pfEl.className = 'stat-value mono ' + (m.profitFactor >= 1 ? 'positive' : 'negative');
}

/* ==================== Load symbol ==================== */
async function loadSymbol(symbol, keepChart = false) {
  state.symbol = symbol;
  const asset = ASSETS.find(a => a.sym === symbol);
  $('live-price').textContent = '…';
  $('chart-loading').classList.remove('hidden');
  try {
    const [klines, ticker, daily] = await Promise.all([
      fetchKlines(symbol, state.interval, BARS),
      fetch24h(symbol),
      fetchDaily(symbol),
    ]);
    state.klines = klines;
    state.dailyKlines = daily;
    if (!keepChart) renderChart(klines);
    const bt = backtest(klines);
    showStats(bt.metrics);
    renderTradeHistory(klines, symbol, state.interval);
    if (ticker) {
      const last = +ticker.lastPrice;
      const chg = ((last - +ticker.openPrice) / +ticker.openPrice) * 100;
      $('live-price').innerHTML = fmtPrice(last) +
        `<span class="chg ${chg >= 0 ? 'pos' : 'neg'}">${fmtPct(chg)}</span>`;
    }
    updateSignalUI();
    $('chart-loading').classList.add('hidden');
  } catch (e) {
    $('chart-loading').classList.add('hidden');
    toast('Error loading ' + symbol + ': ' + e.message);
  }
}

/* ==================== Leaderboard ==================== */
async function buildLeaderboard() {
  const tbody = $('lb-body');
  $('lb-loading').classList.remove('hidden');
  const results = await Promise.all(ASSETS.map(async (a) => {
    try {
      const [kl, daily] = await Promise.all([fetchKlines(a.sym, '1h', 400), fetchDaily(a.sym)]);
      const prevDaily = state.dailyKlines;
      state.dailyKlines = daily;   // set gate data for this asset's backtest
      const bt = backtest(kl);
      state.dailyKlines = prevDaily; // restore
      return { ...a, ...bt.metrics, klines: kl };
    } catch (e) { return { ...a, total: 0, winRate: 0, netReturn: 0, profitFactor: 0, error: true }; }
  }));
  results.sort((a, b) => b.netReturn - a.netReturn);
  tbody.innerHTML = '';
  results.forEach((r, idx) => {
    const tr = document.createElement('tr');
    if (r.sym === state.symbol) tr.className = 'active';
    const medal = idx === 0 ? 'gold' : idx === 1 ? 'silver' : idx === 2 ? 'bronze' : '';
    tr.innerHTML = `
      <td><span class="rank-badge ${medal}">${idx + 1}</span></td>
      <td>${r.label}</td>
      <td class="${r.netReturn >= 0 ? 'pos' : 'neg'}">${fmtPct(r.netReturn)}</td>
      <td>${r.total ? r.winRate.toFixed(0) + '%' : '—'}</td>
      <td>${r.total}</td>
      <td>${r.profitFactor === Infinity ? '∞' : r.total ? r.profitFactor.toFixed(2) : '—'}</td>`;
    tr.addEventListener('click', () => {
      state.symbol = r.sym;
      $('symbol-select').value = r.sym;
      loadSymbol(r.sym);
      document.querySelectorAll('#lb-body tr').forEach(x => x.classList.remove('active'));
      tr.classList.add('active');
    });
    tbody.appendChild(tr);
  });
  $('lb-loading').classList.add('hidden');
}

/* ==================== Init ==================== */
function populateSymbols() {
  const sel = $('symbol-select');
  ASSETS.forEach(a => {
    const opt = document.createElement('option');
    opt.value = a.sym; opt.textContent = a.label;
    sel.appendChild(opt);
  });
  sel.value = state.symbol;
}

document.addEventListener('DOMContentLoaded', async () => {
  populateSymbols();
  initChart();
  await loadSymbol(state.symbol);
  connectWS();
  buildLeaderboard();

  $('symbol-select').addEventListener('change', (e) => {
    state.symbol = e.target.value;
    loadSymbol(e.target.value);
    connectWS();
  });
  document.querySelectorAll('.tf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.interval = TF_MAP[btn.dataset.tf];
      loadSymbol(state.symbol);
      connectWS();
    });
  });
});

/* ==================== Toast ==================== */
function toast(msg) {
  let c = document.querySelector('.toast-container');
  if (!c) { c = document.createElement('div'); c.className = 'toast-container'; document.body.appendChild(c); }
  const t = document.createElement('div');
  t.className = 'toast'; t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity 0.3s'; setTimeout(() => t.remove(), 300); }, 4000);
}
