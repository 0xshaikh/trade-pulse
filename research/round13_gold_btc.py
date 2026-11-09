#!/usr/bin/env python3
"""Round 13: GOLD + BTC only, 15M, target WR 80%+.
Deep sample (6000 bars each). REAL costs (taker 0.05%/side + slippage + funding; and maker 0.02%/side variant).
Flag: [HIT]=WR>=80 & netR>0 | [TRAP]=WR>=80 & netR<=0 | per-asset + half-split OOS.
"""
import sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, sma, ema, rsi, metrics

SLIP = 0.0002; FUND_8H = 0.0001; BARH = 0.25

def load2(a):
    kl = load(a, '15m_deep')
    if kl is None: kl = load(a, '15m')
    return kl, atr(kl, 14)

def run15(kl, A, signals, tp, stop, mb, taker):
    n = len(kl); sigmap = {}
    for (si, d) in signals:
        if si not in sigmap: sigmap[si] = d
    trades = []; pos = None
    for i in range(1, n):
        if pos:
            b = kl[i]; ex = None; rsn = None
            st = pos['stop']
            if pos['dir'] == 1:
                if b['low'] <= st: ex = st; rsn = 'stop'
                elif pos['tp'] is not None and b['high'] >= pos['tp']: ex = pos['tp']; rsn = 'target'
            else:
                if b['high'] >= st: ex = st; rsn = 'stop'
                elif pos['tp'] is not None and b['low'] <= pos['tp']: ex = pos['tp']; rsn = 'target'
            if ex is None and mb and (i - pos['ti']) >= mb: ex = b['close']; rsn = 'time'
            if ex is not None:
                t = pos; ex2 = ex - pos['dir']*SLIP*ex
                t['exit'] = ex2; t['rsn'] = rsn; t['time'] = b['time']
                bars = i - pos['ti']
                gross = (ex2 - t['entry'])/t['entry']*t['dir']
                fn = FUND_8H*(bars*BARH/8.0)
                t['net'] = gross - taker*2 - SLIP*2 - fn*pos['dir']
                t['r'] = (t['net']*t['entry'])/t['risk_amt'] if t['risk_amt'] > 0 else 0
                trades.append(t); pos = None
        if pos: continue
        if i not in sigmap: continue
        if i+1 >= n: continue
        if A[i] is None or A[i] <= 0: continue
        d = sigmap[i]; e_ = kl[i+1]['open']; e_ = e_ + d*SLIP*e_
        sd = stop*A[i]
        if sd <= 0 or e_ <= 0: continue
        pos = {'dir': d, 'entry': e_, 'risk_amt': sd, 'stop': e_ - d*sd,
               'tp': (e_ + d*tp*sd) if tp else None, 'ti': i+1}
    return trades

def s_vwap(kl, n=60, k=1.5):
    closes = [c['close'] for c in kl]
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
        dev = (closes[i]-vwap)/A[i]
        if dev <= -k: s.append((i, 1))
        elif dev >= k: s.append((i, -1))
    return s

def s_rsi(kl, lo, hi, n=14):
    R = rsi([k['close'] for k in kl], n); s = []
    for i in range(30, len(kl)):
        if R[i] is None or R[i-1] is None: continue
        if R[i-1] > lo and R[i] <= lo: s.append((i, 1))
        elif R[i-1] < hi and R[i] >= hi: s.append((i, -1))
    return s

def s_bb(kl, n=20, k=2.0):
    closes = [c['close'] for c in kl]; mid = sma(closes, n)
    lo = [None]*len(kl); hi = [None]*len(kl)
    for i in range(n-1, len(kl)):
        w = closes[i-n+1:i+1]; m = mid[i]
        sd = math.sqrt(sum((x-m)**2 for x in w)/n)
        lo[i] = m - k*sd; hi[i] = m + k*sd
    s = []
    for i in range(25, len(kl)):
        if lo[i] is None: continue
        if kl[i-1]['close'] > lo[i-1] and kl[i]['close'] <= lo[i]: s.append((i, 1))
        if kl[i-1]['close'] < hi[i-1] and kl[i]['close'] >= hi[i]: s.append((i, -1))
    return s

def s_sr(kl, n=20):
    s = []
    for i in range(n+5, len(kl)):
        sup = min(kl[j]['low'] for j in range(i-n, i))
        res = max(kl[j]['high'] for j in range(i-n, i))
        if kl[i]['low'] <= sup and kl[i]['close'] > sup and kl[i]['close'] > kl[i-1]['close']: s.append((i, 1))
        if kl[i]['high'] >= res and kl[i]['close'] < res and kl[i]['close'] < kl[i-1]['close']: s.append((i, -1))
    return s

def s_ema_pull(kl, fast=20, slow=200):
    closes = [c['close'] for c in kl]
    ef = ema(closes, fast); es = sma(closes, slow); s = []
    for i in range(slow+5, len(kl)):
        if ef[i] is None or es[i] is None: continue
        if closes[i] > es[i] and kl[i]['low'] <= ef[i] and kl[i]['close'] > ef[i]: s.append((i, 1))
        if closes[i] < es[i] and kl[i]['high'] >= ef[i] and kl[i]['close'] < ef[i]: s.append((i, -1))
    return s

FAMS = [('VWAP1.5', lambda kl: s_vwap(kl, k=1.5)), ('VWAP2.0', lambda kl: s_vwap(kl, k=2.0)),
        ('VWAP2.5', lambda kl: s_vwap(kl, k=2.5)), ('RSI30', lambda kl: s_rsi(kl, 30, 70)),
        ('RSI35', lambda kl: s_rsi(kl, 35, 65)), ('BB20', s_bb), ('SR20', s_sr), ('EMApull', s_ema_pull)]
TPS = [0.15, 0.2, 0.3, 0.4]
STOPS = [1.5, 2.0, 2.5, 3.0]
ASSETS2 = ["XAUUSDT", "BTCUSDT"]

def run_asset(asset, kind_fn, tp, stop, mb, taker):
    kl, A = load2(asset)
    tr = run15(kl, A, kind_fn(kl), tp, stop, mb, taker)
    for t in tr: t['asset'] = asset
    m = metrics(tr)
    times = sorted(t['time'] for t in tr)
    oos = "-"
    if times and len(tr) >= 30:
        med = times[len(times)//2]
        h1 = metrics([t for t in tr if t['time'] <= med]); h2 = metrics([t for t in tr if t['time'] > med])
        oos = f"{h1['netR']:>6.1f}/{h2['netR']:>6.1f}" + (" OK" if (h1['netR'] > 0 and h2['netR'] > 0) else " X")
    return m, oos

print("ROUND 13: GOLD + BTC 15M, target WR>=80%. 6000 bars each. REAL costs.")
print("="*120)
results = []
for asset in ASSETS2:
    for name, fn in FAMS:
        for tp in TPS:
            for stop in STOPS:
                for taker, ftag in ((0.0002, 'maker'), (0.0005, 'taker')):
                    m, oos = run_asset(asset, fn, tp, stop, None, taker)
                    flag = ""
                    if m['wr'] >= 80: flag = " [HIT]" if m['netR'] > 0 else " [TRAP]"
                    results.append((m['wr'], m['netR'], asset, name, tp, stop, ftag, m['trades'], m['pf'], oos, flag))

print("--- HIGHEST WR, per asset (top 12 each) ---")
for asset in ASSETS2:
    print(f"\n[{asset}]")
    for wr, netR, a, name, tp, stop, ftag, T, pf, oos, flag in sorted([r for r in results if r[2] == asset], key=lambda x: -x[0])[:12]:
        print(f"  WR={wr:>2.0f}% netR={netR:>8.1f} PF={pf:>4.2f} T={T:>4}  {name} TP={tp}R stop={stop}R {ftag}  h1/h2={oos}{flag}")
print("\n--- HITS (WR>=80 & netR>0) ---")
hits = [r for r in results if r[0] >= 80 and r[1] > 0]
print(f"found: {len(hits)}")
for wr, netR, a, name, tp, stop, ftag, T, pf, oos, flag in hits[:20]:
    print(f"  WR={wr:>2.0f}% netR={netR:>8.1f} {a} {name} TP={tp}R stop={stop}R {ftag} h1/h2={oos}")
print("\n--- TRAPS (WR>=80 but netR<=0) count ---")
print(len([r for r in results if r[0] >= 80 and r[1] <= 0]))
