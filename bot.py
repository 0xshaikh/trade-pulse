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

# --- demo-trader publisher (reads the separate multi-asset demo bot's state) ---
DEMO_STATE = '/home/ubuntu/demo-trader/state'
DEMO_JSON = os.path.join(BASE, 'site', 'data', 'demo-trader.json')
REVIEW_JSON = os.path.join(BASE, 'site', 'data', 'review.json')

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
        subprocess.run(['git', 'add', 'site/data/trades.json', 'site/data/demo-trader.json', 'site/data/review.json'],
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


def build_demo_json():
    """Read the demo-trader bot's state files into a compact JSON for the site."""
    try:
        with open(os.path.join(DEMO_STATE, 'status.json')) as f:
            status = json.load(f)
    except Exception:
        return None
    positions = {}
    try:
        with open(os.path.join(DEMO_STATE, 'positions.json')) as f:
            positions = json.load(f).get('positions', {})
    except Exception:
        pass
    hist = []
    try:
        with open(os.path.join(DEMO_STATE, 'trades.csv')) as f:
            rows = f.read().strip().splitlines()
        for r in rows[1:][-60:]:
            p = r.split(',')
            if len(p) >= 7:
                hist.append({'ts': p[0], 'symbol': p[1], 'dir': int(p[2]),
                             'entry': float(p[3]), 'exit': float(p[4]),
                             'ret_pct': float(p[5]), 'equity': float(p[6])})
    except Exception:
        pass
    open_list = []
    for sym, p in positions.items():
        if p:
            open_list.append({'symbol': sym, 'dir': p.get('dir'), 'entry': p.get('entry'),
                             'sl': p.get('sl_price'), 'tp1': p.get('tp1'), 'tp2': p.get('tp2'),
                             'tp3': p.get('tp3'), 'qty': p.get('qty'),
                             'realized': p.get('realized'), 'opened': p.get('opened')})
    return {'equity': status.get('equity'), 'cash': status.get('cash'),
            'day_realized_pct': status.get('day_realized_pct'),
            'open': open_list, 'history': hist,
            'updated': int(time.time())}


_last_demo_mtime = None


def _lesson(row):
    """One-line lesson for a single journaled trade (evidence-backed, from the row)."""
    out = str(row.get('outcome', ''))
    r = str(row.get('exit_reason', ''))
    lvl = int(row.get('tp_level', 0) or 0)
    h = float(row.get('hold_hours', 0) or 0)
    if out == 'win':
        if lvl >= 3:
            return 'Full 3R run — let winners run, do not cut early.'
        if lvl >= 2:
            return 'Banked 2R — scaling out at TP2 works.'
        if lvl >= 1:
            return 'Banked 1R at TP1 — partial TP paid.'
        return 'Closed in profit — clean trend exit.'
    # loss attribution (mirrors demo-trader learning_summary)
    if r == 'SL hit' and lvl == 0 and h <= 4.5:
        return 'Chop — breakout had no follow-through, hit SL fast. Avoid flat-MA100 chop.'
    if r == 'SL hit' and lvl == 0:
        return 'Trend reversal after hold — regime filter too slow for this one.'
    if r == 'SL hit' and lvl >= 1:
        return 'Gave back profit — was in TP then reversed to SL. Tighten TP or trail.'
    if r == 'signal':
        return 'Signal exit at a loss — trend flipped, cut per rule.'
    return 'Exited at a loss — review setup validity.'


def build_review_json():
    """Aggregate the demo-trader journal into an actionable review (loss causes, lessons, avoid list)."""
    import csv as _csv
    jpath = os.path.join(DEMO_STATE, 'journal.csv')
    tpath = os.path.join(DEMO_STATE, 'trades.csv')
    try:
        with open(jpath) as f:
            j = list(_csv.DictReader(f))
    except Exception:
        j = []
    total_closed = 0
    try:
        with open(tpath) as f:
            total_closed = max(0, sum(1 for _ in f) - 1)
    except Exception:
        pass
    if not j:
        return {'n': 0, 'total_closed': total_closed}
    wins = [x for x in j if x.get('outcome') == 'win']
    losses = [x for x in j if x.get('outcome') == 'loss']
    n = len(j)
    gross_win = sum(float(x['r_total']) for x in wins)
    gross_loss = abs(sum(float(x['r_total']) for x in losses))
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0
    causes = {}
    for x in losses:
        c = _lesson(x)
        key = c.split('—')[0].strip()
        causes[key] = causes.get(key, 0) + 1
    causes = dict(sorted(causes.items(), key=lambda kv: -kv[1]))
    win_exits = {}
    for x in wins:
        r = str(x.get('exit_reason', '')); lvl = int(x.get('tp_level', 0) or 0)
        k = {'TP3 hit': 'TP3 full (3R)', 'TP2 hit': 'TP2 (2R)', 'TP1 hit': 'TP1 (1R)'}.get(r, '%s (lvl%d)' % (r, lvl))
        win_exits[k] = win_exits.get(k, 0) + 1
    win_exits = dict(sorted(win_exits.items(), key=lambda kv: -kv[1]))
    by_exit = {}
    for x in j:
        k = str(x.get('exit_reason', '?'))
        by_exit.setdefault(k, [0, 0.0])
        by_exit[k][0] += 1
        by_exit[k][1] += float(x['r_total'])
    by_asset = {}
    for x in j:
        k = str(x.get('symbol', '?'))
        by_asset.setdefault(k, [0, 0, 0.0])
        by_asset[k][0] += 1
        by_asset[k][1] += 1 if x.get('outcome') == 'win' else 0
        by_asset[k][2] += float(x['r_total'])
    by_dir = {}
    for x in j:
        k = 'SHORT' if str(x.get('dir')) == '-1' else 'LONG'
        by_dir.setdefault(k, [0, 0, 0.0])
        by_dir[k][0] += 1
        by_dir[k][1] += 1 if x.get('outcome') == 'win' else 0
        by_dir[k][2] += float(x['r_total'])
    avoid = []
    for k, (cnt, w, s) in sorted(by_asset.items(), key=lambda kv: kv[1][2]):
        if cnt >= 2 and s < -0.5:
            avoid.append('%s: %d/%d wins, %.2fR' % (k, w, cnt, s))
    for k, (cnt, w, s) in sorted(by_dir.items(), key=lambda kv: kv[1][2]):
        if cnt >= 3 and w / cnt < 0.34 and s < -0.3:
            avoid.append('%s side: %d/%d wins, %.2fR' % (k, w, cnt, s))
    recent = []
    for x in j[-12:]:
        recent.append({'ts': x.get('ts_close', ''), 'symbol': x.get('symbol'),
                       'dir': int(x.get('dir', 0) or 0), 'entry': float(x.get('entry', 0)),
                       'exit': float(x.get('exit', 0)), 'r': round(float(x.get('r_total', 0)), 2),
                       'outcome': x.get('outcome'), 'exit_reason': x.get('exit_reason'),
                       'tp_level': int(x.get('tp_level', 0) or 0), 'lesson': _lesson(x)})
    status = {}
    try:
        with open(os.path.join(DEMO_STATE, 'status.json')) as f:
            status = json.load(f)
    except Exception:
        pass
    return {'n': n, 'total_closed': total_closed, 'wins': len(wins), 'losses': len(losses),
            'winrate': round(len(wins) / n * 100, 1) if n else 0,
            'avg_r': round(sum(float(x['r_total']) for x in j) / n, 2),
            'pf': pf, 'equity': status.get('equity'),
            'causes': causes, 'win_exits': win_exits,
            'by_exit': {k: [v[0], round(v[1], 2)] for k, v in by_exit.items()},
            'by_asset': {k: [v[0], v[1], round(v[2], 2)] for k, v in by_asset.items()},
            'by_dir': {k: [v[0], v[1], round(v[2], 2)] for k, v in by_dir.items()},
            'avoid': avoid, 'recent': recent,
            'generated': int(time.time())}


def publish_demo():
    """Write demo-trader.json when the demo bot's state changes. Returns True if written."""
    global _last_demo_mtime
    try:
        mtimes = []
        for fn in ('status.json', 'positions.json', 'trades.csv'):
            mp = os.path.join(DEMO_STATE, fn)
            if os.path.exists(mp):
                mtimes.append(os.path.getmtime(mp))
        sig = max(mtimes) if mtimes else 0
    except Exception:
        return False
    if _last_demo_mtime is not None and sig <= _last_demo_mtime:
        return False
    data = build_demo_json()
    if data is None:
        return False
    os.makedirs(os.path.dirname(DEMO_JSON), exist_ok=True)
    tmp = DEMO_JSON + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, DEMO_JSON)
    review = build_review_json()
    rtmp = REVIEW_JSON + '.tmp'
    with open(rtmp, 'w') as f:
        json.dump(review, f, indent=1)
    os.replace(rtmp, REVIEW_JSON)
    _last_demo_mtime = sig
    print('  demo-trader published: equity=%s open=%d hist=%d review=%d' %
          (data.get('equity'), len(data['open']), len(data['history']), review.get('n', 0)))
    return True


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
        demo_changed = False
        try:
            demo_changed = publish_demo()
        except Exception as e:
            print('  demo publish error: %s' % e)
        if changed or demo_changed:
            if push():
                print('  pushed')
        time.sleep(POLL)


if __name__ == '__main__':
    main()
