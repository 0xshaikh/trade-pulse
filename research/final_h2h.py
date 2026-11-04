#!/usr/bin/env python3
"""Final head-to-head: DC10_MA100 no-chop vs ATR-band variant. Robustness + loss-cause.
Also: what does ATR band actually filter, per asset (which assets lose in dead-vol)."""
import json, os, sys
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, backtest, metrics, ASSETS

def base(**kw):
    c = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
             use_chop=False, min_slope=0.10, use_daily_gate=True, daily_ma_n=200,
             strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
             use_ema=False, atr_band=None)
    c.update(kw); return c

def per_asset(cfg, label):
    print(f"\n=== {label} ===")
    tot=0; net=0; pos=0; both=0; checked=0
    for a in ASSETS:
        kl = load(a,'4h')[-600:]; daily = load(a,'1d')
        tr = backtest(kl, cfg, daily); m = metrics(tr)
        h=len(tr)//2; m1=metrics(tr[:h]); m2=metrics(tr[h:])
        tot+=m['trades']; net+=m['netR']; pos+= 1 if m['netR']>0 else 0
        if m['trades']>=6 and m1['netR']>0 and m2['netR']>0: both+=1; checked+=1 if m['trades']>=6 else 0
        elif m['trades']>=6: checked+=1
        print(f"  {a:<10} T={m['trades']:>3} WR={m['wr']:>3.0f} netR={m['netR']:>6.1f} PF={m['pf']:>5.2f}  {m1['netR']:>5.1f}/{m2['netR']:>5.1f}")
    print(f"  TOTAL: {tot} trades netR={net:.1f} +{pos}/14 assets  +both={both}/{checked}")

if __name__ == "__main__":
    per_asset(base(), "DC10_MA100 (no chop) WINNER")
    per_asset(base(atr_band=(0.5,3.0)), "DC10_MA100 + ATR band 0.5-3.0")
    # ATR% profile of the losers: are DOT/DOGE/AVAX trades in dead-vol?
    print("\n=== ATR% at entry for net-negative assets (DOT, DOGE, AVAX) vs winner SOL ===")
    for a in ['DOTUSDT','DOGEUSDT','AVAXUSDT','SOLUSDT','LINKUSDT']:
        kl = load(a,'4h')[-600:]; daily = load(a,'1d')
        # compute ATR% series
        from grid_search import atr
        A = atr(kl,14)
        atrp = [ (A[i]/kl[i]['close']*100 if A[i] else None) for i in range(len(kl)) ]
        vals = [x for x in atrp if x is not None]
        print(f"  {a:<10} ATR% median={sorted(vals)[len(vals)//2]:.2f} p25={sorted(vals)[len(vals)//4]:.2f} p75={sorted(vals)[3*len(vals)//4]:.2f}")
