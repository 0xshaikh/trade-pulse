#!/usr/bin/env python3
"""Fetch deep 1h data (3000 bars = 125 days) for XAUUSDT+BTCUSDT, then validate the
1h S/R reclaim + 1:2 scale-out winner per-asset + robustness sweep (S/R window, TP sets)."""
import json, sys, time, urllib.request
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
RES = "/home/ubuntu/trade-pulse/research"
BASE = "https://fapi.binance.com/fapi/v1/klines"

def fetch_paged(sym, tf, target):
    out = []; end = None
    while len(out) < target:
        url = f"{BASE}?symbol={sym}&interval={tf}&limit=1500"
        if end: url += f"&endTime={end}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            rows = json.loads(r.read().decode())
        if not rows: break
        batch = [{"time": int(k[0])//1000, "open": float(k[1]), "high": float(k[2]),
                  "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in rows]
        out = batch + out
        end = rows[0][0] - 1
        if len(rows) < 1500: break
        time.sleep(0.3)
    return out[-target:]

for s in ("XAUUSDT", "BTCUSDT"):
    d = fetch_paged(s, "1h", 3000)
    json.dump(d, open(f"{RES}/{s}_1h_deep.json", "w"))
    print(f"{s}: {len(d)} 1h bars")

# ---- validate winner ----
from grid_search import load, atr, sma, metrics
from round14_scaleout_tf import run_scale, s_sr, get_data

SLIP = 0.0002; FUND_8H = 0.0001; TAKER = 0.0005
def run_asset(asset, kl, tps, sizes, n_sr, stop_mult=2.0):
    A = atr(kl, 14)
    sig = s_sr(kl, n=n_sr)
    tr = run_scale(kl, A, sig, tps, sizes, stop_mult, TAKER, 1.0)
    for t in tr: t['asset'] = asset
    return tr

def msum(tr):
    m = metrics(tr)
    times = sorted(t['time'] for t in tr)
    oos = "-"
    if times and len(tr) >= 20:
        med = times[len(times)//2]
        h1 = metrics([t for t in tr if t['time'] <= med]); h2 = metrics([t for t in tr if t['time'] > med])
        oos = f"{h1['netR']:>5.1f}/{h2['netR']:>5.1f}" + (" OK" if (h1['netR'] > 0 and h2['netR'] > 0) else " X")
    return m, oos

print("\n=== VALIDATE 1h S/R reclaim + 1:2 scale-out (TP=[1,1.5,2]R sizes=[.4,.3,.3]) ===")
print("="*100)
for asset in ("XAUUSDT", "BTCUSDT"):
    for n in (15, 20, 25, 30):
        for klfile in (f"{asset}_1h_deep", f"{asset}_1h"):
            kl = load(asset, "1h_deep") if "deep" in klfile else load(asset, "1h")
            if kl is None: continue
            tr = run_asset(asset, kl, [1.0, 1.5, 2.0], [0.4, 0.3, 0.3], n)
            m, oos = msum(tr)
            days = len(kl)/24
            print(f"{asset} n={n} ({len(kl)} bars): T={m['trades']:>3} {m['trades']/days:.1f}/day WR={m['wr']:>2.0f}% netR={m['netR']:>6.1f} PF={m['pf']:>5.2f} h1/h2={oos}")
            break
print("\n=== COMBINED (gold+BTC, deep 1h) — winner config sweep ===")
for n in (15, 20, 25, 30):
    for tps, sizes, lab in (([1.0,1.5,2.0],[0.4,0.3,0.3],"1:2"), ([1.0,1.5,2.5],[0.4,0.3,0.3],"1:2.5"), ([1.0,1.5,3.0],[0.4,0.3,0.3],"1:3")):
        alltr = []
        for asset in ("XAUUSDT", "BTCUSDT"):
            kl = load(asset, "1h_deep")
            if kl is None: continue
            alltr += run_asset(asset, kl, tps, sizes, n)
        m, oos = msum(alltr)
        days = 2*3000/24
        print(f"n={n} {lab}: T={m['trades']:>3} {m['trades']/days:.1f}/day WR={m['wr']:>2.0f}% netR={m['netR']:>6.1f} PF={m['pf']:>5.2f} h1/h2={oos}")
