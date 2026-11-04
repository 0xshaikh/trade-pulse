#!/usr/bin/env python3
"""Round 10: CUT THE CHOP — filters to remove the losing assets/conditions (DOT/XRP/DOGE).
REAL engine (next-open + slippage + funding). Test: ADX trend-strength filter, volume confirmation,
asset-level regime (above daily MA200). Goal: keep netR, cut the losers.
"""
import sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, donch, sma, metrics, ASSETS
from round9_realism import backtest_real, SLIP

def adx(kl, n=14):
    out=[None]*len(kl)
    for i in range(n+1,len(kl)):
        trs=[]; pdms=[]; ndms=[]; rngs=[]
        for j in range(i-n+1,i+1):
            h=kl[j]['high']; l=kl[j]['low']; hc=kl[j-1]['close']; lc=kl[j-1]['close']
            tr=max(h-l, abs(h-hc), abs(l-lc))
            up=h-kl[j-1]['high']; dn=kl[j-1]['low']-l
            pdm=up if (up>dn and up>0) else 0
            ndm=dn if (dn>up and dn>0) else 0
            trs.append(tr); pdms.append(pdm); ndms.append(ndm)
        atr_v=sum(trs)/n
        if atr_v<=0: out[i]=0; continue
        pdi=100*sum(pdms)/n/atr_v; ndi=100*sum(ndms)/n/atr_v
        out[i]=100*abs(pdi-ndi)/(pdi+ndi) if (pdi+ndi)>0 else 0
    return out

def volratio(kl, n=20):
    out=[None]*len(kl)
    for i in range(n-1,len(kl)):
        w=kl[i-n+1:i+1]
        avg=sum(k.get('volume',0) for k in w)/n
        out[i]=kl[i].get('volume',0)/avg if avg>0 else 1.0
    return out

def agg_f(cfg, label, adx_min=None, vol_min=None, drop=None):
    alltr=[]
    for a in ASSETS:
        if drop and a in drop: continue
        kl=load(a,'4h')[-600:]; daily=load(a,'1d')
        tr=backtest_real(kl,cfg,daily,True,SLIP,True)
        # apply filters post-hoc (on entry bar)
        if adx_min is not None:
            AD=adx(kl)
            tr=[t for t in tr if AD[t['ti']] is not None and AD[t['ti']]>=adx_min]
        if vol_min is not None:
            VR=volratio(kl)
            tr=[t for t in tr if VR[t['ti']] is not None and VR[t['ti']]>=vol_min]
        for t in tr: t['asset']=a
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
    print(f"{label:<40} T={m['trades']:>3} WR={m['wr']:>2.0f}% netR={m['netR']:>6.1f} PF={m['pf']:>5.2f} {hh}")
    return m

cfg = dict(dc_n=10, ma_n=100, atr_n=14, dcx_n=10, stop_mult=2.0, tp_mult=3.0,
           use_chop=True, min_slope=0.05, use_daily_gate=True, daily_ma_n=200,
           strict_gate=False, use_rsi=False, use_adx=False, use_macd=False, use_vol=False,
           use_ema=False, atr_band=(0.5,3.0), trail=False)

print("ROUND 10: CUT THE CHOP — filters on REAL engine (next-open+slippage+funding)")
print("="*110)
agg_f(cfg, "REAL baseline (no extra filter)")
agg_f(cfg, "REAL + ADX>=18", adx_min=18)
agg_f(cfg, "REAL + ADX>=22", adx_min=22)
agg_f(cfg, "REAL + ADX>=25", adx_min=25)
agg_f(cfg, "REAL + vol>=1.0x", vol_min=1.0)
agg_f(cfg, "REAL + vol>=1.2x", vol_min=1.2)
agg_f(cfg, "REAL + ADX>=18 + vol>=1.0", adx_min=18, vol_min=1.0)
agg_f(cfg, "REAL, drop DOT only", drop={'DOTUSDT'})
agg_f(cfg, "REAL, drop DOT+XRP+DOGE", drop={'DOTUSDT','XRPUSDT','DOGEUSDT'})
agg_f(cfg, "REAL + ADX>=20, drop DOT", adx_min=20, drop={'DOTUSDT'})
