#!/usr/bin/env python3
"""Round 2: DC-centered matrix with AGGREGATE half-split (time-based) + per-asset."""
import json, os, sys
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, backtest, metrics, ASSETS, COST

def agg_halves(cfg, tf='4h', bars=600):
    """Pool all trades across assets; split by TIME (median bar time). Aggregate both halves."""
    alltr = []
    for a in ASSETS:
        kl = load(a, tf)
        if kl is None: continue
        kl = kl[-bars:]
        daily = load(a, '1d')
        tr = backtest(kl, cfg, daily)
        for t in tr: t['asset'] = a
        alltr += tr
    if not alltr: return dict(t=0, h1=0, h2=0, h1pf=0, h2pf=0, h1wr=0, h2wr=0, netR=0)
    times = sorted(t['time'] for t in alltr)
    med = times[len(times)//2]
    h1 = [t for t in alltr if t['time'] <= med]
    h2 = [t for t in alltr if t['time'] > med]
    m1 = metrics(h1); m2 = metrics(h2)
    return dict(t=len(alltr), h1=m1['netR'], h2=m2['netR'], h1pf=m1['pf'], h2pf=m2['pf'],
                h1wr=m1['wr'], h2wr=m2['wr'], netR=m1['netR']+m2['netR'], n1=len(h1), n2=len(h2))

def per_asset_halves(cfg, tf='4h', bars=600):
    both = 0; checked = 0; pos = 0; tot = 0; net = 0.0
    for a in ASSETS:
        kl = load(a, tf)
        if kl is None: continue
        kl = kl[-bars:]
        daily = load(a, '1d')
        tr = backtest(kl, cfg, daily)
        m = metrics(tr)
        tot += m['trades']; net += m['netR']
        if m['netR'] > 0: pos += 1
        if m['trades'] >= 6:
            half = len(tr)//2
            m1 = metrics(tr[:half]); m2 = metrics(tr[half:])
            if m1['netR'] > 0 and m2['netR'] > 0: both += 1
            checked += 1
    return dict(both=both, checked=checked, pos=pos, tot=tot, net=net)

def show(cfg, name):
    a = agg_halves(cfg); p = per_asset_halves(cfg)
    flag = "✓" if (a['h1']>0 and a['h2']>0) else "✗"
    print(f"{name:<22}{a['t']:>4}{a['netR']:>7.1f}{a['h1']:>7.1f}{a['h2']:>7.1f}{a['h1pf']:>6.2f}{a['h2pf']:>6.2f}{a['h1wr']:>5.0f}{a['h2wr']:>5.0f}  {flag}   {p['both']}/{p['checked']} {p['pos']}/{len(ASSETS)}")
    return a, p

def base(**kw):
    c = dict(dc_n=20, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
             use_chop=True, min_slope=0.10, use_daily_gate=True, daily_ma_n=200,
             strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
             use_ema=False, atr_band=None)
    c.update(kw); return c

if __name__ == "__main__":
    print(f"{'candidate':<22}{'T':>4}{'netR':>7}{'h1R':>7}{'h2R':>7}{'h1PF':>6}{'h2PF':>6}{'h1WR':>5}{'h2WR':>5}  2H+   +assets/+both +pos")
    results = []
    # DC10 family
    results.append(("DC10_MA100_chop", base(dc_n=10), show(base(dc_n=10),"DC10_MA100_chop")))
    results.append(("DC10_MA50", base(dc_n=10, ma_n=50), show(base(dc_n=10, ma_n=50),"DC10_MA50")))
    results.append(("DC10_chop05", base(dc_n=10, min_slope=0.05), show(base(dc_n=10, min_slope=0.05),"DC10_chop05")))
    results.append(("DC10_nochop", base(dc_n=10, use_chop=False), show(base(dc_n=10, use_chop=False),"DC10_nochop")))
    results.append(("DC10_MACD", base(dc_n=10, use_macd=True), show(base(dc_n=10, use_macd=True),"DC10_MACD")))
    results.append(("DC10_ADX20", base(dc_n=10, use_adx=True, adx_min=20), show(base(dc_n=10, use_adx=True, adx_min=20),"DC10_ADX20")))
    results.append(("DC10_EMA", base(dc_n=10, use_ema=True), show(base(dc_n=10, use_ema=True),"DC10_EMA")))
    results.append(("DC10_ATRB", base(dc_n=10, atr_band=(0.5,3.0)), show(base(dc_n=10, atr_band=(0.5,3.0)),"DC10_ATRB")))
    results.append(("DC10_dc5", base(dc_n=5), show(base(dc_n=5),"DC10_dc5")))
    results.append(("DC10_dc15", base(dc_n=15), show(base(dc_n=15),"DC10_dc15")))
    results.append(("DC10_T45", base(dc_n=10, stop_mult=2.0, tp_mult=4.5), show(base(dc_n=10, stop_mult=2.0, tp_mult=4.5),"DC10_T45")))
    results.append(("DC10_T40", base(dc_n=10, tp_mult=4.0), show(base(dc_n=10, tp_mult=4.0),"DC10_T40")))
    # BASE for reference
    results.append(("BASE_current", base(), show(base(),"BASE_current")))
