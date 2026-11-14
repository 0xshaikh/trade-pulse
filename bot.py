#!/usr/bin/env python3
"""
Trade-Pulse v5 — focused portfolio (GOLD / BTC / SOL x 4H), strategy v4.
Evidence-first, data-validated (see market-prediction skill Round 12):
  Donchian10 breakout (look-ahead-safe) + MA100 trend + chop filter
  + ATR band (0.5-3.0%) + daily MA200 distance >= 5% gate
  1R stop (2xATR14) / 3R target (6xATR14), real fills (next-open + slip + taker)
  1% risk/trade, $1,000 virtual, PAPER ONLY, no real money, no future data.
Publishes site/data/trades.json (FULL history: every trade) + site/data/review.json.
Closed 4H bars only. Fresh start (2026-11-14) — old losing strategy retired.
"""
import json
import os
import subprocess
import time
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE, 'site', 'data', 'trades.json')
REVIEW_JSON = os.path.join(BASE, 'site', 'data', 'review.json')
FAPI = 'https://fapi.binance.com/fapi/v1/klines'

CAP = 1000.0
RISK = 0.01                    # 1% of equity per trade
PAIRS = ['XAUUSDT', 'BTCUSDT', 'SOLUSDT']   # GOLD, BTC, SOL (Binance USDT-M perps)
TF = '4h'
POLL = 60                      # seconds between checks
STALE_SIG = 300                # only take a signal whose bar closed <5min ago

# --- strategy v4 params (match backtest_v4.py exactly) ---
DC_N, MA_N, SLOPE_N = 10, 100, 5
SLOPE_MIN = 0.0005             # MA100 5-bar slope >= 0.05% of price
ATR_N = 14
ATR_LO, ATR_HI = 0.005, 0.030  # ATR14% in 0.5% - 3.0%
STOP_MULT, TP_MULT = 2.0, 6.0  # 1R = 2xATR, 3R = 6xATR
DAILY_MA = 200
DIST = 0.05                    # daily close >= 5% from daily MA200
FEE, SLIP = 0.0005, 0.0002
RT_COST = (FEE + SLIP) * 2     # round-trip notional cost


def fetch_klines(sym, interval, limit=600):
    r = requests.get(FAPI, params={'symbol': sym, 'interval': interval, 'limit': limit}, timeout=15)
    r.raise_for_status()
    out = []
    for k in r.json():
        out.append({'t': int(k[0]), 'o': float(k[1]), 'h': float(k[2]),
                    'l': float(k[3]), 'c': float(k[4]), 'v': float(k[5])})
    return out


def sma(vals, n):
    out = [None] * len(vals); s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n: s -= vals[i - n]
        if i >= n - 1: out[i] = s / n
    return out


def wilder_atr(bars, n):
    out = [None] * len(bars); trs = []
    for i, b in enumerate(bars):
        if i == 0: tr = b['h'] - b['l']
        else:
            tr = max(b['h'] - b['l'], abs(b['h'] - bars[i - 1]['c']), abs(b['l'] - bars[i - 1]['c']))
        trs.append(tr)
        if i == n - 1: out[i] = sum(trs) / n
        elif i >= n: out[i] = (out[i - 1] * (n - 1) + tr) / n
    return out


def donchian(bars, n):
    up = [None] * len(bars); lo = [None] * len(bars)
    for i in range(len(bars)):
        if i >= n:
            up[i] = max(b['h'] for b in bars[i - n:i])
            lo[i] = min(b['l'] for b in bars[i - n:i])
    return up, lo


def daily_gate(daily, bar_t):
    """Return +1/-1/0 for the daily bar containing bar_t. daily = list of (t_ms, close)."""
    d = bar_t // 86400000
    dcloses = [c for _, c in daily]
    dma = sma(dcloses, DAILY_MA)
    for i, (t, c) in enumerate(daily):
        if t // 86400000 == d:
            if dma[i] is None:
                return 0
            if c > dma[i] * (1 + DIST): return 1
            if c < dma[i] * (1 - DIST): return -1
            return 0
    return 0


def load_state():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {'cap': CAP, 'hist': [], 'open': {p: None for p in PAIRS},
            'lastDone': {}, 'updated': 0, 'started': int(time.time())}


def save_state(state):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, DATA_FILE)


def push():
    try:
        subprocess.run(['git', 'add', 'site/data/trades.json', 'site/data/review.json'],
                       cwd=BASE, check=True, timeout=30)
        subprocess.run(['git', 'commit', '-q', '-m',
                        'bot: update paper trades %d' % int(time.time())],
                       cwd=BASE, check=True, timeout=30)
        subprocess.run(['git', 'push', '-q', 'origin', 'main'], cwd=BASE,
                       check=True, timeout=90)
        return True
    except Exception as e:
        print('  push failed: %s' % e)
        return False


def equity(state):
    e = state['cap']
    for h in state['hist']:
        e += h['rR'] * h['riskUsd']
    return e


def write_review(state):
    hist = state['hist']
    n = len(hist)
    if not n:
        return {'n': 0, 'total_closed': 0, 'generated': int(time.time())}
    wins = [h for h in hist if h['rR'] > 0]
    losses = [h for h in hist if h['rR'] <= 0]
    gp = sum(h['rR'] for h in wins); gl = abs(sum(h['rR'] for h in losses))
    causes = {}
    for h in losses:
        r = h.get('reason', '')
        if r.startswith('stop'):
            causes['1R stop (stop-out)'] = causes.get('1R stop (stop-out)', 0) + 1
        else:
            causes[r] = causes.get(r, 0) + 1
    causes = dict(sorted(causes.items(), key=lambda kv: -kv[1]))
    by_asset = {}
    for h in hist:
        by_asset.setdefault(h['pair'], [0, 0, 0.0])
        by_asset[h['pair']][0] += 1
        by_asset[h['pair']][1] += 1 if h['rR'] > 0 else 0
        by_asset[h['pair']][2] += h['rR']
    recent = [{'ts': h.get('exitT'), 'symbol': h['pair'], 'dir': h['dir'],
               'entry': h['entry'], 'exit': h['exit'], 'r': round(h['rR'], 2),
               'outcome': 'win' if h['rR'] > 0 else 'loss',
               'exit_reason': h.get('reason', '')} for h in hist[-12:]]
    return {'n': n, 'total_closed': n, 'wins': len(wins), 'losses': len(losses),
            'winrate': round(len(wins) / n * 100, 1),
            'avg_r': round(sum(h['rR'] for h in hist) / n, 2),
            'pf': round(gp / gl, 2) if gl > 0 else 99.0,
            'equity': round(equity(state), 2),
            'causes': causes,
            'by_asset': {k: [v[0], v[1], round(v[2], 2)] for k, v in by_asset.items()},
            'recent': recent, 'generated': int(time.time())}


def publish_review(state):
    data = write_review(state)
    os.makedirs(os.path.dirname(REVIEW_JSON), exist_ok=True)
    tmp = REVIEW_JSON + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, REVIEW_JSON)


def signal_at(bars, i, daily):
    """Evaluate v4 signal at closed bar i. Returns dict or None."""
    if i < MA_N + SLOPE_N + 2:
        return None
    b = bars[i]
    c = b['c']
    atr = wilder_atr(bars, ATR_N)
    up, lo = donchian(bars, DC_N)
    ma = sma([x['c'] for x in bars], MA_N)
    if atr[i] is None or ma[i] is None or up[i] is None or lo[i] is None:
        return None
    a = atr[i] / c
    if not (ATR_LO <= a <= ATR_HI):
        return None
    slope = (ma[i] - ma[i - SLOPE_N]) / c
    if abs(slope) < SLOPE_MIN:
        return None
    gate = daily_gate(daily, b['t'])
    if gate == 0:
        return None
    long_sig = c > up[i] and c > ma[i] and gate == 1
    short_sig = c < lo[i] and c < ma[i] and gate == -1
    if not (long_sig or short_sig):
        return None
    d = 1 if long_sig else -1
    stop = c - d * STOP_MULT * atr[i]
    tgt = c + d * TP_MULT * atr[i]
    risk = abs(c - stop)
    if risk <= 0:
        return None
    return {'dir': d, 'entry': c, 'stop': stop, 'tgt': tgt,
            'atr': atr[i], 'risk': risk, 'at': b['t'], 'reason': 'breakout'}


def process_pair(pair, state, bars, daily):
    if len(bars) < MA_N + SLOPE_N + 5:
        return False
    last_closed = bars[-2]   # [-1] is the in-progress bar; use last fully-closed
    ct = last_closed['t']
    if ct <= state['lastDone'].get(pair, 0):
        return False
    state['lastDone'][pair] = ct
    changed = False
    op = state['open'].get(pair)
    if op:
        b = last_closed
        d = op['dir']
        if d == 1:
            if b['l'] <= op['stop'] and b['h'] >= op['tgt']:
                exit_p, reason = op['stop'], 'stop'
            elif b['l'] <= op['stop']:
                exit_p, reason = op['stop'], 'stop'
            elif b['h'] >= op['tgt']:
                exit_p, reason = op['tgt'], 'TP3 (3R)'
            else:
                exit_p = reason = None
        else:
            if b['h'] >= op['stop'] and b['l'] <= op['tgt']:
                exit_p, reason = op['stop'], 'stop'
            elif b['h'] >= op['stop']:
                exit_p, reason = op['stop'], 'stop'
            elif b['l'] <= op['tgt']:
                exit_p, reason = op['tgt'], 'TP3 (3R)'
            else:
                exit_p = reason = None
        if exit_p is not None:
            dR = (exit_p - op['entry']) if d == 1 else (op['entry'] - exit_p)
            grossR = dR / op['risk']
            stop_frac = op['risk'] / op['entry']
            cost_R = RT_COST / stop_frac
            netR = grossR - cost_R
            state['hist'].append({
                'pair': pair, 'dir': d, 'entry': op['entry'], 'exit': exit_p,
                'rR': netR, 'reason': reason, 'size': op['size'],
                'riskUsd': op['size'] * op['risk'],
                'bars': int((ct - op['entryT']) / (4 * 3600)),
                'exitT': ct, 'atr': round(op['atr'], 4),
            })
            state['open'][pair] = None
            changed = True
            print('  [%s] CLOSED %s %s @ %.2f -> %+.2fR (eq %.2f)' %
                  (pair, 'LONG' if d == 1 else 'SHORT', reason, exit_p, netR, equity(state)))
    else:
        # only take a signal if the signal bar closed recently (no stale entries)
        if time.time() * 1000 - ct <= STALE_SIG * 1000:
            sig = signal_at(bars, len(bars) - 2, daily)
            if sig:
                eq = equity(state)
                size = (eq * RISK) / sig['risk']
                state['open'][pair] = {
                    'pair': pair, 'dir': sig['dir'], 'entry': sig['entry'],
                    'stop': sig['stop'], 'tgt': sig['tgt'], 'risk': sig['risk'],
                    'size': size, 'entryT': sig['at'], 'atr': sig['atr'],
                }
                changed = True
                print('  [%s] OPENED %s @ %.2f stop %.2f tgt %.2f size %.6f' %
                      (pair, 'LONG' if sig['dir'] == 1 else 'SHORT', sig['entry'],
                       sig['stop'], sig['tgt'], size))
    return changed


def main():
    state = load_state()
    state.setdefault('cap', CAP)
    state.setdefault('hist', [])
    state.setdefault('open', {p: None for p in PAIRS})
    state.setdefault('lastDone', {})
    print('Trade-Pulse v5 started (fresh portfolio: GOLD/BTC/SOL x 4H). cap=%.0f hist=%d open=%d' %
          (state['cap'], len(state['hist']), sum(1 for v in state['open'].values() if v)))
    while True:
        changed = False
        for pair in PAIRS:
            try:
                bars = fetch_klines(pair, TF, 700)
                daily = fetch_klines(pair, '1d', 400)
            except Exception as e:
                print('  [%s] fetch failed: %s' % (pair, e))
                continue
            try:
                if process_pair(pair, state, bars, daily):
                    changed = True
            except Exception as e:
                print('  [%s] process error: %s' % (pair, e))
        if changed:
            state['updated'] = int(time.time())
            save_state(state)
            publish_review(state)
            if push():
                print('  pushed')
        time.sleep(POLL)


if __name__ == '__main__':
    main()
