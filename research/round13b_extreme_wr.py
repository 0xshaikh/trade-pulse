#!/usr/bin/env python3
"""Round 13b: EXTREME HIGH-WR PUSH on XAUUSDT + BTCUSDT — drive WR to the 80% boundary.
Wider stops (3.5-5R) + tiny TP (0.15-0.3R), maker fee best case. Shows exactly what 80% WR costs.
"""
import sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, sma, ema, rsi, metrics
from round13_gold_btc import run15, load2, s_vwap, s_rsi, s_bb, s_sr, s_ema_pull

FAMS = [('EMApull', s_ema_pull), ('VWAP2.5', lambda kl: s_vwap(kl, k=2.5)), ('VWAP2.0', lambda kl: s_vwap(kl, k=2.0)),
        ('SR20', s_sr), ('RSI30', lambda kl: s_rsi(kl, 30, 70)), ('BB20', s_bb)]
TPS = [0.15, 0.2, 0.25, 0.3]
STOPS = [3.0, 3.5, 4.0, 5.0]
MAKER = 0.0002

print("ROUND 13b: EXTREME WR PUSH — XAUUSDT + BTCUSDT, maker 0.02%/side, 6000 bars")
print("="*120)
rows = []
for asset in ("XAUUSDT", "BTCUSDT"):
    kl, A = load2(asset)
    for name, fn in FAMS:
        sig = fn(kl)
        for tp in TPS:
            for stop in STOPS:
                tr = run15(kl, A, sig, tp, stop, None, MAKER)
                m = metrics(tr)
                times = sorted(t['time'] for t in tr)
                oos = "-"
                if times and len(tr) >= 30:
                    med = times[len(times)//2]
                    h1 = metrics([t for t in tr if t['time'] <= med]); h2 = metrics([t for t in tr if t['time'] > med])
                    oos = f"{h1['netR']:>6.1f}/{h2['netR']:>6.1f}" + (" OK" if (h1['netR'] > 0 and h2['netR'] > 0) else " X")
                rows.append((m['wr'], m['netR'], asset, name, tp, stop, m['trades'], m['pf'], oos))

print("--- top WR overall (any asset) ---")
for wr, netR, asset, name, tp, stop, T, pf, oos in sorted(rows, key=lambda x: -x[0])[:15]:
    tag = " [HIT]" if wr >= 80 and netR > 0 else (" [TRAP]" if wr >= 80 else "")
    print(f"WR={wr:>2.0f}% netR={netR:>8.1f} PF={pf:>4.2f} T={T:>4}  {asset} {name} TP={tp}R stop={stop}R  h1/h2={oos}{tag}")
print()
maxwr = max(rows, key=lambda x: x[0])
print(f"ABSOLUTE MAX WR found: {maxwr[0]:.0f}%  ({maxwr[2]} {maxwr[3]} TP={maxwr[4]}R stop={maxwr[5]}R) netR={maxwr[1]:.1f}")
print("configs with WR>=80:", len([r for r in rows if r[0] >= 80]), "| of those netR>0:", len([r for r in rows if r[0] >= 80 and r[1] > 0]))
