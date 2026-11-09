#!/usr/bin/env python3
"""
Trade-Pulse Auto-Bot
Runs the SAME trendline strategy the trade-pulse site displays (4H trendline bias + 15M
execution, XAUUSDT + BTCUSDT), on CLOSED 15M candles. Paper trading ONLY: $1,000 virtual,
1% risk per trade, no real money, no future data. Publishes to site/data/trades.json
which the site fetches, so trades show on every device.

Mirrors the site's strategy exactly (FEE/SLIP/ROUND_TRIP, K=3, TOL=0.25, ATR14,
swing-lows/highs, 4H trendline value, 1:2 & 1:15 targets, stop>TP2>TP1 close priority).
"""
import json
import os
import subprocess
import time

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE, 'site', 'data', 'trades.json')

FEE = 0.0005
SLIP = 0.0002
ROUND_TRIP = (FEE + SLIP) * 2
K = 3
TOL = 0.25
CAP = 1000.0
PAIRS = ['XAUUSDT', 'BTCUSDT']
BINANCE = 'https://fapi.binance.com/fapi/v1/klines'
POLL = 60  # seconds between checks


def fetch_klines(sym, interval, limit=400):
    r = requests.get(BINANCE, params={'symbol': sym, 'interval': interval, 'limit': limit}, timeout=15)
    r.raise_for_status()
    out = []
    for k in r.json():
        out.append({'t': int(k[0]), 'o': float(k[1]), 'h': float(k[2]),
                    'l': float(k[3]), 'c': float(k[4]), 'v': float(k[5])})
    return out


def atr15(bars, i, n=14):
    if i < n:
        return None
    s = 0.0
    for j in range(i - n, i):
        b = bars[j]
        p = bars[j - 1]
        tr = max(b['h'] - b['l'], abs(b['h'] - p['c']), abs(b['l'] - p['c']))
        s += tr
    return s / n


def swing_lows(b, k):
    o = []
    for i in range(k, len(b) - k):
        lo = b[i]['l']
        ok = True
        for j in range(i - k, i + k + 1):
            if j != i and b[j]['l'] < lo:
                ok = False
                break
        if ok:
            o.append(i)
    return o


def swing_highs(b, k):
    o = []
    for i in range(k, len(b) - k):
        hi = b[i]['h']
        ok = True
        for j in range(i - k, i + k + 1):
            if j != i and b[j]['h'] > hi:
                ok = False
                break
        if ok:
            o.append(i)
    return o


def tl_from(b, k, t, dirn):
    sw = swing_lows(b, k) if dirn == 'low' else swing_highs(b, k)
    conf = []
    for i in sw:
        if i + k < len(b) and b[i + k]['t'] <= t:
            conf.append(i)
    if len(conf) < 2:
        return None
    i1 = conf[-2]
    i2 = conf[-1]
    p1 = b[i1]['l'] if dirn == 'low' else b[i1]['h']
    p2 = b[i2]['l'] if dirn == 'low' else b[i2]['h']
    if dirn == 'low' and not (p2 > p1):
        return None
    if dirn == 'high' and not (p2 < p1):
        return None
    return {'p1': p1, 't1': b[i1]['t'], 'p2': p2, 't2': b[i2]['t']}


def tl_val(tl, t):
    if t <= tl['t2']:
        return tl['p2']
    sl = (tl['p2'] - tl['p1']) / (tl['t2'] - tl['t1'])
    return tl['p2'] + sl * (t - tl['t2'])


def last_signal(bars15, bars4h, idx):
    if len(bars15) < 300 or len(bars4h) < 10:
        return None
    if idx < 0 or idx >= len(bars15):
        return None
    b = bars15[idx]
    t = b['t']
    a = atr15(bars15, idx)
    if not a or a <= 0:
        return None
    tol = TOL * a
    tl = tl_from(bars4h, K, t, 'low')
    if tl:
        tv = tl_val(tl, t)
        if b['l'] <= tv + tol and b['c'] > tv and b['c'] > b['o']:
            entry = b['c']
            stop = min(b['l'] - 0.25 * a, tl['p2'] - 0.5 * a)
            risk = entry - stop
            if risk > 0:
                return {'dir': 'long', 'zone': tv, 'entry': entry, 'stop': stop,
                        'tp1': entry + 2 * risk, 'tp2': entry + 15 * risk, 'risk': risk, 'at': t}
    tl = tl_from(bars4h, K, t, 'high')
    if tl:
        tv2 = tl_val(tl, t)
        if b['h'] >= tv2 - tol and b['c'] < tv2 and b['c'] < b['o']:
            entry2 = b['c']
            stop2 = max(b['h'] + 0.25 * a, tl['p2'] + 0.5 * a)
            risk2 = stop2 - entry2
            if risk2 > 0:
                return {'dir': 'short', 'zone': tv2, 'entry': entry2, 'stop': stop2,
                        'tp1': entry2 - 2 * risk2, 'tp2': entry2 - 15 * risk2, 'risk': risk2, 'at': t}
    return None


def load_state():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {'cap': CAP, 'hist': [], 'open': {p: None for p in PAIRS},
            'lastDone': {}, 'updated': 0}


def save_state(state):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, DATA_FILE)


def push():
    try:
        subprocess.run(['git', 'add', 'site/data/trades.json'], cwd=BASE,
                       check=True, timeout=30)
        subprocess.run(['git', 'commit', '-q', '-m',
                        'bot: update paper trades %d' % int(time.time())],
                       cwd=BASE, check=True, timeout=30)
        subprocess.run(['git', 'push', '-q', 'origin', 'main'], cwd=BASE,
                       check=True, timeout=90)
        return True
    except Exception as e:
        print('  push failed: %s' % e)
        return False


def current_equity(state):
    e = state['cap']
    for h in state['hist']:
        e += h['rR'] * h['riskUsd']
    return e


def process_pair(pair, state, bars15, bars4h):
    if len(bars15) < 300 or len(bars4h) < 10:
        return False
    last_closed = bars15[-2]  # last fully-closed 15M candle ([-1] is still forming)
    ct = last_closed['t']
    if ct <= state['lastDone'].get(pair, 0):
        return False  # already processed this candle
    state['lastDone'][pair] = ct
    changed = False
    op = state['open'].get(pair)
    if op:
        b = last_closed
        if op['dir'] == 'long':
            if b['l'] <= op['stop']:
                close = ('stop', op['stop'])
            elif b['h'] >= op['tp2']:
                close = ('TP2 (15R)', op['tp2'])
            elif b['h'] >= op['tp1']:
                close = ('TP1 (2R)', op['tp1'])
            else:
                close = None
        else:
            if b['h'] >= op['stop']:
                close = ('stop', op['stop'])
            elif b['l'] <= op['tp2']:
                close = ('TP2 (15R)', op['tp2'])
            elif b['l'] <= op['tp1']:
                close = ('TP1 (2R)', op['tp1'])
            else:
                close = None
        if close:
            reason, exit_p = close
            d = (exit_p - op['entry']) if op['dir'] == 'long' else (op['entry'] - exit_p)
            rR = d / op['risk']
            feesR = ROUND_TRIP * op['entry'] / op['risk']
            netR = rR - feesR
            state['hist'].append({
                'pair': pair, 'dir': op['dir'], 'entry': op['entry'], 'exit': exit_p,
                'rR': netR, 'reason': reason, 'size': op['size'],
                'riskUsd': op['size'] * op['risk'],
                'bars': int((ct - op['entryT']) / (15 * 60)),
                'exitT': ct,
            })
            state['open'][pair] = None
            changed = True
            print('  [%s] CLOSED %s %s @ %.2f -> %+.2fR' % (pair, op['dir'], reason, exit_p, netR))
    else:
        sig = last_signal(bars15, bars4h, len(bars15) - 2)
        if sig:
            eq = current_equity(state)
            size = (eq * 0.01) / sig['risk']
            state['open'][pair] = {
                'pair': pair, 'dir': sig['dir'], 'entry': sig['entry'], 'stop': sig['stop'],
                'tp1': sig['tp1'], 'tp2': sig['tp2'], 'risk': sig['risk'], 'size': size,
                'entryT': sig['at'], 'zone': sig['zone'],
            }
            changed = True
            print('  [%s] OPENED %s @ %.2f stop %.2f tp1 %.2f tp2 %.2f size %.6f' %
                  (pair, sig['dir'], sig['entry'], sig['stop'], sig['tp1'], sig['tp2'], size))
    return changed


def main():
    state = load_state()
    state.setdefault('cap', CAP)
    state.setdefault('hist', [])
    state.setdefault('open', {p: None for p in PAIRS})
    state.setdefault('lastDone', {})
    print('Trade-Pulse bot started. cap=%s hist=%d open=%d' %
          (state['cap'], len(state['hist']),
           sum(1 for v in state['open'].values() if v)))
    while True:
        changed = False
        for pair in PAIRS:
            try:
                bars15 = fetch_klines(pair, '15m', 300)
                bars4h = fetch_klines(pair, '4h', 300)
            except Exception as e:
                print('  [%s] fetch failed: %s' % (pair, e))
                continue
            try:
                if process_pair(pair, state, bars15, bars4h):
                    changed = True
            except Exception as e:
                print('  [%s] process error: %s' % (pair, e))
        if changed:
            state['updated'] = int(time.time())
            save_state(state)
            if push():
                print('  pushed')
        time.sleep(POLL)


if __name__ == '__main__':
    main()
