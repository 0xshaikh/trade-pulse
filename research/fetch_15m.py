#!/usr/bin/env python3
"""Fetch 15M Binance USDT-M futures klines WITH volume for all ASSETS.
Matching existing data format: [{'time','open','high','low','close','volume'}], epoch seconds.
1500 bars each (enough for mean-reversion / scalping sample).
"""
import json, os, time, urllib.request

RES = "/home/ubuntu/trade-pulse/research"
ASSETS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
          "LTCUSDT","LINKUSDT","MATICUSDT","AVAXUSDT","DOTUSDT","XAUUSDT","XAGUSDT"]
BASE = "https://fapi.binance.com/fapi/v1/klines"

def fetch(sym):
    url = f"{BASE}?symbol={sym}&interval=15m&limit=1500"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        rows = json.loads(r.read().decode())
    out = []
    for k in rows:
        # [openTime, open, high, low, close, volume, closeTime, ...]
        out.append({"time": int(k[0])//1000, "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])})
    return out

ok = 0; fail = []
for a in ASSETS:
    try:
        d = fetch(a)
        if len(d) < 500: fail.append((a, f"short {len(d)}")); continue
        json.dump(d, open(f"{RES}/{a}_15m.json", "w"))
        ok += 1
        print(f"{a}: {len(d)} bars, vol[0]={d[0].get('volume'):.1f}")
    except Exception as e:
        fail.append((a, str(e)[:60]))
    time.sleep(0.35)  # rate limit politeness
print(f"\nOK={ok} FAIL={len(fail)}")
for a, e in fail: print("  FAIL", a, e)
