#!/usr/bin/env python3
"""Winner verification: per-asset detail + loss attribution + not-one-asset-driven."""
import json, os, sys
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, backtest, metrics, ASSETS

def base(**kw):
    c = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
             use_chop=False, min_slope=0.10, use_daily_gate=True, daily_ma_n=200,
             strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
             use_ema=False, atr_band=None)
    c.update(kw); return c

if __name__ == "__main__":
    cfg = base()
    print(f"{'asset':<10}{'T':>4}{'WR%':>6}{'netR':>8}{'PF':>6}{'avgR':>7}  exit-stops target chan  h1R  h2R")
    tot = 0; net = 0; stops = 0; tgts = 0; chans = 0; pos = 0
    asset_nets = []
    for a in ASSETS:
        kl = load(a, '4h'); kl = kl[-600:]
        daily = load(a, '1d')
        tr = backtest(kl, cfg, daily)
        m = metrics(tr)
        h = len(tr)//2
        m1 = metrics(tr[:h]); m2 = metrics(tr[h:])
        ns = sum(1 for t in tr if t['rsn']=='stop'); nt = sum(1 for t in tr if t['rsn']=='target'); nc = sum(1 for t in tr if t['rsn']=='chan')
        stops+=ns; tgts+=nt; chans+=nc; tot+=m['trades']; net+=m['netR']
        if m['netR']>0: pos+=1
        asset_nets.append((a, m['netR']))
        print(f"{a:<10}{m['trades']:>4}{m['wr']:>6.0f}{m['netR']:>8.1f}{m['pf']:>6.2f}{m['avgR']:>7.2f}  {ns:>5} {nt:>6} {nc:>5}  {m1['netR']:>5.1f} {m2['netR']:>5.1f}")
    print(f"\nTOTAL: {tot} trades, netR {net:.1f}, {pos}/14 assets positive")
    print(f"EXIT MIX: stop {stops} ({100*stops/tot:.0f}%) | target {tgts} ({100*tgts/tot:.0f}%) | channel {chans} ({100*chans/tot:.0f}%)")
    # concentration check
    asset_nets.sort(key=lambda x: -x[1])
    top1 = asset_nets[0][1]; top3 = sum(x[1] for x in asset_nets[:3])
    print(f"Top asset {asset_nets[0][0]} contributes {top1:.1f}R ({100*top1/net:.0f}% of net)")
    print(f"Top-3 assets contribute {top3:.1f}R ({100*top3/net:.0f}% of net)")
    # loss attribution: avg R by exit reason
    allt = []
    for a in ASSETS:
        kl = load(a, '4h'); kl = kl[-600:]
        daily = load(a, '1d')
        allt += backtest(kl, cfg, daily)
    for rsn in ('stop','target','chan'):
        sub = [t['r'] for t in allt if t['rsn']==rsn]
        if sub:
            wins = sum(1 for r in sub if r>0)
            print(f"  {rsn:>7}: n={len(sub):>3} avgR={sum(sub)/len(sub):+.2f} winRate={100*wins/len(sub):.0f}%")
