#!/usr/bin/env python3
"""Round 14d: MAKER-FEE rescues? Test 1h+15m signals with limit-order fills (0.02%/side).
If even maker costs keep them negative, no high-frequency TF is masterable on gold+BTC.
"""
import sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, sma, rsi, metrics
from round14_scaleout_tf import run_scale, s_donch_ma, s_ema_pull, s_vwap, s_sr
from round14c_broad_1h import s_rsi, s_bb, s_mom

MAKER = 0.0002
def agg(asset, tf, name, fn, tps, sizes, barh):
    kl = load(asset, f"{tf}_deep") if tf in ('15m','1h') else load(asset, tf)
    if kl is None: return None
    A = atr(kl, 14)
    tr = run_scale(kl, A, fn(kl), tps, sizes, 2.0, MAKER, barh)
    for t in tr: t['asset'] = asset
    m = metrics(tr)
    times = sorted(t['time'] for t in tr)
    oos = "-"
    if times and len(tr) >= 20:
        med = times[len(times)//2]
        h1 = metrics([t for t in tr if t['time'] <= med]); h2 = metrics([t for t in tr if t['time'] > med])
        oos = f"{h1['netR']:>5.1f}/{h2['netR']:>5.1f}" + (" OK" if (h1['netR'] > 0 and h2['netR'] > 0) else " X")
    return m, oos

SIGS = [('Donch20+MA', lambda kl: s_donch_ma(kl, 20, 100)), ('EMA pullback', s_ema_pull),
        ('VWAP1.5', lambda kl: s_vwap(kl, k=1.5)), ('S/R', s_sr), ('RSI30', lambda kl: s_rsi(kl, 30, 70)), ('BB20', s_bb)]
TPS = [1.0, 1.5, 2.0]; SIZ = [0.4, 0.3, 0.3]

print("ROUND 14d: MAKER (0.02%/side) — does it rescue 1h/15m? gold+BTC, scale-out 1:2")
print("="*110)
for tf, barh in (('1h', 1.0), ('15m', 0.25)):
    print(f"\n### {tf} (deep, maker)")
    for name, fn in SIGS:
        for asset in ("XAUUSDT", "BTCUSDT"):
            r = agg(asset, tf, name, fn, TPS, SIZ, barh)
            if r is None: continue
            m, oos = r
            days = len(load(asset, f"{tf}_deep"))*barh/24
            flag = " <== PROFIT" if m['netR'] > 0 and m['pf'] > 1.05 and oos.endswith("OK") else ""
            print(f"{asset} {name:<14} T={m['trades']:>3} {m['trades']/days:>4.1f}/day WR={m['wr']:>2.0f}% netR={m['netR']:>6.1f} PF={m['pf']:>5.2f} h1/h2={oos}{flag}")
