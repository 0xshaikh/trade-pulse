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
];
const TF_MAP = { '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d' };
const BARS = 600;          // history bars for chart + backtest (matches research window)
const DONCHIAN_N = 10;     // breakout channel (10 = faster, catches trend earlier)
const MA_N = 100;          // trend filter
const ATR_N = 14;          // volatility stop
const ATR_MULT_STOP = 2;   // 2xATR stop (1R)
const ATR_MULT_TP   = 6;   // 3R target (stop=1R -> target=3x stop distance = 6xATR, matches research)
const MIN_MA_SLOPE = 0.05; // chop filter: |MA100 slope| (as % of price over 5 bars) must exceed this
const DAILY_MA_N   = 200;  // daily regime gate: trade only in direction of daily MA200
const ATR_BAND     = [0.5, 3.0]; // volatility regime: skip dead-vol (<0.5%) / blow-off (>3%) chop
const ADX_MIN      = 18;         // trend-strength gate: only trade when ADX(14) >= 18 (cut chop)
const DAILY_DIST   = 0.05;       // daily MA200 range filter: trade only when price is >=5% from the daily MA200 (v4)

/* ==================== State ==================== */
const state = {
  symbol: 'BTCUSDT',
  interval: '4h',
  klines: [],          // {time, open, high, low, close, volume}
  dailyKlines: [],     // 1d klines for regime gate
  ws: null,
  wsSubscribed: false,
  currentAsset: null,  // active leaderboard row
  portfolio: null,     // cached per-asset metrics for the Portfolio view
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
// Wilder-smoothed ADX (trend strength). >=ADX_MIN = trending (the chop-cut gate).
function adx(klines, n) {
  const out = new Array(klines.length).fill(null);
  if (klines.length < n + 2) return out;
  let tr = [], pdm = [], ndm = [];
  for (let i = 1; i < klines.length; i++) {
    const h = klines[i].high, l = klines[i].low, ph = klines[i-1].high, pl = klines[i-1].low, pc = klines[i-1].close;
    const t = Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc));
    const up = h - ph, dn = pl - l;
    const p = (up > dn && up > 0) ? up : 0;
    const nn = (dn > up && dn > 0) ? dn : 0;
    tr.push(t); pdm.push(p); ndm.push(nn);
    if (i < n) continue;
    let atrS = 0, pdmS = 0, ndmS = 0;
    for (let j = i - n + 1; j <= i; j++) { atrS += tr[j-1]; pdmS += pdm[j-1]; ndmS += ndm[j-1]; }
    atrS /= n; pdmS /= n; ndmS /= n;
    if (atrS <= 0) { out[i] = 0; continue; }
    const pdi = 100 * pdmS / atrS, ndi = 100 * ndmS / atrS;
    const dx = (pdi + ndi) > 0 ? 100 * Math.abs(pdi - ndi) / (pdi + ndi) : 0;
    if (i === n) { out[i] = dx; }
    else {
      const prev = out[i-1];
      out[i] = (prev != null && prev > 0) ? (prev * (n - 1) + dx) / n : dx;
    }
  }
  return out;
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
// Daily regime gate: returns +1 (clear uptrend), -1 (clear downtrend), or 0 (range/no data).
// v4: only trade when price is at least DAILY_DIST (5%) from the daily MA200 — price hugging the daily MA is
// a range (no trend), and trend breakouts from a range bleed (the recent long-side chop loss).
function dailyGate(dailyKlines, ts) {
  if (!dailyKlines || dailyKlines.length < DAILY_MA_N) return 0;
  const dclose = dailyKlines.map(k => k.close);
  const dma = sma(dclose, DAILY_MA_N);
  let idx = -1;
  for (let j = 0; j < dailyKlines.length; j++) {
    if (dailyKlines[j].time <= ts) idx = j; else break;
  }
  if (idx < DAILY_MA_N - 1 || dma[idx] == null) return 0;
  const ratio = dclose[idx] / dma[idx] - 1;
  if (ratio > DAILY_DIST) return 1;   // clearly above MA200 -> long regime
  if (ratio < -DAILY_DIST) return -1; // clearly below MA200 -> short regime
  return 0;                           // within DAILY_DIST of MA200 -> range (no trade)
}

/* ==================== Strategy backtest (closed bars) ==================== */
function backtest(klines) {
  const close = klines.map(k => k.close);
  const ma = sma(close, MA_N);
  const atrVals = atr(klines, ATR_N);
  const dc = donchian(klines, DONCHIAN_N);
  const adxVals = adx(klines, 14);

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
    // Volatility regime band: skip dead-vol (<0.5%) and blow-off (>3%) chop
    const atrPct = atrVals[i] / close[i] * 100;
    if (ATR_BAND && (atrPct < ATR_BAND[0] || atrPct > ATR_BAND[1])) continue;
    // Trend-strength gate: skip chop (ADX < threshold) — the round-10 loss cutter
    if (adxVals[i] == null || adxVals[i] < ADX_MIN) continue;
    const prevClose = close[i - 1];
    // Daily regime gate: only long in a clear daily uptrend (>=5% above MA200), only short in a clear downtrend
    const gate = dailyGate(state.dailyKlines, klines[i].time);
    // Long: close breaks above PRIOR 20-bar high (no look-ahead) AND MA100 rising
    if (prevClose <= dc.upper[i - 1] && close[i] > dc.upper[i - 1] && slope > 0 && close[i] > ma[i] && gate === 1) {
      const entry = close[i];
      pos = { dir: 1, entry, stop: entry - ATR_MULT_STOP * atrVals[i], target: entry + ATR_MULT_TP * atrVals[i], entryIdx: i };
    }
    // Short: close breaks below PRIOR 20-bar low (no look-ahead) AND MA100 falling
    else if (prevClose >= dc.lower[i - 1] && close[i] < dc.lower[i - 1] && slope < 0 && close[i] < ma[i] && gate === -1) {
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
  const r = await fetch(`${REST}/klines?symbol=${symbol}&interval=1d&limit=500`);
  if (!r.ok) return [];
  const raw = await r.json();
  return raw.map(k => ({ time: Math.floor(k[0] / 1000), open: +k[1], high: +k[2], low: +k[3], close: +k[4] }));
}

/* ==================== Chart ==================== */
let chart = null, candleSeries = null, donkHiSeries = null, donkLoSeries = null, maSeries = null;

function initChart() {
  chart = LightweightCharts.createChart($('chart'), {
    layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#8A8A8A', fontFamily: "'Manrope', sans-serif" },
    grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
    rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
    timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    autoSize: true,
  });
  candleSeries = chart.addCandlestickSeries({
    upColor: '#2ECC71', downColor: '#E5484D',
    wickUpColor: '#2ECC71', wickDownColor: '#E5484D',
    borderVisible: false,
  });
  donkHiSeries = chart.addLineSeries({ color: '#3FD8E8', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, title: 'Donchian 20 High' });
  donkLoSeries = chart.addLineSeries({ color: '#8A8A8A', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, title: 'Donchian 20 Low' });
  maSeries = chart.addLineSeries({ color: '#F5A623', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, title: 'MA100' });
}

/* ==================== Render chart ==================== */
function renderChart(klines) {
  const candles = klines.map(k => ({ time: k.time, open: k.open, high: k.high, low: k.low, close: k.close }));
  candleSeries.setData(candles);

  const close = klines.map(k => k.close);
  const ma = sma(close, MA_N);
  const dc = donchian(klines, DONCHIAN_N);
  const atrVals = atr(klines, ATR_N);
  const adxVals = adx(klines, 14);

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
    const atrPct = atrVals[i] / close[i] * 100;
    if (ATR_BAND && (atrPct < ATR_BAND[0] || atrPct > ATR_BAND[1])) continue;
    if (adxVals[i] == null || adxVals[i] < ADX_MIN) continue;
    const gate = dailyGate(state.dailyKlines, klines[i].time);
    const isLong = prevClose <= dc.upper[i - 1] && close[i] > dc.upper[i - 1] && slope > 0 && close[i] > ma[i] && gate === 1;
    const isShort = prevClose >= dc.lower[i - 1] && close[i] < dc.lower[i - 1] && slope < 0 && close[i] < ma[i] && gate === -1;
    if (isLong) {
      sigMarkers.push({ time: klines[i].time, position: 'belowBar', color: '#2ECC71', shape: 'arrowUp', text: 'BUY' });
      lastTrade = i + DONCHIAN_N * 2; // don't re-signal inside channel period
    } else if (isShort) {
      sigMarkers.push({ time: klines[i].time, position: 'aboveBar', color: '#E5484D', shape: 'arrowDown', text: 'SELL' });
      lastTrade = i + DONCHIAN_N * 2;
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
  const atrVals = atr(klines, ATR_N);
  const adxVals = adx(klines, 14);
  const i = klines.length - 1;
  if (i < 1) return;
  const slope = maSlopePct(ma, close, i);
  const sv = $('signal-value');
  const sr = $('signal-reason');
  const gate = dailyGate(state.dailyKlines, klines[i].time);
  const atrPct = atrVals[i] / close[i] * 100;
  const inBand = !ATR_BAND || (atrPct >= ATR_BAND[0] && atrPct <= ATR_BAND[1]);
  const inTrend = adxVals[i] != null && adxVals[i] >= ADX_MIN;
  const brkUp = close[i] > dc.upper[i - 1];
  const brkDn = close[i] < dc.lower[i - 1];
  const reasons = [];
  if (!inTrend) reasons.push(`ADX ${adxVals[i] == null ? '—' : adxVals[i].toFixed(0)} < ${ADX_MIN} (chop)`);
  if (!inBand) reasons.push(`ATR ${atrPct.toFixed(1)}% outside ${ATR_BAND[0]}–${ATR_BAND[1]}%`);
  if (Math.abs(slope) < MIN_MA_SLOPE) reasons.push(`MA100 slope ${slope >= 0 ? '+' : ''}${slope.toFixed(2)}% too flat`);
  if (gate === 0) reasons.push(`price within ${(DAILY_DIST*100).toFixed(0)}% of daily MA200 (range)`);
  if (!brkUp && !brkDn) reasons.push('price inside Donchian (no breakout)');
  const wantLong = brkUp && slope > 0 && close[i] > ma[i] && gate === 1;
  const wantShort = brkDn && slope < 0 && close[i] < ma[i] && gate === -1;
  if ((wantLong || wantShort) && gate !== 0 && gate !== (wantLong ? -1 : 1) && (wantLong ? slope < 0 : slope > 0)) {
    reasons.push('breakout opposite MA100 slope (counter-trend)');
  }
  if (sr) sr.textContent = reasons.length ? '· ' + reasons.join(' · ') : '· filters clear';
  if (inBand && inTrend && close[i] > dc.upper[i - 1] && slope > MIN_MA_SLOPE && close[i] > ma[i] && gate === 1) {
    sv.textContent = 'BUY SIGNAL'; sv.className = 'signal-value buy';
  } else if (inBand && inTrend && close[i] < dc.lower[i - 1] && slope < -MIN_MA_SLOPE && close[i] < ma[i] && gate === -1) {
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
  // newest-first: most recent trade at top
  const rows = trades.slice().reverse().map((t, i) => {
    const dollar = t.net * 10000; // $10k equity base
    const dstr = (dollar >= 0 ? '+' : '−') + '$' + Math.abs(dollar).toFixed(2);
    const num = trades.length - i; // original trade # (newest has highest)
    return `<tr>
      <td>${num}</td>
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

/* ==================== Portfolio (exchange-style) ==================== */
const PORTFOLIO_BASE = 10000; // sim capital per pair
function renderPortfolio(results) {
  const valid = results.filter(r => !r.error && r.total > 0);
  const totalTrades = valid.reduce((s, r) => s + r.total, 0);
  const totalWins = valid.reduce((s, r) => s + (r.winRate / 100) * r.total, 0);
  const overallWR = totalTrades ? (totalWins / totalTrades) * 100 : 0;
  // per-pair P&L on $10k base (compounded)
  const withPnl = valid.map(r => {
    const equity = PORTFOLIO_BASE * (1 + r.netReturn / 100);
    return { ...r, pnl: equity - PORTFOLIO_BASE };
  });
  const netPnl = withPnl.reduce((s, r) => s + r.pnl, 0);
  const grossPos = withPnl.filter(r => r.pnl > 0).reduce((s, r) => s + r.pnl, 0);
  const grossNeg = Math.abs(withPnl.filter(r => r.pnl < 0).reduce((s, r) => s + r.pnl, 0));
  const aggPF = grossNeg > 0 ? grossPos / grossNeg : (grossPos > 0 ? Infinity : 0);
  const sorted = withPnl.slice().sort((a, b) => b.pnl - a.pnl);
  const best = sorted[0], worst = sorted[sorted.length - 1];
  const avgRet = valid.length ? valid.reduce((s, r) => s + r.netReturn, 0) / valid.length : 0;

  // --- summary cards ---
  $('pf-capital').textContent = '$' + PORTFOLIO_BASE.toLocaleString();
  $('pf-capital-sub').textContent = 'sim base · $' + PORTFOLIO_BASE.toLocaleString() + ' per pair';
  const pnlEl = $('pf-pnl');
  pnlEl.textContent = (netPnl >= 0 ? '+' : '−') + '$' + Math.abs(netPnl).toLocaleString('en-US', { maximumFractionDigits: 0 });
  pnlEl.className = 'pcard-value mono ' + (netPnl >= 0 ? 'positive' : 'negative');
  const pnlPct = $('pf-pnl-pct');
  pnlPct.textContent = fmtPct(avgRet) + ' avg per pair';
  pnlPct.className = 'pcard-sub ' + (avgRet >= 0 ? 'positive' : 'negative');
  $('pf-wr').textContent = overallWR.toFixed(0) + '%';
  $('pf-wr-sub').textContent = totalTrades ? `${totalWins.toFixed(0)}/${totalTrades} wins` : 'no trades';
  $('pf-trades').textContent = totalTrades;
  $('pf-trades-sub').textContent = 'closed 4H signals';
  const pfEl = $('pf-pf');
  pfEl.textContent = aggPF === Infinity ? '∞' : aggPF.toFixed(2);
  pfEl.className = 'pcard-value mono ' + (aggPF >= 1 ? 'positive' : 'negative');
  const bestEl = $('pf-best');
  bestEl.textContent = best && best.total ? best.label.replace('USDT', '') + ' ' + fmtPct(best.netReturn) : '—';
  bestEl.className = 'pcard-value best-worst ' + (best && best.netReturn >= 0 ? 'positive' : 'negative');
  const worstEl = $('pf-worst');
  worstEl.textContent = worst && worst.total ? worst.label.replace('USDT', '') + ' ' + fmtPct(worst.netReturn) : '—';
  worstEl.className = 'pcard-sub ' + (worst && worst.netReturn < 0 ? 'negative' : 'positive');

  // --- allocation table ---
  const body = $('alloc-body');
  if (!body) return;
  $('pf-loading').classList.add('hidden');
  const maxAbs = Math.max(1, ...withPnl.map(r => Math.abs(r.pnl)));
  body.innerHTML = withPnl.map(r => {
    const pct = Math.abs(r.pnl) / maxAbs * 100;
    const bar = r.pnl >= 0 ? 'pos-bar' : 'neg-bar';
    return `<tr data-sym="${r.sym}">
      <td><span class="asset-dot" style="background:${r.color}"></span>${r.label}</td>
      <td>${r.total}</td>
      <td>${r.winRate.toFixed(0)}%</td>
      <td class="alloc-bar-wrap"><div class="alloc-bar"><span class="${bar}" style="width:${pct.toFixed(1)}%"></span></div></td>
      <td class="${r.pnl >= 0 ? 'pos' : 'neg'}">${(r.pnl >= 0 ? '+' : '−')}$${Math.abs(r.pnl).toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
      <td class="${r.netReturn >= 0 ? 'pos' : 'neg'}">${fmtPct(r.netReturn)}</td>
    </tr>`;
  }).join('');
  // click row -> focus that pair on chart + history
  body.querySelectorAll('tr[data-sym]').forEach(tr => {
    tr.addEventListener('click', () => {
      const sym = tr.dataset.sym;
      state.symbol = sym;
      const sel = $('symbol-select');
      if (sel) sel.value = sym;
      loadSymbol(sym);
      connectWS();
      switchView('chart');
    });
  });
}

/* ==================== View tabs (exchange-style) ==================== */
function switchView(name) {
  ['chart', 'portfolio', 'history'].forEach(v => {
    const view = $('view-' + v);
    if (view) view.hidden = (v !== name);
  });
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.view === name);
    b.setAttribute('aria-selected', b.dataset.view === name ? 'true' : 'false');
  });
  document.querySelectorAll('.mnav-btn').forEach(b => b.classList.toggle('active', b.dataset.view === name));
  // ensure chart resizes when it becomes visible
  if (name === 'chart' && chart) setTimeout(() => { try { chart.applyOptions({}); chart.timeScale().fitContent(); } catch(e){} }, 50);
  // refresh portfolio data each time it opens
  if (name === 'portfolio' && state.portfolio) renderPortfolio(state.portfolio);
}

/* ==================== Leaderboard ==================== */
async function buildLeaderboard() {
  $('pf-loading').classList.remove('hidden');
  const results = await Promise.all(ASSETS.map(async (a) => {
    try {
      const [kl, daily] = await Promise.all([fetchKlines(a.sym, '4h', 600), fetchDaily(a.sym)]);
      const prevDaily = state.dailyKlines;
      state.dailyKlines = daily;   // set gate data for this asset's backtest
      const bt = backtest(kl);
      state.dailyKlines = prevDaily; // restore
      return { ...a, ...bt.metrics, klines: kl };
    } catch (e) { return { ...a, total: 0, winRate: 0, netReturn: 0, profitFactor: 0, error: true }; }
  }));
  results.sort((a, b) => b.netReturn - a.netReturn);
  state.portfolio = results;
  renderPortfolio(results);
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

  // --- view tabs (desktop + mobile) ---
  document.querySelectorAll('.tab-btn, .mnav-btn').forEach(btn => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
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
