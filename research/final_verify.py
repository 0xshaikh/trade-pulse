#!/usr/bin/env python3
"""FINAL winner verification: ATRband+chop05 — per-asset, halves, exit mix, concentration."""
import json, os, sys
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, metrics, ASSETS
from round4_trail import backtest_trail

def base(**kw):
    c = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
             use_chop=True, min_slope=0.05, use_daily_gate=True, daily_ma_n=200,
             strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
             use_ema=False, atr_band=(0.5,3.0), trail=False)
    c.update(kw); return c

if __name__ == "__main__":
    cfg = base()
    print(f"{'asset':<10}{'T':>4}{'WR%':>6}{'netR':>8}{'PF':>6}{'avgR':>7}  stops target chan  h1R  h2R")
    tot=0; net=0; pos=0; both=0; checked=0; stops=0; tgts=0; chans=0
    allt=[]
    for a in ASSETS:
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        tr=backtest_trail(kl,cfg,daily); m=metrics(tr)
        h=len(tr)//2; m1=metrics(tr[:h]); m2=metrics(tr[h:])
        ns=sum(1 for t in tr if t['rsn']=='stop'); nt=sum(1 for t in tr if t['rsn']=='target'); nc=sum(1 for t in tr if t['rsn']=='chan')
        stops+=ns; tgts+=nt; chans+=nc; tot+=m['trades']; net+=m['netR']
        if m['netR']>0: pos+=1
        if m['trades']>=6:
            if m1['netR']>0 and m2['netR']>0: both+=1
            checked+=1
        allt+=tr
        print(f"{a:<10}{m['trades']:>4}{m['wr']:>6.0f}{m['netR']:>8.1f}{m['pf']:>6.2f}{m['avgR']:>7.2f}  {ns:>5} {nt:>5} {nc:>5}  {m1['netR']:>5.1f} {m2['netR']:>5.1f}")
    print(f"\nTOTAL: {tot} trades netR={net:.1f} +{pos}/14 +both={both}/{checked}")
    print(f"EXIT: stop {stops} ({100*stops/tot:.0f}%) | target {tgts} ({100*tgts/tot:.0f}%) | chan {chans}")
    for rsn in ('stop','target','chan'):
        sub=[t['r'] for t in allt if t['rsn']==rsn]
        if sub:
            w=sum(1 for r in sub if r>0)
            print(f"  {rsn:>7}: n={len(sub):>3} avgR={sum(sub)/len(sub):+.2f} winRate={100*w/len(sub):.0f}%")
    # concentration
    per=[(a, metrics(backtest_trail(load(a,'4h')[-600:],cfg,load(a,'1d')) )['netR']) for a in ASSETS]
    per.sort(key=lambda x:-x[1])
    print(f"  Top1 {per[0][0]} {per[0][1]:.1f}R ({100*per[0][1]/net:.0f}%) | Top3 {sum(x[1] for x in per[:3]):.1f}R ({100*sum(x[1] for x in per[:3])/net:.0f}%)")
