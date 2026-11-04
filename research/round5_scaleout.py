#!/usr/bin/env python3
"""Round 5: pro scale-out (partial profit-taking + breakeven) vs full 3R.
Skill's documented ladder: TP1=1R close 30% + SL->breakeven; TP2=2R close 30% + SL->+1R; TP3=3R close 40%.
Compare against full-position 3R exit. Focus: does scale-out cut the give-back losses on XRP/DOGE/ETH
without hurting the trend winners (SOL/LINK)?
"""
import json, sys, datetime
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, donch, sma, metrics, ASSETS

def base(**kw):
    c = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
             use_chop=True, min_slope=0.05, use_daily_gate=True, daily_ma_n=200,
             strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
             use_ema=False, atr_band=(0.5,3.0), trail=False, scaleout=False)
    c.update(kw); return c

def backtest_so(kl, cfg, daily=None, daily_ma_n=200):
    """Same engine + optional 3-tier scale-out (fractions 0.3/0.3/0.4 at 1R/2R/3R)."""
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
            b=kl[i]; ex=None; rsn=None; stop=pos['stop']
            dir=pos['dir']; entry=pos['entry']; risk=pos['risk_amt']
            # exit logic depends on scale-out tier
            tier_hit=None
            if cfg.get('scaleout'):
                # determine if a tier is hit this bar (based on high/low)
                # tier1=1R, tier2=2R, tier3=3R (target)
                tp1 = entry + dir*risk
                tp2 = entry + dir*2*risk
                tp3 = entry + dir*3*risk
                if dir==1:
                    if b['low']<=stop: ex=stop; rsn='stop'
                    elif b['high']>=tp3: ex=tp3; rsn='target'; tier_hit=3
                    elif b['high']>=tp2 and not pos.get('t2'): ex=tp2; rsn='tp2'; tier_hit=2
                    elif b['high']>=tp1 and not pos.get('t1'): ex=tp1; rsn='tp1'; tier_hit=1
                    elif b['close']<DLx[i]: ex=b['close']; rsn='chan'
                else:
                    if b['high']>=stop: ex=stop; rsn='stop'
                    elif b['low']<=tp3: ex=tp3; rsn='target'; tier_hit=3
                    elif b['low']<=tp2 and not pos.get('t2'): ex=tp2; rsn='tp2'; tier_hit=2
                    elif b['low']<=tp1 and not pos.get('t1'): ex=tp1; rsn='tp1'; tier_hit=1
                    elif b['close']>DUx[i]: ex=b['close']; rsn='chan'
                if ex is not None:
                    # scale-out: partial close, adjust stop, keep rest
                    if tier_hit in (1,2):
                        frac = 0.3
                        gross=(ex-entry)/entry*dir; net=gross-0.0010
                        trades.append({'dir':dir,'entry':entry,'exit':ex,'net':net,'rsn':rsn,'time':b['time'],
                                       'risk_amt':risk,'fraction':frac})
                        # update stop
                        if tier_hit==1: stop=entry  # breakeven
                        else: stop=entry + dir*risk  # +1R
                        pos['stop']=stop; pos['t1']=pos.get('t1') or tier_hit>=1; pos['t2']=pos.get('t2') or tier_hit>=2
                        pos['last_exit']=b['time']; pos['last_price']=ex
                        ex=None  # position continues
                    elif tier_hit==3 or rsn=='stop' or rsn=='chan':
                        gross=(ex-entry)/entry*dir; net=gross-0.0010
                        frac = 0.4 if tier_hit==3 else 1.0
                        trades.append({'dir':dir,'entry':entry,'exit':ex,'net':net,'rsn':rsn,'time':b['time'],
                                       'risk_amt':risk,'fraction':frac})
                        pos=None
            else:
                # full position (original)
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
                    trades.append({'dir':dir,'entry':entry,'exit':ex,'net':net,'rsn':rsn,'time':b['time'],
                                   'risk_amt':risk,'fraction':1.0})
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

def agg_metrics(cfg, label):
    alltr=[]
    for a in ASSETS:
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        tr=backtest_so(kl,cfg,daily)
        for t in tr: t['asset']=a
        alltr+=tr
    # effective net (fraction-weighted)
    # For scale-out, sum fraction*net per position; treat each partial as separate is wrong for count
    # Compute position-level: group by entry time
    pos_map={}
    for t in alltr:
        key=(t['asset'],t['entry'],t['time'])
        if key not in pos_map: pos_map[key]={'net':0,'frac':0,'entry':t['entry'],'asset':t['asset'],'time':t['time'],'dir':t['dir'],'rsns':[],'risk_amt':t.get('risk_amt',1)}
        pos_map[key]['net'] += t['fraction']*t['net']
        pos_map[key]['frac'] += t['fraction']
        pos_map[key]['rsns'].append(t['rsn'])
    poss=list(pos_map.values())
    for p in poss:
        p['r'] = (p['net']*p['entry'])/p.get('risk_amt',1) if p.get('risk_amt',0)>0 else 0
    m=metrics(poss)
    times=sorted(p['time'] for p in poss); med=times[len(times)//2]
    h1=[p for p in poss if p['time']<=med]; h2=[p for p in poss if p['time']>med]
    m1=metrics(h1); m2=metrics(h2)
    # per-asset
    both=0; checked=0; pcount=0
    for a in ASSETS:
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        tr=backtest_so(kl,cfg,daily)
        pm={}
        for t in tr:
            k=(t['entry'],t['time'])
            if k not in pm: pm[k]={'net':0,'entry':t['entry'],'time':t['time'],'risk_amt':t.get('risk_amt',1)}
            pm[k]['net']+=t['fraction']*t['net']
        pp=list(pm.values())
        for p in pp:
            p['r'] = (p['net']*p['entry'])/p.get('risk_amt',1) if p.get('risk_amt',0)>0 else 0
        mm=metrics(pp)
        if mm['netR']>0: pcount+=1
        if mm['trades']>=6:
            h=len(pp)//2; x=metrics(pp[:h]); y=metrics(pp[h:])
            if x['netR']>0 and y['netR']>0: both+=1
            checked+=1
    flag="✓" if (m1['netR']>0 and m2['netR']>0) else "✗"
    print(f"{label:<28} T={m['trades']:>3} netR={m['netR']:>6.1f} h1={m1['netR']:>6.1f} h2={m2['netR']:>6.1f} h1PF={m1['pf']:>5.2f} h2PF={m2['pf']:>5.2f} {flag} +both={both}/{checked} +pos={pcount}/14 WR={m['wr']:.0f}%")
    return m, poss

if __name__ == "__main__":
    print("Round 5: pro scale-out (1R/2R/3R ladder) vs full 3R")
    m,_ = agg_metrics(base(), "FULL 3R (current winner)")
    m2,poss = agg_metrics(base(scaleout=True), "SCALE-OUT 0.3/0.3/0.4")
    # focus assets
    print("\n--- give-back assets with scale-out ---")
    for a in ['XRPUSDT','DOGEUSDT','ETHUSDT']:
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        tr=backtest_so(kl,base(scaleout=True),daily)
        pm={}
        for t in tr:
            k=(t['entry'],t['time'])
            if k not in pm: pm[k]={'net':0,'entry':t['entry'],'time':t['time'],'risk_amt':t.get('risk_amt',1),'rsns':[]}
            pm[k]['net']+=t['fraction']*t['net']; pm[k]['rsns'].append(t['rsn'])
        pp=list(pm.values())
        for p in pp:
            p['r']=(p['net']*p['entry'])/p.get('risk_amt',1) if p.get('risk_amt',0)>0 else 0
        mm=metrics(pp)
        print(f"  {a}: T={mm['trades']} netR={mm['netR']:.1f} WR={mm['wr']:.0f}% PF={mm['pf']:.2f}")
