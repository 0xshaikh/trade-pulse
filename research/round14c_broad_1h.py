#!/usr/bin/env python3
"""Round 14c: BROAD 1H DEEP SEARCH (3000 bars, 125 days) gold+BTC — is 1h masterable at all?
Scale-out (multi-TP), many signal families, 1R stop / 2xATR risk. Robustness = full sample + OOS split.
"""
import sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, donch, sma, ema, rsi, metrics
from round14_scaleout_tf import run_scale, s_donch_ma, s_ema_pull, s_vwap, s_sr

TAKER = 0.0005
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
def s_mom(kl, n=200):
    closes = [c['close'] for c in kl]; es = sma(closes, n); R = rsi(closes, 14); s = []
    for i in range(n+5, len(kl)):
        if es[i] is None or R[i] is None: continue
        if closes[i] > es[i] and R[i] > 55 and R[i-1] <= 55: s.append((i, 1))
        if closes[i] < es[i] and R[i] < 45 and R[i-1] >= 45: s.append((i, -1))
    return s

SIGS = [('Donch20+MA', lambda kl: s_donch_ma(kl, 20, 100)), ('Donch10+MA', lambda kl: s_donch_ma(kl, 10, 100)),
        ('EMA pullback', s_ema_pull), ('VWAP1.5', lambda kl: s_vwap(kl, k=1.5)), ('VWAP2.0', lambda kl: s_vwap(kl, k=2.0)),
        ('S/R', s_sr), ('RSI30', lambda kl: s_rsi(kl, 30, 70)), ('BB20', s_bb), ('Momentum', s_mom)]
TPSETS = [([1.0, 1.5, 2.0], [0.4, 0.3, 0.3], "1:2"), ([0.75, 1.0, 1.5], [0.4, 0.3, 0.3], "1:1.5")]

def agg(name, fn, tps, sizes, lab):
    alltr = []
    for asset in ("XAUUSDT", "BTCUSDT"):
        kl = load(asset, "1h_deep")
        if kl is None: continue
        A = atr(kl, 14)
        tr = run_scale(kl, A, fn(kl), tps, sizes, 2.0, TAKER, 1.0)
        for t in tr: t['asset'] = asset
        alltr += tr
    if not alltr: return
    m = metrics(alltr)
    days = 2*len(load("BTCUSDT", "1h_deep"))/24
    times = sorted(t['time'] for t in alltr)
    oos = "-"
    if times and len(alltr) >= 20:
        med = times[len(times)//2]
        h1 = metrics([t for t in alltr if t['time'] <= med]); h2 = metrics([t for t in alltr if t['time'] > med])
        oos = f"{h1['netR']:>5.1f}/{h2['netR']:>5.1f}" + (" OK" if (h1['netR'] > 0 and h2['netR'] > 0) else " X")
    flag = " <== PROFIT" if m['netR'] > 0 and m['pf'] > 1.05 and oos.endswith("OK") else ""
    print(f"{name:<16}{lab:<8} T={m['trades']:>3} {m['trades']/days:>4.1f}/day WR={m['wr']:>2.0f}% netR={m['netR']:>7.1f} PF={m['pf']:>5.2f} h1/h2={oos}{flag}")

print("ROUND 14c: 1H DEEP (3000 bars/125d) gold+BTC — scale-out, robust check")
print("="*110)
for tps, sizes, lab in TPSETS:
    print(f"\n### {lab}")
    for name, fn in SIGS:
        agg(name, fn, tps, sizes, lab)
