#!/usr/bin/env python3
"""HTF trendline + 15M entry strategy backtest.
User request: find trades via 1H/4H trendlines, execute on 15M, R:R 1:2 and 1:15.
Symbols: BTCUSDT + XAUUSDT futures. Realistic fees (taker 0.05%/side + slip 0.02%/side).
Honest evaluation: report WR, PF, netR, count for each config.
"""
import json, math

# ---- engine constants (matches prior rounds) ----
TAKER = 0.0005   # per side
SLIP  = 0.0002   # per side
ROUND_TRIP = (TAKER + SLIP) * 2  # 0.14% of notional

def load(sym, tf):
    return json.load(open(f"/home/ubuntu/trade-pulse/research/{sym}_{tf}.json"))

def atr(bars, i, n=14):
    if i < n: return None
    trs = []
    for j in range(i - n, i):
        h, l, pc = bars[j]['high'], bars[j]['low'], bars[j-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n

def swing_lows(bars, k):
    """Indices of swing lows: low[i] is min over [i-k, i+k]."""
    out = []
    for i in range(k, len(bars) - k):
        lo = bars[i]['low']
        if all(lo < bars[j]['low'] for j in range(i - k, i + k + 1) if j != i):
            out.append(i)
    return out

def swing_highs(bars, k):
    out = []
    for i in range(k, len(bars) - k):
        hi = bars[i]['high']
        if all(hi > bars[j]['high'] for j in range(i - k, i + k + 1) if j != i):
            out.append(i)
    return out

def htf_trendline(bars, k, t, dirn):
    """Return (confirmed) trendline info at 15m time t.
    dirn='low' for uptrend support line (thru 2 swing lows),
          'high' for downtrend resistance line (thru 2 swing highs).
    Returns dict with p1,t1,p2,t2 (confirmed swing points) or None.
    A swing point at bar idx is confirmed only at time bars[idx+k]['time'].
    """
    sw = swing_lows(bars, k) if dirn == 'low' else swing_highs(bars, k)
    # confirmed swings: those with confirm time <= t
    conf = [i for i in sw if i + k < len(bars) and bars[i + k]['time'] <= t]
    if len(conf) < 2:
        return None
    i1, i2 = conf[-2], conf[-1]
    t1, t2 = bars[i1]['time'], bars[i2]['time']
    p1 = bars[i1]['low'] if dirn == 'low' else bars[i1]['high']
    p2 = bars[i2]['low'] if dirn == 'low' else bars[i2]['high']
    # validity: uptrend support needs rising lows; downtrend resistance needs falling highs
    if dirn == 'low' and not (p2 > p1): return None
    if dirn == 'high' and not (p2 < p1): return None
    return dict(p1=p1, t1=t1, p2=p2, t2=t2)

def tl_value(tl, t):
    if t <= tl['t2']: return tl['p2']
    slope = (tl['p2'] - tl['p1']) / (tl['t2'] - tl['t1'])
    return tl['p2'] + slope * (t - tl['t2'])

def backtest(sym, htf, k=2, tol_atr=0.5, tp1_r=2.0, tp2_r=15.0, scale1=0.5, risk_atr=1.5):
    bars15 = load(sym, "15m_deep")
    bars_htf = load(sym, htf)
    if not bars15 or not bars_htf:
        return None
    trades = []
    open_tr = None
    start_i = 300  # warmup
    for i in range(start_i, len(bars15)):
        b = bars15[i]
        t = b['time']
        a = atr(bars15, i)
        if a is None or a <= 0:
            continue
        # manage open trade
        if open_tr:
            tr = open_tr
            hit = False
            # check high/low within bar
            if tr['dir'] == 'long':
                if b['low'] <= tr['sl']:
                    # stop hit first (conservative: if both in same bar, stop wins)
                    r = -1.0; hit = True
                elif b['high'] >= tr['tp2']:
                    r = tp2_r; hit = True
                elif b['high'] >= tr['tp1']:
                    r = tp1_r; hit = True
            else:
                if b['high'] >= tr['sl']:
                    r = -1.0; hit = True
                elif b['low'] <= tr['tp2']:
                    r = tp2_r; hit = True
                elif b['low'] <= tr['tp1']:
                    r = tp1_r; hit = True
            if hit:
                fees_r = ROUND_TRIP * tr['entry'] / tr['risk']
                tr['r'] = r - fees_r
                tr['exit_t'] = t
                tr['bars'] = (t - tr['entry_t']) / (15 * 60)
                trades.append(tr)
                open_tr = None
            continue
        # generate signal
        dirn = 'low'
        tl = htf_trendline(bars_htf, k, t, 'low')
        if tl:
            tlv = tl_value(tl, t)
            tol = tol_atr * a
            # uptrend: price dips to touch support line then closes above it
            if b['low'] <= tlv + tol and b['close'] > tlv and b['close'] > b['open']:
                entry = b['close']
                stop = min(b['low'] - 0.25 * a, tl['p2'] - 0.5 * a)
                risk = entry - stop
                if risk > 0:
                    open_tr = dict(dir='long', entry=entry, sl=stop, risk=risk,
                                   tp1=entry + tp1_r * risk, tp2=entry + tp2_r * risk,
                                   entry_t=t)
                    continue
        dirn = 'high'
        tl = htf_trendline(bars_htf, k, t, 'high')
        if tl:
            tlv = tl_value(tl, t)
            tol = tol_atr * a
            if b['high'] >= tlv - tol and b['close'] < tlv and b['close'] < b['open']:
                entry = b['close']
                stop = max(b['high'] + 0.25 * a, tl['p2'] + 0.5 * a)
                risk = stop - entry
                if risk > 0:
                    open_tr = dict(dir='short', entry=entry, sl=stop, risk=risk,
                                   tp1=entry - tp1_r * risk, tp2=entry - tp2_r * risk,
                                   entry_t=t)
    if open_tr:
        open_tr['r'] = 0.0
        open_tr['open'] = True
        trades.append(open_tr)
    if not trades:
        return dict(n=0)
    closed = [x for x in trades if 'r' in x and not x.get('open')]
    n = len(closed)
    if n == 0:
        return dict(n=0)
    wins = [x for x in closed if x['r'] > 0]
    wr = len(wins) / n
    netR = sum(x['r'] for x in closed)
    gross_w = sum(x['r'] for x in wins)
    gross_l = -sum(x['r'] for x in closed if x['r'] <= 0)
    pf = gross_w / gross_l if gross_l > 0 else float('inf')
    avg = netR / n
    # how many hit tp2 (the big runner)?
    tp2_hits = sum(1 for x in closed if (x['dir']=='long' and x['tp2'] <= max(bars15[j]['high'] for j in range(len(bars15))) ) )
    return dict(n=n, wr=wr, netR=round(netR,1), pf=round(pf,2), avg=round(avg,2),
                avg_bars=round(sum(x['bars'] for x in closed)/n,1),
                tp2_count=sum(1 for x in closed if x['r'] == tp2_r - ROUND_TRIP*x['entry']/x['risk'] or x['r'] > tp2_r*0.9))

if __name__ == '__main__':
    print("=" * 100)
    print("NEW STRATEGY — HTF trendline + 15M entry | fees 0.14% round-trip (taker+slip)")
    print("=" * 100)
    results = []
    for sym in ["BTCUSDT", "XAUUSDT"]:
        for htf in ["1h", "4h"]:
            for k in [2, 3]:
                for tol in [0.25, 0.5]:
                    r = backtest(sym, htf, k=k, tol_atr=tol)
                    if r and r.get('n', 0) > 5:
                        print(f"{sym:8s} HTF={htf} k={k} tol={tol}: T={r['n']:3d} WR={r['wr']*100:5.1f}% PF={r['pf']:5.2f} netR={r['netR']:+7.1f} avg={r['avg']:+5.2f}R avg_bars={r['avg_bars']} hit15R={r['tp2_count']}")
                        results.append((sym, htf, k, tol, r))
    print("-" * 100)
    if results:
        best = max(results, key=lambda x: x[4]['netR'])
        print("BEST:", best[0], "HTF=" + best[1], "k=", best[2], "tol=", best[3],
              "-> T=%d WR=%.1f%% PF=%.2f netR=%+.1f avg=%+.2fR" % (
                  best[4]['n'], best[4]['wr']*100, best[4]['pf'], best[4]['netR'], best[4]['avg']))
