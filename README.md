# TradePulse — Live Strategy Signals & Leaderboard

Real-time crypto chart (TradingView Lightweight Charts) with **Donchian 20 + MA100 strategy signals** overlaid, plus a **multi-asset performance leaderboard** backtested on live Binance data — entirely in your browser. No API key, no server, no build step.

🔗 **Live:** https://0xshaikh.github.io/trade-pulse/

## Features

- 📈 **Live candlestick chart** (TradingView Lightweight Charts v4) — real-time updates via Binance WebSocket
- 🎯 **Strategy signals** — Donchian 20 breakout with MA100 trend filter; BUY/SELL markers on the chart
- 📊 **Live strategy stats** — win rate, trades, net return, profit factor (computed on closed bars)
- 🏆 **Leaderboard** — 12 assets ranked by strategy backtest return on live 1H data; click a row to load that chart
- 🔄 **Asset + timeframe switcher** — BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, LTC, DOT, MATIC · 15m/1H/4H/1D

## Strategy

- **Entry:** close breaks above Donchian 20 high (long) or below Donchian 20 low (short), *only* in the direction of the MA100 slope
- **Exit:** 2×ATR stop · 3×ATR target · opposite Donchian channel touch
- **Discipline:** signals computed on **closed bars only** (no in-progress-bar trading), net of ~0.04% round-trip cost

## Data

- REST: `https://api.binance.com/api/v3/klines` (history)
- WebSocket: `wss://stream.binance.com:9443/ws/<sym>@kline_<tf>` (live)
- Public Binance API — no key required, CORS-open

## Run locally

```bash
cd site && python3 -m http.server 8000
# open http://localhost:8000
```

## Stack

- Vanilla HTML/CSS/JS (no framework, no build step)
- TradingView Lightweight Charts v4 (CDN)
- GitHub Pages

> ⚠️ Educational tool — not financial advice. Past performance does not guarantee future results.
