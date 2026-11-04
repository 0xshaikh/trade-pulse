#!/usr/bin/env python3
"""
Evidence-first strategy grid search for Trade-Pulse.
Frozen harness: Binance USDT-M futures 4h, 600 bars, taker cost 0.0010 round-trip,
1R stop (2xATR) / 3R target, closed-bar fills, look-ahead-safe breakout.
Every candidate differs ONLY by signal rule. Each candidate gets:
  per-asset trades/WR/avgR/PF/netR + assets-positive count + half-split regime test.
"""
import json, math, os, sys
from itertools import product

RES = "/home/ubuntu/trade-pulse/research"
COST = 0.0010  # taker round-trip

ASSETS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
          "LTCUSDT","LINKUSDT","MATICUSDT","AVAXUSDT","DOTUSDT","XAUUSDT","XAGUSDT"]

def load(asset, tf):
    p = f"{RES}/{asset}_{tf}.json"
    if not os.path.exists(p): return None
    return json.load(open(p))

# ---------- indicators (pure, no look-ahead) ----------
def sma(v, n):
    o = [None]*len(v); s = 0.0
    for i in range(len(v)):
        s += v[i]
        if i >= n: s -= v[i-n]
        if i >= n-1: o[i] = s/n
    return o

def ema(v, n):
    o = [None]*len(v); k = 2/(n+1); e = None
    for i in range(len(v)):
        if i == 0: e = v[0]
        else: e = v[i]*k + e*(1-k)
        o[i] = e
    return o

def rsi(v, n=14):
    o = [None]*len(v); g = 0.0; l = 0.0
    for i in range(len(v)):
        if i == 0:
            o[i] = 50.0; continue
        ch = v[i]-v[i-1]
        up = max(ch,0); dn = max(-ch,0)
        if i <= n:
            g += up; l += dn
            if i == n:
                g /= n; l /= n
                o[i] = 100 - 100/(1 + (g/l if l>0 else 1e9))
        else:
            g = (g*(n-1)+up)/n; l = (l*(n-1)+dn)/n
            o[i] = 100 - 100/(1 + (g/l if l>0 else 1e9))
    return o

def atr(kl, n=14):
    o = [None]*len(kl)
    for i in range(len(kl)):
        if i < n: continue
        s = 0.0
        for j in range(i-n+1, i+1):
            h = kl[j]['high']; l = kl[j]['low']; pc = kl[j-1]['close']
            s += max(h-l, abs(h-pc), abs(l-pc))
        o[i] = s/n
    return o

def donch(kl, n):
    up = [None]*len(kl); lo = [None]*len(kl)
    for i in range(len(kl)):
        if i < n-1: continue
        up[i] = max(kl[j]['high'] for j in range(i-n+1, i+1))
        lo[i] = min(kl[j]['low'] for j in range(i-n+1, i+1))
    return up, lo

def adx(kl, n=14):
    # Wilder ADX
    plus = [None]*len(kl); minus = [None]*len(kl); dx = [None]*len(kl)
    tr_s = [0.0]*len(kl); pdm_s = [0.0]*len(kl); ndm_s = [0.0]*len(kl)
    for i in range(1, len(kl)):
        h = kl[i]['high']; l = kl[i]['low']; ph = kl[i-1]['high']; pl = kl[i-1]['low']; pc = kl[i-1]['close']
        tr = max(h-l, abs(h-pc), abs(l-pc))
        pdm = max(h-ph, 0) if h-ph > pl-l else 0
        ndm = max(pl-l, 0) if pl-l > h-ph else 0
        if i <= n:
            tr_s[i] = tr_s[i-1]+tr; pdm_s[i] = pdm_s[i-1]+pdm; ndm_s[i] = ndm_s[i-1]+ndm
            if i == n:
                tr_s[i]/=n; pdm_s[i]/=n; ndm_s[i]/=n
                if tr_s[i] > 0:
                    plus[i] = 100*pdm_s[i]/tr_s[i]; minus[i] = 100*ndm_s[i]/tr_s[i]
                    dx[i] = 100*abs(plus[i]-minus[i])/(plus[i]+minus[i] if plus[i]+minus[i]>0 else 1)
        else:
            tr_s[i] = (tr_s[i-1]*(n-1)+tr)/n
            pdm_s[i] = (pdm_s[i-1]*(n-1)+pdm)/n
            ndm_s[i] = (ndm_s[i-1]*(n-1)+ndm)/n
            if tr_s[i] > 0:
                plus[i] = 100*pdm_s[i]/tr_s[i]; minus[i] = 100*ndm_s[i]/tr_s[i]
                d = 100*abs(plus[i]-minus[i])/(plus[i]+minus[i] if plus[i]+minus[i]>0 else 1)
                dx[i] = d
    # ADX = smoothed DX
    adx_ = [None]*len(kl); s = 0.0
    for i in range(len(kl)):
        if dx[i] is None: continue
        if i < 2*n: continue
        if i == 2*n:
            s = sum(dx[j] for j in range(i-n+1, i+1))/n
        else:
            s = (s*(n-1)+dx[i])/n
        adx_[i] = s
    return adx_

def macd(v, fast=12, slow=26, sig=9):
    ef = ema(v, fast); es = ema(v, slow)
    line = [ (ef[i]-es[i]) if ef[i] is not None and es[i] is not None else None for i in range(len(v)) ]
    sigv = [None]*len(v)
    # EMA of line where defined
    s = None; cnt = 0
    for i in range(len(v)):
        if line[i] is None: continue
        if s is None: s = line[i]; cnt = 1
        else:
            k = 2/(sig+1); s = line[i]*k + s*(1-k); cnt += 1
        if cnt >= sig: sigv[i] = s
    return line, sigv

# ---------- backtest engine (frozen) ----------
def backtest(kl, cfg, daily=None, daily_ma_n=200):
    """
    cfg: dict of signal params. Signal function returns +1/-1/0 at bar i (0=no entry).
    Entries on close[i] AFTER closed-bar signal; exit next bars.
    Stop = entry -/+ 2*ATR (1R), target = entry +/- 3*ATR (3R). Channel exit on Donchian 10.
    """
    n = len(kl)
    close = [k['close'] for k in kl]
    A = atr(kl, cfg.get('atr_n',14))
    DU, DL = donch(kl, cfg['dc_n'])
    DUx, DLx = donch(kl, cfg.get('dcx_n',10))
    MA = sma(close, cfg['ma_n'])
    RS = rsi(close, 14)
    AD = adx(kl, 14) if cfg.get('use_adx') else None
    MACL, MACS = (macd(close) if cfg.get('use_macd') else (None,None))
    # daily gate
    dclose = None; dma = None; dma2 = None
    if daily is not None and cfg.get('use_daily_gate'):
        dclose = [k['close'] for k in daily]
        dma = sma(dclose, cfg.get('daily_ma_n', daily_ma_n))
    vol = [k.get('volume', None) for k in kl]
    # vol MA
    volma = None
    if cfg.get('use_vol') and any(v is not None for v in vol):
        vs = [ (v if v is not None else 0) for v in vol ]
        volma = sma(vs, cfg.get('vol_n',20))
    EMA20 = ema(close, 20) if cfg.get('use_ema') else None
    EMA50 = ema(close, 50) if cfg.get('use_ema') else None
    warm = max(cfg['dc_n'], cfg['ma_n'], cfg.get('atr_n',14), cfg.get('dcx_n',10), 20) + 5

    trades = []
    pos = None
    for i in range(1, n):
        # exit open position first
        if pos:
            b = kl[i]; ex = None; rsn = None
            if pos['dir'] == 1:
                if b['low'] <= pos['stop']: ex = pos['stop']; rsn = 'stop'
                elif pos['tp'] is not None and b['high'] >= pos['tp']: ex = pos['tp']; rsn = 'target'
                elif b['close'] < DLx[i]: ex = b['close']; rsn = 'chan'
            else:
                if b['high'] >= pos['stop']: ex = pos['stop']; rsn = 'stop'
                elif pos['tp'] is not None and b['low'] <= pos['tp']: ex = pos['tp']; rsn = 'target'
                elif b['close'] > DUx[i]: ex = b['close']; rsn = 'chan'
            if ex is not None:
                t = pos
                t['exit'] = ex; t['rsn'] = rsn; t['time'] = b['time']
                gross = (ex - t['entry'])/t['entry'] * t['dir']
                t['net'] = gross - COST
                t['r'] = (t['net']*t['entry']) / t['risk_amt'] if t['risk_amt']>0 else 0
                trades.append(t)
                pos = None
        if i < warm: continue
        if pos: continue
        if MA[i] is None or A[i] is None or DU[i] is None or DU[i-1] is None: continue
        # ---- signal rules ----
        sig = 0
        d = None
        # breakout direction
        pc = close[i-1]
        slope = (MA[i]-MA[i-5])/pc*100 if pc>0 and MA[i-5] is not None else 0
        if cfg.get('use_chop') and abs(slope) < cfg['min_slope']: sig = 0
        else:
            if pc <= DU[i-1] and close[i] > DU[i-1] and close[i] > MA[i]:
                d = 1
                if cfg.get('require_above_ma') and slope <= 0: d = 0
            elif pc >= DL[i-1] and close[i] < DL[i-1] and close[i] < MA[i]:
                d = -1
                if cfg.get('require_above_ma') and slope >= 0: d = 0
        if d == 0 or d is None: continue
        # momentum filters
        if d == 1:
            if cfg.get('use_rsi') and RS[i] is not None and RS[i] < cfg['rsi_min']: continue
            if cfg.get('use_adx') and AD[i] is not None and AD[i] < cfg['adx_min']: continue
            if cfg.get('use_macd') and MACL[i] is not None and MACS[i] is not None and MACL[i] <= MACS[i]: continue
            if cfg.get('use_vol') and volma is not None and volma[i] is not None and vol[i] is not None and vol[i] < volma[i]*cfg.get('vol_mult',1.0): continue
            if cfg.get('use_ema') and (EMA20[i] is None or EMA50[i] is None or close[i] <= EMA20[i] or EMA20[i] <= EMA50[i]): continue
        else:
            if cfg.get('use_rsi') and RS[i] is not None and RS[i] > 100-cfg['rsi_min']: continue
            if cfg.get('use_adx') and AD[i] is not None and AD[i] < cfg['adx_min']: continue
            if cfg.get('use_macd') and MACL[i] is not None and MACS[i] is not None and MACL[i] >= MACS[i]: continue
            if cfg.get('use_vol') and volma is not None and volma[i] is not None and vol[i] is not None and vol[i] < volma[i]*cfg.get('vol_mult',1.0): continue
            if cfg.get('use_ema') and (EMA20[i] is None or EMA50[i] is None or close[i] >= EMA20[i] or EMA20[i] >= EMA50[i]): continue
        # ATR regime band (skip dead-vol / blow-off chop)
        if cfg.get('atr_band'):
            lo, hi = cfg['atr_band']
            atrp = A[i]/close[i]*100
            if atrp < lo or atrp > hi: continue
        # daily regime gate
        if daily is not None and cfg.get('use_daily_gate'):
            ts = kl[i]['time']
            idx = -1
            for j in range(len(daily)):
                if daily[j]['time'] <= ts: idx = j
                else: break
            if idx < daily_ma_n - 1 or dma[idx] is None: 
                if cfg.get('strict_gate'): continue
                # else neutral -> allow
            else:
                dc = dclose[idx]; dm = dma[idx]
                if d == 1 and dc <= dm: continue
                if d == -1 and dc >= dm: continue
        # enter
        e = close[i]; sd = cfg.get('stop_mult',2.0)*A[i] if A[i] is not None else None
        if sd is None or sd <= 0 or e <= 0: continue
        pos = {'dir': d, 'entry': e, 'risk_amt': sd,
               'stop': e - d*sd,
               'tp': (e + d*cfg.get('tp_mult',3.0)*sd) if cfg.get('tp_mult') else None,
               'ti': i}
    return trades

def metrics(trades):
    if not trades: return dict(trades=0, wr=0, avgR=0, pf=0, netR=0, avgNet=0)
    wins = [t for t in trades if t['net'] > 0]
    losses = [t for t in trades if t['net'] <= 0]
    gp = sum(t['net'] for t in wins); gl = -sum(t['net'] for t in losses)
    netR = sum(t['r'] for t in trades)
    return dict(trades=len(trades), wr=100*len(wins)/len(trades),
                avgR=netR/len(trades), pf=(gp/gl if gl>0 else 999.0),
                netR=netR, avgNet=sum(t['net'] for t in trades)/len(trades))

def run_candidate(cfg, name, tf='4h', bars=600, verbose=False):
    total_t = 0; total_net = 0.0; total_r = 0.0; pos_count = 0
    per = {}
    half_pos = 0; half_checked = 0
    for a in ASSETS:
        kl = load(a, tf)
        if kl is None: continue
        kl = kl[-bars:]
        daily = load(a, '1d')
        tr = backtest(kl, cfg, daily)
        m = metrics(tr)
        per[a] = m
        total_t += m['trades']; total_net += m['netR']; total_r += m['netR']
        if m['netR'] > 0: pos_count += 1
        # half-split
        if m['trades'] >= 6:
            half = len(tr)//2
            h1 = metrics(tr[:half]); h2 = metrics(tr[half:])
            if h1['netR'] > 0 and h2['netR'] > 0: half_pos += 1
            half_checked += 1
    return dict(name=name, cfg=cfg, per=per, total_t=total_t, netR=total_net,
                pos_count=pos_count, half_pos=half_pos, half_checked=half_checked)

# ---------- candidate matrix ----------
def build_matrix():
    cands = []
    # baseline = current live strategy (Donchian20 + MA100 + chop 0.10 + daily MA200 gate)
    base = dict(dc_n=20, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
                use_chop=True, min_slope=0.10, use_daily_gate=True, daily_ma_n=200,
                strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False)
    cands.append(("BASE_current", base))
    # 1. ADX trend-strength filter (kill chop by strength, not just slope)
    for adx_min in (18, 22, 25):
        c = dict(base); c.update(use_adx=True, adx_min=adx_min)
        cands.append((f"ADX{adx_min}", c))
    # 2. RSI momentum filter
    for rsi_min in (45, 50):
        c = dict(base); c.update(use_rsi=True, rsi_min=rsi_min)
        cands.append((f"RSI{rsi_min}", c))
    # 3. MACD confirmation
    c = dict(base); c.update(use_macd=True)
    cands.append(("MACD", c))
    # 4. ADX + RSI combo
    c = dict(base); c.update(use_adx=True, adx_min=22, use_rsi=True, rsi_min=48)
    cands.append(("ADX22_RSI48", c))
    # 5. Volume confirmation
    c = dict(base); c.update(use_vol=True, vol_mult=1.0)
    cands.append(("VOL", c))
    # 6. Tighter chop
    for ms in (0.05, 0.15):
        c = dict(base); c.update(min_slope=ms)
        cands.append((f"CHOP{ms}", c))
    # 7. Different MA trend filter
    for mn in (50, 200):
        c = dict(base); c.update(ma_n=mn)
        cands.append((f"MA{mn}", c))
    # 8. Different Donchian
    for dn in (10, 30):
        c = dict(base); c.update(dc_n=dn)
        cands.append((f"DC{dn}", c))
    # 9. Different stop/target (risk profile)
    for sm, tm in ((1.5,2.5),(2.0,4.0),(2.5,3.0)):
        c = dict(base); c.update(stop_mult=sm, tp_mult=tm)
        cands.append((f"S{sm}T{tm}", c))
    # 10. EMA confluence (trend stack)
    c = dict(base); c.update(use_ema=True)
    cands.append(("EMA_STACK", c))
    # 11. ATR regime gate (only trade when ATR% within band -> no dead-vol chop)
    #    handled by atr_band flag
    for lo, hi in ((0.5,3.0),(0.8,2.5)):
        c = dict(base); c.update(atr_band=(lo,hi))
        cands.append((f"ATRBAND{lo}_{hi}", c))
    return cands

def run_all():
    cands = build_matrix()
    out = []
    for name, cfg in cands:
        r = run_candidate(cfg, name)
        out.append(r)
    # sort by: both-halves positive count, then netR
    out.sort(key=lambda r: (r['half_pos'], r['netR']), reverse=True)
    print(f"{'candidate':<20}{'T':>5}{'netR':>8}{'PF':>7}{'WR%':>6}{'+assets':>8}{'+halves':>8}")
    for r in out:
        print(f"{r['name']:<20}{r['total_t']:>5}{r['netR']:>8.1f}{'-':>7}{'-':>6}{r['pos_count']:>8}{r['half_pos']:>6}/{r['half_checked']}")
    return out

if __name__ == "__main__":
    run_all()
