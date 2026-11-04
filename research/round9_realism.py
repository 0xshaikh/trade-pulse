#!/usr/bin/env python3
"""Round 9: REAL-TRADE realism test. Same winner signal, but fills are realistic:
  - ENTRY at next bar OPEN (signal on close[i], enter open[i+1]) instead of close[i]
  - SLIPPAGE 0.02% per side (conservative for liquid futures; 0.04% round trip)
  - FUNDING 0.01% per 8h held (pro-rated by bars held), paid in direction of position
  - Same: taker 0.05%/side (0.10% round trip), 2xATR stop / 3xATR target, daily MA200 gate
If the winner survives these costs on next-open fills, it's real. If not, the edge was fill-assumption.
"""
import sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, donch, sma, metrics, ASSETS

SLIP = 0.0002   # 0.02% per side
TAKER = 0.0005  # 0.05% per side
FUND_8H = 0.0001  # 0.01% per 8h interval

def backtest_real(kl, cfg, daily=None, next_open=True, slip=SLIP, fund=True):
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
            b=kl[i]; ex=None; rsn=None
            stop=pos['stop']
            if pos['dir']==1:
                if b['low']<=stop: ex=stop; rsn='stop'
                elif pos['tp'] is not None and b['high']>=pos['tp']: ex=pos['tp']; rsn='target'
                elif b['close']<DLx[i]: ex=b['close']; rsn='chan'
            else:
                if b['high']>=stop: ex=stop; rsn='stop'
                elif pos['tp'] is not None and b['low']<=pos['tp']: ex=pos['tp']; rsn='target'
                elif b['close']>DUx[i]: ex=b['close']; rsn='chan'
            if ex is not None:
                t=pos
                # slippage on exit (in adverse direction)
                ex2 = ex - pos['dir']*slip*ex
                t['exit']=ex2; t['rsn']=rsn; t['time']=b['time']
                bars_held = i - pos['ti']
                gross=(ex2-t['entry'])/t['entry']*t['dir']
                fees = TAKER*2  # entry+exit taker
                sl = slip*2     # entry+exit slippage
                fn = (FUND_8H * (bars_held*4/8.0)) if fund else 0  # 4h bars, funding every 8h
                t['net'] = gross - fees - sl - fn*pos['dir']
                t['r']=(t['net']*t['entry'])/t['risk_amt'] if t['risk_amt']>0 else 0
                t['bars']=bars_held; t['fund']=fn*pos['dir']
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
            if idx<cfg.get('daily_ma_n',200)-1 or dma[idx] is None:
                if cfg.get('strict_gate'): continue
            else:
                dc=dclose[idx]; dm=dma[idx]
                if d==1 and dc<=dm: continue
                if d==-1 and dc>=dm: continue
        # REAL entry: signal on close[i], enter at open[i+1] (next bar), if exists
        if next_open:
            if i+1>=n: continue
            e = kl[i+1]['open']  # enter next bar open
            # slip adverse on entry
            e = e + d*slip*e
            sd = cfg.get('stop_mult',2.0)*A[i] if A[i] is not None else None
            if sd is None or sd<=0 or e<=0: continue
            pos={'dir':d,'entry':e,'risk_amt':sd,'stop':e-d*sd,
                 'tp':(e+d*cfg.get('tp_mult',3.0)*sd) if cfg.get('tp_mult') else None,'ti':i+1}
        else:
            e=close[i]; sd=cfg.get('stop_mult',2.0)*A[i] if A[i] is not None else None
            if sd is None or sd<=0 or e<=0: continue
            pos={'dir':d,'entry':e,'risk_amt':sd,'stop':e-d*sd,
                 'tp':(e+d*cfg.get('tp_mult',3.0)*sd) if cfg.get('tp_mult') else None,'ti':i}
    return trades

def agg(cfg, next_open, slip, fund, label):
    alltr=[]
    for a in ASSETS:
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        tr=backtest_real(kl,cfg,daily,next_open,slip,fund)
        for t in tr:
            t['asset']=a
        alltr+=tr
    m=metrics(alltr)
    times=sorted(t['time'] for t in alltr)
    if times:
        med=times[len(times)//2]
        h1=[t for t in alltr if t['time']<=med]; h2=[t for t in alltr if t['time']>med]
        m1=metrics(h1); m2=metrics(h2); flag="✓" if (m1['netR']>0 and m2['netR']>0) else "✗"
        hh=f"h1={m1['netR']:>6.1f} h2={m2['netR']:>6.1f} {flag}"
    else:
        hh="no trades"
    print(f"{label:<44} T={m['trades']:>3} WR={m['wr']:>2.0f}% netR={m['netR']:>6.1f} PF={m['pf']:>5.2f} {hh}")
    return m

cfg = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
           use_chop=True, min_slope=0.05, use_daily_gate=True, daily_ma_n=200,
           strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
           use_ema=False, atr_band=(0.5,3.0), trail=False)

print("ROUND 9: REAL-TRADE realism — same winner, realistic fills")
print("="*110)
agg(cfg, False, 0.0, False, "IDEAL (close-fill, taker only) [current]")
agg(cfg, True, 0.0, False, "NEXT-OPEN entry, taker only")
agg(cfg, True, SLIP, False, "NEXT-OPEN + slippage 0.02%/side")
agg(cfg, True, SLIP, True, "NEXT-OPEN + slippage + funding (REAL)")
