#!/usr/bin/env python3
"""Round 14: WHICH TIMEFRAME CAN WE MASTER? (user: 1:2/1:1.5 R:R + multi-TP scale-out + 3-4+ trades/day)
Scale-out engine: TP1/TP2/TP3 partial exits, stop->breakeven after TP1 (less loss), 1R stop.
Test signals x timeframes (15m/1h/4h) on XAUUSDT+BTCUSDT. Report trades/day, WR, netR, PF, OOS.
"""
import sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, donch, sma, ema, rsi, metrics

SLIP = 0.0002; FUND_8H = 0.0001
TAKER = 0.0005; MAKER = 0.0002

def get_data(asset, tf):
    p = f"{asset}_{tf}.json"
    if tf == '15m': p = f"{asset}_15m_deep.json"
    kl = load(asset, tf if tf != '15m' else '15m_deep')
    if kl is None: kl = load(asset, tf)
    return kl, atr(kl, 14)

def run_scale(kl, A, signals, tps, sizes, stop_mult, taker, barh, trail_be=True):
    """signals: (i, dir). tps: list of R targets (e.g. [1.0,1.5,2.0]); sizes sum to 1.0."""
    n = len(kl); sigmap = {}
    for (si, d) in signals:
        if si not in sigmap: sigmap[si] = d
    trades = []; pos = None
    for i in range(1, n):
        if pos:
            b = kl[i]; fills = []
            # scale-out TP checks (in order)
            for lvl, size, rsn in pos['tpq']:
                if rsn in pos['done']: continue
                hit = (pos['dir'] == 1 and b['high'] >= pos['tp_price'][rsn]) or \
                      (pos['dir'] == -1 and b['low'] <= pos['tp_price'][rsn])
                if hit: fills.append((rsn, size))
            # stop check
            st = pos['stop']; stop_hit = False
            if pos['dir'] == 1 and b['low'] <= st: stop_hit = True
            if pos['dir'] == -1 and b['high'] >= st: stop_hit = True
            if stop_hit:
                fills.append(('stop', pos['remaining']))
            for rsn, size in fills:
                if size <= 0: continue
                ex = pos['tp_price'][rsn] if rsn != 'stop' else st
                ex2 = ex - pos['dir']*SLIP*ex
                t = {'dir': pos['dir'], 'entry': pos['entry'], 'exit': ex2, 'rsn': rsn,
                     'time': b['time'], 'bars': i - pos['ti'], 'size': size}
                # R accounting: prorate ALL costs by the partial size s
                r_gross = (ex2 - pos['entry'])/pos['risk_amt']*pos['dir']*size
                fees_r = taker*2*pos['entry']/pos['risk_amt']*size
                slip_r = SLIP*2*pos['entry']/pos['risk_amt']*size
                fn_r = FUND_8H*(t['bars']*barh/8.0)*pos['dir']*pos['entry']/pos['risk_amt']*size
                t['r'] = r_gross - fees_r - slip_r - fn_r
                t['net'] = t['r']*pos['risk_amt']/pos['entry'] if pos['entry'] > 0 else 0
                pos['done'].add(rsn)
                pos['remaining'] -= size
                trades.append(t)
            if pos['remaining'] <= 0.001 or stop_hit:
                pos = None
                continue
            # after first TP, move stop to breakeven (reduce loss on remainder)
            if trail_be and any(x in pos['done'] for x in pos['tps']):
                pos['stop'] = pos['entry'] if pos['dir'] == 1 else pos['entry']
        if pos: continue
        if i not in sigmap: continue
        if i+1 >= n: continue
        if A[i] is None or A[i] <= 0: continue
        d = sigmap[i]; e_ = kl[i+1]['open']; e_ = e_ + d*SLIP*e_
        sd = stop_mult*A[i]
        if sd <= 0 or e_ <= 0: continue
        tpq = []; tpp = {}
        for lvl, size in zip(tps, sizes):
            nm = f"tp{lvl}"
            tpp[nm] = e_ + d*lvl*sd
            tpq.append((lvl, size, nm))
        pos = {'dir': d, 'entry': e_, 'risk_amt': sd, 'stop': e_ - d*sd,
               'tp_price': tpp, 'tpq': tpq, 'tps': [f"tp{l}" for l in tps],
               'done': set(), 'remaining': sum(sizes), 'ti': i+1}
    return trades

# ---------- signals ----------
def s_donch_ma(kl, dc_n=20, ma_n=100):
    close = [k['close'] for k in kl]; DU, DL = donch(kl, dc_n); MA = sma(close, ma_n); s = []
    for i in range(ma_n+5, len(kl)):
        if MA[i] is None or DU[i-1] is None: continue
        pc = close[i-1]
        if pc <= DU[i-1] and close[i] > DU[i-1] and close[i] > MA[i]: s.append((i, 1))
        elif pc >= DL[i-1] and close[i] < DL[i-1] and close[i] < MA[i]: s.append((i, -1))
    return s

def s_ema_pull(kl, fast=20, slow=100):
    close = [k['close'] for k in kl]
    ef = ema(close, fast); es = sma(close, slow); s = []
    for i in range(slow+5, len(kl)):
        if ef[i] is None or es[i] is None: continue
        if close[i] > es[i] and kl[i]['low'] <= ef[i] and kl[i]['close'] > ef[i]: s.append((i, 1))
        if close[i] < es[i] and kl[i]['high'] >= ef[i] and kl[i]['close'] < ef[i]: s.append((i, -1))
    return s

def s_vwap(kl, n=60, k=1.5):
    close = [c['close'] for c in kl]
    pv = [0.0]*len(kl); vv = [0.0]*len(kl)
    for i in range(len(kl)):
        tp = (kl[i]['high']+kl[i]['low']+kl[i]['close'])/3
        v = kl[i].get('volume', 0) or 0
        pv[i] = tp*v; vv[i] = v
    sp = [0.0]*(len(kl)+1); sv = [0.0]*(len(kl)+1)
    for i in range(len(kl)):
        sp[i+1] = sp[i]+pv[i]; sv[i+1] = sv[i]+vv[i]
    A = atr(kl, 14); s = []
    for i in range(n+1, len(kl)):
        if A[i] is None or A[i] <= 0: continue
        vsum = sv[i+1]-sv[i+1-n]
        if vsum <= 0: continue
        vwap = (sp[i+1]-sp[i+1-n])/vsum
        dev = (close[i]-vwap)/A[i]
        if dev <= -k: s.append((i, 1))
        elif dev >= k: s.append((i, -1))
    return s

def s_sr(kl, n=20):
    s = []
    for i in range(n+5, len(kl)):
        sup = min(kl[j]['low'] for j in range(i-n, i))
        res = max(kl[j]['high'] for j in range(i-n, i))
        if kl[i]['low'] <= sup and kl[i]['close'] > sup and kl[i]['close'] > kl[i-1]['close']: s.append((i, 1))
        if kl[i]['high'] >= res and kl[i]['close'] < res and kl[i]['close'] < kl[i-1]['close']: s.append((i, -1))
    return s

SIGNALS = [('Donch+MA', s_donch_ma), ('EMA pullback', s_ema_pull), ('VWAP rev', s_vwap), ('S/R reclaim', s_sr)]
TFS = [('15m', 0.25, 6000), ('1h', 1.0, 600), ('4h', 4.0, 600)]
TPSETS = [([1.0, 1.5, 2.0], [0.4, 0.3, 0.3], "1:2 scale"), ([0.75, 1.0, 1.5], [0.4, 0.3, 0.3], "1:1.5 scale")]
ASSETS = ["XAUUSDT", "BTCUSDT"]

def agg(tf, barh, bars, name, fn, tps, sizes, label, taker):
    alltr = []
    days_total = 0
    for a in ASSETS:
        kl, A = get_data(a, tf)
        if kl is None: continue
        kl = kl[-bars:]
        A = atr(kl, 14)
        sig = fn(kl)
        tr = run_scale(kl, A, sig, tps, sizes, 2.0, taker, barh)
        for t in tr: t['asset'] = a
        alltr += tr
        days_total += len(kl)*barh/24.0
    if not alltr: return
    m = metrics(alltr)
    tpd = m['trades']/days_total if days_total else 0
    times = sorted(t['time'] for t in alltr)
    oos = "-"
    if times and len(alltr) >= 20:
        med = times[len(times)//2]
        h1 = metrics([t for t in alltr if t['time'] <= med]); h2 = metrics([t for t in alltr if t['time'] > med])
        oos = f"{h1['netR']:>5.1f}/{h2['netR']:>5.1f}" + (" OK" if (h1['netR'] > 0 and h2['netR'] > 0) else " X")
    flag = " <== PROFIT" if m['netR'] > 0 and m['pf'] > 1.0 else ""
    print(f"{tf:<4}{name:<16}{label:<12} T={m['trades']:>4} {tpd:>4.1f}/day WR={m['wr']:>2.0f}% netR={m['netR']:>7.1f} PF={m['pf']:>5.2f}  h1/h2={oos}{flag}")

print("ROUND 14: WHICH TIMEFRAME IS MASTERABLE? gold+BTC, scale-out (multi-TP), 1R stop, 2xATR risk")
print("="*120)
for tps, sizes, lab in TPSETS:
    print(f"\n### {lab} (TP={tps}R, sizes={sizes})")
    for tf, barh, bars in TFS:
        for name, fn in SIGNALS:
            agg(tf, barh, bars, name, fn, tps, sizes, lab, TAKER)
