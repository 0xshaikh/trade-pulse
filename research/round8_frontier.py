#!/usr/bin/env python3
"""Round 8: THE FRONTIER — sweep target R-multiple on the winner. Find max WR at positive netR.
Shows the honest trade-off: as target shrinks (WR up), netR collapses through zero.
"""
import sys
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from round4_trail import backtest_trail
from grid_search import load, metrics, ASSETS

def agg(cfg):
    alltr=[]
    for a in ASSETS:
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        tr=backtest_trail(kl,cfg,daily)
        for t in tr:
            t['asset']=a; t['r']=(t['net']*t['entry'])/t['risk_amt'] if t['risk_amt']>0 else 0
        alltr+=tr
    return metrics(alltr), alltr

base = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0,
            use_chop=True, min_slope=0.05, use_daily_gate=True, daily_ma_n=200,
            strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
            use_ema=False, atr_band=(0.5,3.0), trail=False)

print("ROUND 8: THE WR-vs-netR FRONTIER (winner, sweep target R-multiple)")
print("tp_mult here = R-multiple directly (research engine: tp = entry + tp_mult*stop_dist)")
print("="*110)
print(f"{'TP (R)':>8} {'Trades':>7} {'WR%':>6} {'netR':>8} {'PF':>7} {'avgR':>7}  verdict")
for tp in [0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
    cfg = dict(base, tp_mult=tp)
    m,_ = agg(cfg)
    verdict = "✓ PROFITABLE" if m['netR']>0 else "✗ LOSES"
    print(f"{tp:>8.2f} {m['trades']:>7} {m['wr']:>6.0f} {m['netR']:>8.1f} {m['pf']:>7.2f} {m.get('avg',0):>+7.2f}  {verdict}")
