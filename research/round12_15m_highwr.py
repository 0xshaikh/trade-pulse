#!/usr/bin/env python3
"""Round 12: 15M HIGH-WR SEARCH (user target: 80%+ win rate, non-stop).
Mean-reversion / scalp families on 15m with SMALL TP (high WR) vs realistic costs.
REAL engine: next-open + slippage 0.02%/side + funding 0.01%/8h (prorated 15m) + taker 0.05%/side.
For every config report WR, netR, PF + half-split (out-of-sample). Flag:
  [HIT]  = WR>=80% AND netR>0  (the real prize)
  [WR80] = WR>=80% but netR<=0 (high-WR trap — costs eat the tiny target)
"""
import sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, donch, sma, ema, rsi, metrics, ASSETS

SLIP = 0.0002; TAKER = 0.0005; FUND_8H = 0.0001
BARH = 0.25  # 15m = 0.25h

DATA = {}
for a in ASSETS:
    kl = load(a, '15m')
    if kl and len(kl) >= 500:
        DATA[a] = (kl, atr(kl, 14))

# ---------- engine (15m, fixed tp/stop in R) ----------
def run15(kl, A, signals, tp_mult, stop_mult, max_bars):
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
                fees = TAKER*2; sl = SLIP*2
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

# ---------- signal generators (return (i, dir)) ----------
def s_rsi(kl, lo, hi, n=14):
    R = rsi([k['close'] for k in kl], n); s = []
    for i in range(30, len(kl)):
        if R[i] is None or R[i-1] is None: continue
        if R[i-1] > lo and R[i] <= lo: s.append((i, 1))
        elif R[i-1] < hi and R[i] >= hi: s.append((i, -1))
    return s

def _boll(kl, n=20, k=2.0):
    closes = [c['close'] for c in kl]; mid = sma(closes, n)
    lo = [None]*len(kl); hi = [None]*len(kl)
    for i in range(n-1, len(kl)):
        w = closes[i-n+1:i+1]; m = mid[i]
        sd = math.sqrt(sum((x-m)**2 for x in w)/n)
        lo[i] = m - k*sd; hi[i] = m + k*sd
    return lo, hi

def s_bb(kl, n=20, k=2.0):
    lo, hi = _boll(kl, n, k); s = []
    for i in range(25, len(kl)):
        if lo[i] is None: continue
        if kl[i-1]['close'] > lo[i-1] and kl[i]['close'] <= lo[i]: s.append((i, 1))
        if kl[i-1]['close'] < hi[i-1] and kl[i]['close'] >= hi[i]: s.append((i, -1))
    return s

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

def s_ema_pull(kl, fast=20, slow=200):
    closes = [c['close'] for c in kl]
    ef = ema(closes, fast); es = sma(closes, slow); s = []
    for i in range(slow+5, len(kl)):
        if ef[i] is None or es[i] is None: continue
        if closes[i] > es[i] and kl[i]['low'] <= ef[i] and kl[i]['close'] > ef[i]: s.append((i, 1))
        if closes[i] < es[i] and kl[i]['high'] >= ef[i] and kl[i]['close'] < ef[i]: s.append((i, -1))
    return s

def s_sr(kl, n=20):
    s = []
    for i in range(n+5, len(kl)):
        sup = min(kl[j]['low'] for j in range(i-n, i))
        res = max(kl[j]['high'] for j in range(i-n, i))
        if kl[i]['low'] <= sup and kl[i]['close'] > sup and kl[i]['close'] > kl[i-1]['close']: s.append((i, 1))
        if kl[i]['high'] >= res and kl[i]['close'] < res and kl[i]['close'] < kl[i-1]['close']: s.append((i, -1))
    return s

# ---------- run one config across all assets ----------
def run_cfg(kind, tp, stop, max_bars, label):
    alltr = []
    for a, (kl, A) in DATA.items():
        if kind == 'rsi': sig = s_rsi(kl, 30, 70)
        elif kind == 'rsi35': sig = s_rsi(kl, 35, 65)
        elif kind == 'bb': sig = s_bb(kl)
        elif kind == 'vwap': sig = s_vwap(kl)
        elif kind == 'vwap2': sig = s_vwap(kl, k=2.0)
        elif kind == 'ema_pull': sig = s_ema_pull(kl)
        elif kind == 'sr': sig = s_sr(kl)
        tr = run15(kl, A, sig, tp, stop, max_bars)
        for t in tr: t['asset'] = a
        alltr += tr
    m = metrics(alltr)
    times = sorted(t['time'] for t in alltr)
    oos = "-"
    if times and len(alltr) >= 20:
        med = times[len(times)//2]
        h1 = metrics([t for t in alltr if t['time'] <= med]); h2 = metrics([t for t in alltr if t['time'] > med])
        oos = f"{h1['netR']:>6.1f}/{h2['netR']:>6.1f}" + (" OK" if (h1['netR'] > 0 and h2['netR'] > 0) else " X")
    flag = ""
    if m['wr'] >= 80:
        flag = " [HIT]" if m['netR'] > 0 else " [WR80-TRAP]"
    print(f"{label:<44} T={m['trades']:>4} WR={m['wr']:>2.0f}% netR={m['netR']:>7.1f} PF={m['pf']:>5.2f}  h1/h2={oos}{flag}")
    return m

print("ROUND 12: 15M HIGH-WR SEARCH (target 80%+ WR). 14 assets x 1500 bars. REAL costs.")
print("="*120)
KINDS = [('rsi','RSI14 cross<30/70'), ('rsi35','RSI14 cross<35/65'), ('bb','Bollinger reclaim'),
         ('vwap','VWAP dev>1.5A'), ('vwap2','VWAP dev>2.0A'), ('ema_pull','EMA20 pullback'),
         ('sr','S/R touch-reclaim')]
TPS = [0.3, 0.5, 0.75, 1.0]
STOPS = [1.0, 1.5, 2.0]
BEST = []
for kind, kn in KINDS:
    for tp in TPS:
        for stop in STOPS:
            for mb in (None, 16):
                tag = "ts16" if mb else "hold"
                lab = f"{kn} TP={tp}R stop={stop}R {tag}"
                m = run_cfg(kind, tp, stop, mb, lab)
                BEST.append((m['netR'], m['wr'], lab, m))
print()
print("=== TOP by netR (profitable) ===")
for netR, wr, lab, m in sorted(BEST, key=lambda x: -x[0])[:12]:
    print(f"{netR:>7.1f}R  WR={wr:>2.0f}%  {lab}")
print()
print("=== HIGHEST WR (all) ===")
for netR, wr, lab, m in sorted(BEST, key=lambda x: -x[1])[:12]:
    print(f"WR={wr:>2.0f}%  netR={netR:>7.1f}  {lab}")
