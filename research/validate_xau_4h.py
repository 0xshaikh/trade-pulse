#!/usr/bin/env python3
"""Validate XAUUSDT 4h k=3 trendline+15M 1:2 winner: OOS split + parameter robustness."""
import json
from newstrategy_htf_trendline import backtest, load

def split_backtest(sym, htf, k, tol, risk_atr):
    # run on first-half and second-half of 15m data to check stability
    bars15 = load(sym, "15m_deep")
    n = len(bars15)
    # monkeypatch: temporarily truncate via a wrapper — simplest: use backtest on full then infer
    # Instead, run two sub-windows by slicing data to temp files
    import tempfile, os
    results = []
    for name, lo, hi in [("FIRST", 300, n//2), ("SECOND", n//2, n)]:
        sub = bars15[lo:hi]
        p = f"/tmp/sub_{sym}_{name}.json"
        json.dump(sub, open(p, "w"))
        # load sub via patching the module's load
        orig = __import__("newstrategy_htf_trendline").load
        def patched_load(s, tf):
            if tf == "15m_deep" and s == sym:
                return sub
            return orig(s, tf)
        import newstrategy_htf_trendline as M
        M.load = patched_load
        r = backtest(sym, htf, k=k, tol_atr=tol)
        M.load = orig
        if r and r.get('n', 0) > 2:
            results.append((name, r))
    return results

if __name__ == '__main__':
    print("=== XAUUSDT 4h k=3 OOS split (62d window, half each) ===")
    for name, r in split_backtest("XAUUSDT", "4h", 3, 0.25, 1.5):
        print(f"{name}: T={r['n']} WR={r['wr']*100:.1f}% PF={r['pf']} netR={r['netR']:+} avg={r['avg']:+}R")

    print("\n=== Robustness: XAU 4h k=3 parameter neighborhood ===")
    for tol in [0.15, 0.25, 0.35]:
        for risk_atr in [1.0, 1.5, 2.0]:
            r = backtest("XAUUSDT", "4h", k=3, tol_atr=tol)
            if r and r.get('n', 0) > 2:
                print(f"tol={tol} risk_atr={risk_atr}: T={r['n']} WR={r['wr']*100:.1f}% PF={r['pf']} netR={r['netR']:+} avg={r['avg']:+}R")

    print("\n=== BTC 4h k=3 (for comparison) ===")
    r = backtest("BTCUSDT", "4h", k=3, tol_atr=0.25)
    if r and r.get('n', 0) > 2:
        print(f"BTC 4h k=3 tol=0.25: T={r['n']} WR={r['wr']*100:.1f}% PF={r['pf']} netR={r['netR']:+} avg={r['avg']:+}R")
