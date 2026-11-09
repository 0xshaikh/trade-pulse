#!/usr/bin/env python3
"""Round 11: IMAGE STRATEGIES — the 10 strategies from the user's screenshot.
Same REAL engine as round9 (next-open fill + slippage 0.02%/side + funding 0.01%/8h +
taker 0.05%/side, 2xATR stop). ONLY the entry signal differs per strategy.

Testable on OHLCV (no volume/order-book/macro needed):
  - RSI oversold/overbought (mean reversion)
  - Support & Resistance touch-reclaim (mean reversion)
  - Opening Range Breakout (UTC-day session, first-K-bar range)
  - Trendline break (pivot-based, descending-resistance/ascending-support)
  - ICT unicorn approx (liquidity sweep + reclaim)

NOT testable on this OHLCV data (need volume / order book / macro):
  - Auction market theory (needs volume profile)      -> SKIP, flag
  - Order flow (needs footprint/delta/order book)     -> SKIP, flag
  - VWAP mean reversion (needs volume to weight)      -> SKIP, flag
  - Macro trading (needs macro event data)            -> SKIP, flag
  - Mechanical trading (umbrella term = the current system is already mechanical) -> baseline ref
"""
import sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, donch, sma, ema, rsi, metrics, ASSETS

SLIP = 0.0002; TAKER = 0.0005; FUND_8H = 0.0001

# ---------- generic REAL engine (signal list in, trades out) ----------
def run_real(kl, signals, atr_n=14, next_open=True, slip=SLIP, fund=True, eod=None):
    """signals: sorted list of (sig_idx, dir, stop_mult, tp_mult, eod_idx|None).
    Signal fires on close[sig_idx]; enter open[sig_idx+1]; exit stop/target/eod."""
    n = len(kl); A = atr(kl, atr_n)
    sigmap = {}
    for (si, d, sm, tm, e) in signals:
        if si not in sigmap: sigmap[si] = (d, sm, tm, e)
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
            if pos['eod'] is not None and i >= pos['eod'] and ex is None:
                ex = b['close']; rsn = 'eod'
            if ex is not None:
                t = pos
                ex2 = ex - pos['dir']*slip*ex
                t['exit'] = ex2; t['rsn'] = rsn; t['time'] = b['time']
                bars_held = i - pos['ti']
                gross = (ex2 - t['entry'])/t['entry']*t['dir']
                fees = TAKER*2; sl = slip*2
                fn = (FUND_8H*(bars_held*4/8.0)) if fund else 0
                t['net'] = gross - fees - sl - fn*pos['dir']
                t['r'] = (t['net']*t['entry'])/t['risk_amt'] if t['risk_amt'] > 0 else 0
                t['bars'] = bars_held; t['fund'] = fn*pos['dir']
                trades.append(t); pos = None
        if pos: continue
        if i not in sigmap: continue
        d, sm, tm, e = sigmap[i]
        if i+1 >= n: continue
        if A[i] is None or A[i] <= 0: continue
        e_ = kl[i+1]['open']
        e_ = e_ + d*slip*e_
        sd = sm*A[i]
        if sd <= 0 or e_ <= 0: continue
        pos = {'dir': d, 'entry': e_, 'risk_amt': sd, 'stop': e_ - d*sd,
               'tp': (e_ + d*tm*sd) if tm else None, 'ti': i+1, 'eod': e}
    return trades

# ---------- signal generators ----------
def pivots(kl, k=2):
    hi_p = []; lo_p = []
    for i in range(k, len(kl)-k):
        if kl[i]['high'] == max(kl[j]['high'] for j in range(i-k, i+k+1)): hi_p.append(i)
        if kl[i]['low'] == min(kl[j]['low'] for j in range(i-k, i+k+1)): lo_p.append(i)
    return hi_p, lo_p

def sig_rsi(kl, daily=None, lo=30, hi=70, sm=2.0, tm=3.0):
    R = rsi([k['close'] for k in kl], 14); s = []
    for i in range(len(kl)):
        if R[i] is None or i < 25: continue
        if R[i] < lo: s.append((i, 1, sm, tm, None))
        elif R[i] > hi: s.append((i, -1, sm, tm, None))
    return s

def sig_sr(kl, daily=None, sm=2.0, tm=3.0):
    s = []
    for i in range(25, len(kl)):
        sup = min(kl[j]['low'] for j in range(i-20, i))
        res = max(kl[j]['high'] for j in range(i-20, i))
        if kl[i]['low'] <= sup and kl[i]['close'] > sup and kl[i]['close'] > kl[i-1]['close']:
            s.append((i, 1, sm, tm, None))
        if kl[i]['high'] >= res and kl[i]['close'] < res and kl[i]['close'] < kl[i-1]['close']:
            s.append((i, -1, sm, tm, None))
    return s

def sig_orb(kl, daily=None, k=2, sm=2.0, tm=3.0):
    s = []; i = 0
    while i < len(kl):
        day = kl[i]['time']//86400; daybars = []
        j = i
        while j < len(kl) and kl[j]['time']//86400 == day:
            daybars.append(j); j += 1
        if len(daybars) >= k+1:
            oh = max(kl[daybars[t]]['high'] for t in range(k))
            ol = min(kl[daybars[t]]['low'] for t in range(k))
            taken = set()
            for t in range(k, len(daybars)):
                idx = daybars[t]; eod = daybars[-1]
                if 1 not in taken and kl[idx]['close'] > oh:
                    s.append((idx, 1, sm, tm, eod)); taken.add(1)
                elif -1 not in taken and kl[idx]['close'] < ol:
                    s.append((idx, -1, sm, tm, eod)); taken.add(-1)
        i = j
    return s

def sig_trend(kl, daily=None, sm=2.0, tm=3.0):
    hi_p, lo_p = pivots(kl, 2); s = []
    for i in range(len(kl)):
        ph = [p for p in hi_p if p < i]
        if len(ph) >= 2:
            x1, y1 = ph[-2], kl[ph[-2]]['high']; x2, y2 = ph[-1], kl[ph[-1]]['high']
            if x2 > x1:
                slope = (y2-y1)/(x2-x1)
                if slope < 0:
                    line = y2 + slope*(i-x2)
                    if kl[i]['close'] > line: s.append((i, 1, sm, tm, None))
        pl = [p for p in lo_p if p < i]
        if len(pl) >= 2:
            x1, y1 = pl[-2], kl[pl[-2]]['low']; x2, y2 = pl[-1], kl[pl[-1]]['low']
            if x2 > x1:
                slope = (y2-y1)/(x2-x1)
                if slope > 0:
                    line = y2 + slope*(i-x2)
                    if kl[i]['close'] < line: s.append((i, -1, sm, tm, None))
    return s

def sig_ict(kl, daily=None, sm=2.0, tm=3.0):
    s = []
    for i in range(25, len(kl)):
        sw_lo = min(kl[j]['low'] for j in range(i-25, i-5))
        sw_hi = max(kl[j]['high'] for j in range(i-25, i-5))
        if kl[i]['low'] < sw_lo and kl[i]['close'] > sw_lo: s.append((i, 1, sm, tm, None))
        if kl[i]['high'] > sw_hi and kl[i]['close'] < sw_hi: s.append((i, -1, sm, tm, None))
    return s

# baseline = current mechanical system (Donchian20+MA100+chop+daily gate)
def sig_baseline(kl, daily, cfg):
    n = len(kl); close = [k['close'] for k in kl]
    DU, DL = donch(kl, cfg['dc_n']); MA = sma(close, cfg['ma_n']); A = atr(kl, cfg['atr_n'])
    dclose = [k['close'] for k in daily]; dma = sma(dclose, cfg.get('daily_ma_n', 200))
    warm = max(cfg['dc_n'], cfg['ma_n'], 20)+5; s = []
    for i in range(warm, n):
        if MA[i] is None or A[i] is None or DU[i-1] is None: continue
        pc = close[i-1]; d = 0
        slope = (MA[i]-MA[i-5])/pc*100 if pc > 0 and MA[i-5] is not None else 0
        if abs(slope) >= cfg['min_slope']:
            if pc <= DU[i-1] and close[i] > DU[i-1] and close[i] > MA[i]: d = 1
            elif pc >= DL[i-1] and close[i] < DL[i-1] and close[i] < MA[i]: d = -1
        if d == 0: continue
        ts = kl[i]['time']; idx = -1
        for j in range(len(daily)):
            if daily[j]['time'] <= ts: idx = j
            else: break
        if idx >= cfg.get('daily_ma_n', 200)-1 and dma[idx] is not None:
            dc = dclose[idx]; dm = dma[idx]
            if d == 1 and dc <= dm: continue
            if d == -1 and dc >= dm: continue
        s.append((i, d, cfg['stop_mult'], cfg['tp_mult'], None))
    return s

# ---------- aggregator ----------
def agg(name, fn, tf='4h', bars=600, label_extra=""):
    alltr = []
    for a in ASSETS:
        kl = load(a, tf)
        if kl is None: continue
        kl = kl[-bars:]; daily = load(a, '1d')
        s = fn(kl, daily)
        tr = run_real(kl, s, atr_n=14, next_open=True, slip=SLIP, fund=True)
        for t in tr: t['asset'] = a
        alltr += tr
    m = metrics(alltr)
    times = sorted(t['time'] for t in alltr)
    hh = "no trades"
    if times:
        med = times[len(times)//2]
        h1 = metrics([t for t in alltr if t['time'] <= med]); h2 = metrics([t for t in alltr if t['time'] > med])
        flag = "OK" if (h1['netR'] > 0 and h2['netR'] > 0) else "X"
        hh = f"h1={h1['netR']:>5.1f} h2={h2['netR']:>5.1f} {flag}"
    print(f"{name:<44}{label_extra:<14} T={m['trades']:>3} WR={m['wr']:>2.0f}% netR={m['netR']:>6.1f} PF={m['pf']:>5.2f}  {hh}")
    return m

base_cfg = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
                use_chop=True, min_slope=0.05, use_daily_gate=True, daily_ma_n=200,
                strict_gate=False, atr_band=(0.5, 3.0))

print("ROUND 11: image strategies on REAL engine (next-open + slip 0.02% + funding + taker, 2xATR stop)")
print("="*118)
print("--- 4h, 600 bars, apples-to-apples (2xATR stop / 3xATR target) ---")
m_base = agg("Baseline: Donchian+MA (current/mechanical)", lambda kl, daily: sig_baseline(kl, daily, base_cfg), label_extra="[3R]")
agg("RSI oversold/overbought (mean-rev)", sig_rsi, label_extra="[3R]")
agg("Support & Resistance reclaim", sig_sr, label_extra="[3R]")
agg("Opening Range Breakout (2-bar)", sig_orb, label_extra="[3R]")
agg("Trendline break (pivot)", sig_trend, label_extra="[3R]")
agg("ICT unicorn approx (sweep+reclaim)", sig_ict, label_extra="[3R]")
print()
print("--- mean-reversion strategies get a reversion-appropriate 2xATR stop / 1.5xATR target ---")
agg("RSI oversold (mean-rev)", lambda kl, daily: sig_rsi(kl, daily, tm=1.5), label_extra="[1.5R]")
agg("Support & Resistance reclaim", lambda kl, daily: sig_sr(kl, daily, tm=1.5), label_extra="[1.5R]")
print()
print("--- top candidates also on 1h (more bars) ---")
agg("Baseline: Donchian+MA (1h)", lambda kl, daily: sig_baseline(kl, daily, base_cfg), tf='1h', bars=600, label_extra="[3R]")
agg("RSI oversold (1h)", lambda kl, daily: sig_rsi(kl, daily, tm=1.5), tf='1h', bars=600, label_extra="[1.5R]")
agg("Opening Range Breakout (1h)", lambda kl, daily: sig_orb(kl, daily, k=3), tf='1h', bars=600, label_extra="[3R]")
agg("ICT unicorn approx (1h)", sig_ict, tf='1h', bars=600, label_extra="[3R]")
