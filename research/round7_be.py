#!/usr/bin/env python3
"""Round 7: BREAKEVEN-STOP variants on the winner — the legitimate 'raise WR without killing edge' move.
Winner: DC10+MA100+chop0.05+ATR band+daily gate, 1R stop/3R target.
Variant: move SL to breakeven when price reaches +1R (BE trigger). Counts scratches as 'non-loss'.
Also test: BE at +1R AND trail to +0.5R, BE at +1.5R. Compare vs baseline full 3R.
"""
import sys, json
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from round4_trail import backtest_trail
from grid_search import load, metrics, ASSETS

def backtest_be(kl, cfg, daily=None, be_trigger=1.0, be_lock=0.0):
    """Like backtest_trail but move SL to breakeven (+be_lock) when price reaches be_trigger*risk in favor."""
    import numpy as np
    # Reuse the same signal logic as round4_trail by importing its internals is fragile;
    # replicate the entry/filter logic here with the BE exit modification.
    from grid_search import atr, donch, sma
    n=len(kl); close=[k['close'] for k in kl]
    A=atr(kl,cfg['atr_n']); DU,DL=donch(kl,cfg['dc_n']); DUx,DLx=donch(kl,cfg['dcx_n'])
    MA=sma(close,cfg['ma_n'])
    dclose=None; dma=None
    if daily is not None and cfg.get('use_daily_gate'):
        dclose=[k['close'] for k in daily]; dma=sma(dclose,cfg.get('daily_ma_n',200))
    warm=max(cfg['dc_n'],cfg['ma_n'],cfg.get('atr_n',14),cfg.get('dcx_n',10),20)+5
    trades=[]; pos=None
    for i in range(1,n):
        if pos:
            b=kl[i]; ex=None; rsn=None; dir=pos['dir']; entry=pos['entry']; stop=pos['stop']; risk=pos['risk_amt']
            # BE trigger: if high/low touched be_trigger*risk in favor, ratchet stop
            if not pos.get('be_done'):
                fav = (b['high']-entry)*dir if dir==1 else (entry-b['low'])*dir
                if fav >= be_trigger*risk:
                    stop = entry + dir*be_lock*risk
                    pos['stop']=stop; pos['be_done']=True
            if dir==1:
                if b['low']<=stop: ex=stop; rsn='stop'
                elif pos['tp'] is not None and b['high']>=pos['tp']: ex=pos['tp']; rsn='target'
                elif b['close']<DLx[i]: ex=b['close']; rsn='chan'
            else:
                if b['high']>=stop: ex=stop; rsn='stop'
                elif pos['tp'] is not None and b['low']<=pos['tp']: ex=pos['tp']; rsn='target'
                elif b['close']>DUx[i]: ex=b['close']; rsn='chan'
            if ex is not None:
                gross=(ex-entry)/entry*dir; net=gross-0.0010
                trades.append({'dir':dir,'entry':entry,'exit':ex,'net':net,'rsn':rsn,'time':b['time'],'risk_amt':risk})
                pos=None
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
            if idx<cfg.get('daily_ma_n',200)-1 or dma[idx] is None:
                if cfg.get('strict_gate'): continue
            else:
                dc=dclose[idx]; dm=dma[idx]
                if d==1 and dc<=dm: continue
                if d==-1 and dc>=dm: continue
        e=close[i]; sd=cfg.get('stop_mult',2.0)*A[i] if A[i] is not None else None
        if sd is None or sd<=0 or e<=0: continue
        pos={'dir':d,'entry':e,'risk_amt':sd,'stop':e-d*sd,
             'tp':(e+d*cfg.get('tp_mult',3.0)*sd) if cfg.get('tp_mult') else None,'ti':i,'be_done':False}
    return trades

def agg(cfg, be_trigger=None, be_lock=0.0, label=""):
    alltr=[]
    for a in ASSETS:
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        if be_trigger is None:
            tr=backtest_trail(kl,cfg,daily)
        else:
            tr=backtest_be(kl,cfg,daily,be_trigger,be_lock)
        for t in tr:
            t['asset']=a; t['r']=(t['net']*t['entry'])/t['risk_amt'] if t['risk_amt']>0 else 0
        alltr+=tr
    m=metrics(alltr)
    # count wins, losses, scratches (|net| tiny)
    wins=sum(1 for t in alltr if t['net']>0.0005)
    losses=sum(1 for t in alltr if t['net']<-0.0005)
    scratches=sum(1 for t in alltr if abs(t['net'])<=0.0005)
    times=sorted(t['time'] for t in alltr); med=times[len(times)//2]
    h1=[t for t in alltr if t['time']<=med]; h2=[t for t in alltr if t['time']>med]
    m1=metrics(h1); m2=metrics(h2); flag="✓" if (m1['netR']>0 and m2['netR']>0) else "✗"
    # per-asset both-halves
    both=0; checked=0; posc=0
    for a in ASSETS:
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        tr=backtest_trail(kl,cfg,daily) if be_trigger is None else backtest_be(kl,cfg,daily,be_trigger,be_lock)
        for t in tr:
            t['r']=(t['net']*t['entry'])/t['risk_amt'] if t['risk_amt']>0 else 0
        mm=metrics(tr)
        if mm['netR']>0: posc+=1
        if mm['trades']>=6:
            h=len(tr)//2; x=metrics(tr[:h]); y=metrics(tr[h:])
            if x['netR']>0 and y['netR']>0: both+=1
            checked+=1
    print(f"{label:<34} T={m['trades']:>3} W={wins:>3} L={losses:>3} S={scratches:>3} WR={m['wr']:>2.0f}% netR={m['netR']:>6.1f} PF={m['pf']:>5.2f} h1={m1['netR']:>6.1f} h2={m2['netR']:>6.1f} {flag} +both={both}/{checked} +pos={posc}/14")
    return m

cfg = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
           use_chop=True, min_slope=0.05, use_daily_gate=True, daily_ma_n=200,
           strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
           use_ema=False, atr_band=(0.5,3.0), trail=False)

print("ROUND 7: Breakeven-stop variants (raise non-loss rate, keep trend edge)")
print("="*120)
agg(cfg, None, 0, "BASELINE full 3R (winner)")
agg(cfg, 1.0, 0.0, "BE@+1R, stop->BE(0)")
agg(cfg, 1.0, 0.5, "BE@+1R, stop->+0.5R")
agg(cfg, 1.5, 0.0, "BE@+1.5R, stop->BE(0)")
agg(cfg, 1.5, 1.0, "BE@+1.5R, stop->+1R")
agg(cfg, 2.0, 1.0, "BE@+2R, stop->+1R")
