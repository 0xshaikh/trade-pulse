#!/usr/bin/env python3
"""Fetch deep 15M data (~6000 bars, paged) for XAUUSDT + BTCUSDT. Matching existing format."""
import json, time, urllib.request

RES = "/home/ubuntu/trade-pulse/research"
BASE = "https://fapi.binance.com/fapi/v1/klines"
SYMS = ["XAUUSDT", "BTCUSDT"]
TARGET = 6000

def fetch_paged(sym, target):
    out = []
    end = None  # latest
    while len(out) < target:
        url = f"{BASE}?symbol={sym}&interval=15m&limit=1500"
        if end: url += f"&endTime={end}"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            rows = json.loads(r.read().decode())
        if not rows: break
        batch = [{"time": int(k[0])//1000, "open": float(k[1]), "high": float(k[2]),
                  "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in rows]
        out = batch + out  # prepend (older)
        end = rows[0][0] - 1
        if len(rows) < 1500: break
        time.sleep(0.3)
    return out[-target:]

for s in SYMS:
    d = fetch_paged(s, TARGET)
    json.dump(d, open(f"{RES}/{s}_15m_deep.json", "w"))
    print(f"{s}: {len(d)} bars, first={d[0]['time']} last={d[-1]['time']}, vol[0]={d[0]['volume']:.1f}")
