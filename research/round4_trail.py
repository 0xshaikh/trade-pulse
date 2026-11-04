#!/usr/bin/env python3
"""Round 4: loss-reduction focus — trailing stop (profit lock) + ATR band combo.
The 'lost trade' the user means = stop-outs after giving back profit. Test:
  - DC10_MA100 (baseline winner)
  - + ATR band 0.5-3.0
  - + trailing stop (move stop to breakeven at 1R, trail at 1.5R by ATR)
  - + ATR band + trailing
  - + weak chop 0.05
"""
import json, os, sys
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, donch, sma, metrics, ASSETS

def base(**kw):
    c = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
             use_chop=False, min_slope=0.10, use_daily_gate=True, daily_ma_n=200,
             strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
             use_ema=False, atr_band=None, trail=False)
    c.update(kw); return c

def backtest_trail(kl, cfg, daily=None, daily_ma_n=200):
    """Same engine but with optional breakeven + trailing stop."""
    n=len(kl); close=[k['close'] for k in kl]
    A=atr(kl,cfg['atr_n']); DU,DL=donch(kl,cfg['dc_n']); DUx,DLx=donch(kl,cfg['dcx_n'])
    MA=sma(close,cfg['ma_n'])
    dclose=None; dma=None
    if daily is not None and cfg.get('use_daily_gate'):
        dclose=[k['close'] for k in daily]; dma=sma(dclose,cfg.get('daily_ma_n',daily_ma_n))
    warm=max(cfg['dc_n'],cfg['ma_n'],cfg.get('atr_n',14),cfg.get('dcx_n',10),20)+5
    trades=[]; pos=None
    for i in range(1,n):
        if pos:
            b=kl[i]; ex=None; rsn=None
            stop=pos['stop']
            # breakeven at 1R profit
            if cfg.get('trail'):
                gain=(b['close']-pos['entry'])*pos['dir']
                if gain >= pos['risk_amt'] and pos.get('be') is None:
                    pos['be']=pos['entry']
                    stop=pos['entry']
                elif pos.get('be') is not None:
                    trail_amt=cfg.get('trail_atr',1.5)*A[i]
                    stop=pos['entry'] + pos['dir']*(gain - trail_amt) if A[i] else stop
            if pos['dir']==1:
                if b['low']<=stop: ex=stop; rsn='stop'
                elif pos['tp'] is not None and b['high']>=pos['tp']: ex=pos['tp']; rsn='target'
                elif b['close']<DLx[i]: ex=b['close']; rsn='chan'
            else:
                if b['high']>=stop: ex=stop; rsn='stop'
                elif pos['tp'] is not None and b['low']<=pos['tp']: ex=pos['tp']; rsn='target'
                elif b['close']>DUx[i]: ex=b['close']; rsn='chan'
            if ex is not None:
                t=pos; t['exit']=ex; t['rsn']=rsn; t['time']=b['time']
                gross=(ex-t['entry'])/t['entry']*t['dir']; t['net']=gross-0.0010
                t['r']=(t['net']*t['entry'])/t['risk_amt'] if t['risk_amt']>0 else 0
                trades.append(t); pos=None
        if i<warm: continue
        if pos: continue
        if MA[i] is None or A[i] is None or DU[i] is None or DU[i-1] is None: continue
        d=None; pc=close[i-1]
        slope=(MA[i]-MA[i-5])/pc*100 if pc>0 and MA[i-5] is not None else 0
        if cfg.get('use_chop') and abs(slope)<cfg['min_slope']: d=0
        else:
            if pc<=DU[i-1] and close[i]>DU[i-1] and close[i]>MA[i]: d=1
            elif pc>=DL[i-1] and close[i]<DL[i-1] and close[i]<MA[i]: d=-1
        if d==0 or d is None: continue
        if cfg.get('atr_band'):
            lo,hi=cfg['atr_band']; atrp=A[i]/close[i]*100
            if atrp<lo or atrp>hi: continue
        if daily is not None and cfg.get('use_daily_gate'):
            ts=kl[i]['time']; idx=-1
            for j in range(len(daily)):
                if daily[j]['time']<=ts: idx=j
                else: break
            if idx<daily_ma_n-1 or dma[idx] is None:
                if cfg.get('strict_gate'): continue
            else:
                dc=dclose[idx]; dm=dma[idx]
                if d==1 and dc<=dm: continue
                if d==-1 and dc>=dm: continue
        e=close[i]; sd=cfg.get('stop_mult',2.0)*A[i] if A[i] is not None else None
        if sd is None or sd<=0 or e<=0: continue
        pos={'dir':d,'entry':e,'risk_amt':sd,'stop':e-d*sd,
             'tp':(e+d*cfg.get('tp_mult',3.0)*sd) if cfg.get('tp_mult') else None,'ti':i}
    return trades

def agg(cfg):
    alltr=[]
    for a in ASSETS:
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        tr=backtest_trail(kl,cfg,daily)
        for t in tr: t['asset']=a
        alltr+=tr
    times=sorted(t['time'] for t in alltr); med=times[len(times)//2]
    h1=[t for t in alltr if t['time']<=med]; h2=[t for t in alltr if t['time']>med]
    m1=metrics(h1); m2=metrics(h2); m=metrics(alltr)
    # per-asset both halves + positive
    both=0; checked=0; pos=0
    for a in ASSETS:
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        tr=backtest_trail(kl,cfg,daily); mm=metrics(tr)
        if mm['netR']>0: pos+=1
        if mm['trades']>=6:
            h=len(tr)//2; x=metrics(tr[:h]); y=metrics(tr[h:])
            if x['netR']>0 and y['netR']>0: both+=1
            checked+=1
    flag="✓" if (m1['netR']>0 and m2['netR']>0) else "✗"
    print(f"{'':3}{cfg['name']:<28} T={m['trades']:>3} netR={m['netR']:>6.1f} h1={m1['netR']:>6.1f} h2={m2['netR']:>6.1f} h1PF={m1['pf']:>5.2f} h2PF={m2['pf']:>5.2f} {flag} +both={both}/{checked} +pos={pos}/14 avgR={m['avgR']:+.2f}")
    return m

if __name__ == "__main__":
    print("Round 4: loss-reduction (trailing stop / ATR band / weak chop)")
    variants = [
        ("DC10_MA100 baseline", base()),
        ("+ATRband", base(atr_band=(0.5,3.0))),
        ("+trail", base(trail=True)),
        ("+ATRband+trail", base(atr_band=(0.5,3.0), trail=True)),
        ("+chop05", base(min_slope=0.05, use_chop=True)),
        ("+ATRband+chop05", base(atr_band=(0.5,3.0), min_slope=0.05, use_chop=True)),
        ("+ATRband+trail+chop05", base(atr_band=(0.5,3.0), trail=True, min_slope=0.05, use_chop=True)),
    ]
    for name, cfg in variants:
        cfg['name']=name
        agg(cfg)
