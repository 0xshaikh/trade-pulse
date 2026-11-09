#!/usr/bin/env python3
"""Round 12b: FRIENDLIEST-CASE check on 15M. Can ANYTHING hit 80% WR + profit?
Maker-fee (0.02%/side, best case) + tiny TP (0.15-0.3R) + wide stop (1.5-2R), top signals.
If even this loses or can't reach 80% WR, the cost-drag wall is fundamental, not a parameter issue.
"""
import sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, sma, ema, rsi, metrics, ASSETS

SLIP = 0.0002; FUND_8H = 0.0001; BARH = 0.25
from round12_15m_highwr import DATA, s_rsi, s_vwap, s_sr, s_bb, s_ema_pull

def run15(kl, A, signals, tp_mult, stop_mult, max_bars, taker):
    n = len(kl); sigmap = {}
    for (si, d) in signals:
        if si not in sigmap: sigmap[si] = d
    trades = []; pos = None
    for i in range(1, n):
        if pos:
            b = kl[i]; ex = None; rsn = None
            stop = pos['stop']
            if pos['dir'] == 1:
                if b['low'] <= stop: ex = stop; rsn = 'stop'
                elif pos['tp'] is not None and b['high'] >= pos['tp']: ex = pos['tp']; rsn = 'target'
            else:
                if b['high'] >= stop: ex = stop; rsn = 'stop'
                elif pos['tp'] is not None and b['low'] <= pos['tp']: ex = pos['tp']; rsn = 'target'
            if ex is None and max_bars and (i - pos['ti']) >= max_bars: ex = b['close']; rsn = 'time'
            if ex is not None:
                t = pos; ex2 = ex - pos['dir']*SLIP*ex
                t['exit'] = ex2; t['rsn'] = rsn; t['time'] = b['time']
                bars = i - pos['ti']
                gross = (ex2 - t['entry'])/t['entry']*t['dir']
                fees = taker*2; sl = SLIP*2
                fn = FUND_8H*(bars*BARH/8.0)
                t['net'] = gross - fees - sl - fn*pos['dir']
                t['r'] = (t['net']*t['entry'])/t['risk_amt'] if t['risk_amt'] > 0 else 0
                trades.append(t); pos = None
        if pos: continue
        if i not in sigmap: continue
        if i+1 >= n: continue
        if A[i] is None or A[i] <= 0: continue
        d = sigmap[i]; e_ = kl[i+1]['open']; e_ = e_ + d*SLIP*e_
        sd = stop_mult*A[i]
        if sd <= 0 or e_ <= 0: continue
        pos = {'dir': d, 'entry': e_, 'risk_amt': sd, 'stop': e_ - d*sd,
               'tp': (e_ + d*tp_mult*sd) if tp_mult else None, 'ti': i+1}
    return trades

def run_cfg(fn, tp, stop, mb, taker, label):
    alltr = []
    for a, (kl, A) in DATA.items():
        sig = fn(kl)
        tr = run15(kl, A, sig, tp, stop, mb, taker)
        for t in tr: t['asset'] = a
        alltr += tr
    m = metrics(alltr)
    flag = ""
    if m['wr'] >= 80: flag = " [HIT]" if m['netR'] > 0 else " [WR80-TRAP]"
    print(f"{label:<46} T={m['trades']:>4} WR={m['wr']:>2.0f}% netR={m['netR']:>8.1f} PF={m['pf']:>5.2f}{flag}")
    return m

print("ROUND 12b: FRIENDLIEST case — maker fee 0.02%/side, tiny TP, wide stop, 14 assets x 1500 bars")
print("="*118)
FAMS = [('VWAP', s_vwap), ('RSI', lambda kl: s_rsi(kl, 30, 70)), ('S/R', s_sr)]
for name, fn in FAMS:
    for tp in (0.15, 0.2, 0.3):
        for stop in (1.5, 2.0):
            for taker, ftag in ((0.0002, 'maker'), (0.0005, 'taker')):
                run_cfg(fn, tp, stop, None, taker, f"{name} TP={tp}R stop={stop}R {ftag}")
