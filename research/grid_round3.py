#!/usr/bin/env python3
"""Round 3: refine DC10_nochop neighborhood — robust plateau, not single peak."""
import json, os, sys
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, backtest, metrics, ASSETS
from grid_round2 import agg_halves, per_asset_halves

def base(**kw):
    c = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
             use_chop=False, min_slope=0.10, use_daily_gate=True, daily_ma_n=200,
             strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
             use_ema=False, atr_band=None)
    c.update(kw); return c

if __name__ == "__main__":
    print(f"{'candidate':<20}{'T':>4}{'netR':>7}{'h1R':>7}{'h2R':>7}{'h1PF':>6}{'h2PF':>6}  2H+   +both/+assets +pos")
    tests = [
        ("DC10_MA100", base()),                                # reference
        ("DC8_MA100", base(dc_n=8)),
        ("DC12_MA100", base(dc_n=12)),
        ("DC10_MA75", base(ma_n=75)),
        ("DC10_MA150", base(ma_n=150)),
        ("DC10_dcx5", base(dcx_n=5)),
        ("DC10_dcx15", base(dcx_n=15)),
        ("DC10_dcx20", base(dcx_n=20)),
        ("DC10_T35", base(tp_mult=3.5)),
        ("DC10_T40", base(tp_mult=4.0)),
        ("DC10_S25", base(stop_mult=2.5)),
        ("DC10_S15", base(stop_mult=1.5)),
        ("DC10_dailyMA100", base(daily_ma_n=100)),
        ("DC10_dailyMA300", base(daily_ma_n=300)),
        ("DC10_strictgate", base(strict_gate=True)),
        ("DC10_MACD", base(use_macd=True)),
        ("DC10_ATRB", base(atr_band=(0.5,3.0))),
    ]
    for name, cfg in tests:
        a = agg_halves(cfg); p = per_asset_halves(cfg)
        flag = "✓" if (a['h1']>0 and a['h2']>0) else "✗"
        print(f"{name:<20}{a['t']:>4}{a['netR']:>7.1f}{a['h1']:>7.1f}{a['h2']:>7.1f}{a['h1pf']:>6.2f}{a['h2pf']:>6.2f}  {flag}   {p['both']}/{p['checked']} {p['pos']}/{len(ASSETS)}")
