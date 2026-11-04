#!/usr/bin/env python3
"""Round 6: HIGH WIN RATE hunt. Can 80%+ WR coexist with positive netR after fees?
Skill warns: high WR is manufactured by tight TP / wide SL (rewards frequency, not value).
Test the WR frontier empirically: reversion entries x tight-TP x wide-SL, 1h and 4h, taker fees.
R is defined UNAMBIGUOUSLY: risk = SL_MULT*ATR (1R); TP = TP_MULT*ATR (absolute). TP in R = TP_MULT/SL_MULT.
"""
import json, sys, math
sys.path.insert(0, "/home/ubuntu/trade-pulse/research")
from grid_search import load, atr, sma, metrics, ASSETS

COST = 0.0010  # taker round-trip

def rsi(cl, n):
    out=[None]*len(cl); gains=0; losses=0
    for i in range(1,len(cl)):
        d=cl[i]-cl[i-1]; g=max(d,0); l=max(-d,0)
        if i<=n:
            gains+=g; losses+=l
            if i==n:
                ag=gains/n; al=losses/n
                out[i]=100 if al==0 else 100-100/(1+ag/al)
        else:
            ag=(ag*(n-1)+g)/n; al=(al*(n-1)+l)/n
            out[i]=100 if al==0 else 100-100/(1+ag/al)
    return out

def boll(cl, n=20, k=2.0):
    up=[None]*len(cl); lo=[None]*len(cl); mid=[None]*len(cl)
    for i in range(n-1,len(cl)):
        w=cl[i-n+1:i+1]; m=sum(w)/n
        sd=(sum((x-m)**2 for x in w)/n)**0.5
        mid[i]=m; up[i]=m+k*sd; lo[i]=m-k*sd
    return up,lo,mid

def zscore(cl, n=50):
    out=[None]*len(cl)
    for i in range(n-1,len(cl)):
        w=cl[i-n+1:i+1]; m=sum(w)/n
        sd=(sum((x-m)**2 for x in w)/n)**0.5
        out[i]=(cl[i]-m)/sd if sd>0 else 0
    return out

def backtest(kl, entry_fn, sl_mult, tp_mult, time_stop=None, trend_filter=None):
    """entry_fn(i, kl, ctx) -> +1/-1/0. Exit: stop (SL_MULT*ATR), target (TP_MULT*ATR), optional time stop, optional trend flip."""
    n=len(kl); close=[k['close'] for k in kl]; A=atr(kl,14)
    ctx={'close':close,'A':A}
    trades=[]; pos=None; warm=60
    for i in range(1,n):
        if pos:
            b=kl[i]; dir=pos['dir']; entry=pos['entry']; stop=pos['stop']; tp=pos['tp']
            ex=None; rsn=None
            if dir==1:
                if b['low']<=stop: ex=stop; rsn='stop'
                elif tp is not None and b['high']>=tp: ex=tp; rsn='target'
            else:
                if b['high']>=stop: ex=stop; rsn='stop'
                elif tp is not None and b['low']<=tp: ex=tp; rsn='target'
            if ex is None and time_stop and (i-pos['ti'])>=time_stop:
                ex=close[i]; rsn='time'
            # trend-flip exit (only if configured)
            if ex is None and trend_filter:
                tf=trend_filter(i,kl,ctx)
                if tf is not None and tf!=dir: ex=close[i]; rsn='flip'
            if ex is not None:
                gross=(ex-entry)/entry*dir; net=gross-COST
                trades.append({'dir':dir,'entry':entry,'exit':ex,'net':net,'rsn':rsn,'time':b['time'],'risk_amt':pos['risk']})
                pos=None
        if i<warm: continue
        if pos: continue
        if A[i] is None or A[i]<=0: continue
        s=entry_fn(i,kl,ctx)
        if s==0: continue
        if trend_filter:
            tf=trend_filter(i,kl,ctx)
            if tf is not None and tf!=s: continue
        e=close[i]; risk=sl_mult*A[i]
        if risk<=0 or e<=0: continue
        pos={'dir':s,'entry':e,'stop':e-s*risk,'tp':(e+s*tp_mult*A[i]) if tp_mult else None,'ti':i,'risk':risk}
    return trades

def agg(cfg, label):
    alltr=[]
    for a in ASSETS:
        kl=load(a,cfg['tf'])[-cfg.get('bars',600):]
        tr=backtest(kl, cfg['entry'], cfg['sl'], cfg['tp'], cfg.get('time_stop'), cfg.get('trend_filter'))
        for t in tr:
            t['asset']=a; t['r']=(t['net']*t['entry'])/t['risk_amt'] if t['risk_amt']>0 else 0
        alltr+=tr
    m=metrics(alltr)
    # half-split
    times=sorted(t['time'] for t in alltr)
    if times:
        med=times[len(times)//2]
        h1=[t for t in alltr if t['time']<=med]; h2=[t for t in alltr if t['time']>med]
        m1=metrics(h1); m2=metrics(h2); flag="✓" if (m1['netR']>0 and m2['netR']>0) else "✗"
        hh=f"h1={m1['netR']:>6.1f} h2={m2['netR']:>6.1f} h1PF={m1['pf']:>4.2f} h2PF={m2['pf']:>4.2f} {flag}"
    else:
        hh="no trades"
    print(f"{label:<46} T={m['trades']:>4} WR={m['wr']:>3.0f}% netR={m['netR']:>7.2f} PF={m['pf']:>5.2f} avgR={m['avg'] if 'avg' in m else 0:>+5.2f} {hh}")
    return m

# Entry functions
def mk_rsi2(lo, hi):
    def f(i,kl,ctx):
        r=ctx['rsi2'][i] if ctx.get('rsi2') else None
        if r is None: return 0
        if r<lo: return 1
        if r>hi: return -1
        return 0
    return f

def prep_rsi2(kl):
    ctx={'close':[k['close'] for k in kl],'A':atr(kl,14)}
    ctx['rsi2']=rsi(ctx['close'],2)
    return ctx

def mk_rsi14(lo, hi):
    def f(i,kl,ctx):
        r=ctx['rsi14'][i] if ctx.get('rsi14') else None
        if r is None: return 0
        if r<lo: return 1
        if r>hi: return -1
        return 0
    return f

def prep_rsi14(kl):
    ctx={'close':[k['close'] for k in kl],'A':atr(kl,14)}
    ctx['rsi14']=rsi(ctx['close'],14)
    return ctx

def mk_pctb(lo, hi):
    def f(i,kl,ctx):
        pb=ctx['pctb'][i] if ctx.get('pctb') else None
        if pb is None: return 0
        if pb<lo: return 1
        if pb>hi: return -1
        return 0
    return f

def prep_pctb(kl):
    ctx={'close':[k['close'] for k in kl],'A':atr(kl,14)}
    up,lo,mid=boll(ctx['close'],20,2.0)
    ctx['pctb']=[None if up[i] is None else (ctx['close'][i]-lo[i])/(up[i]-lo[i]) for i in range(len(ctx['close']))]
    return ctx

def mk_z(lo, hi):
    def f(i,kl,ctx):
        z=ctx['z'][i] if ctx.get('z') else None
        if z is None: return 0
        if z<lo: return 1
        if z>hi: return -1
        return 0
    return f

def prep_z(kl):
    ctx={'close':[k['close'] for k in kl],'A':atr(kl,14)}
    ctx['z']=zscore(ctx['close'],50)
    return ctx

# Trend filter: only long if close>MA200, only short if close<MA200
def mk_trend(ma_n):
    def tf(i,kl,ctx):
        ma=ctx.get('ma')
        if ma is None or ma[i] is None: return None
        return 1 if ctx['close'][i]>ma[i] else -1
    return tf

def prep_trend(kl, ma_n=200):
    ctx={'close':[k['close'] for k in kl],'A':atr(kl,14)}
    ctx['ma']=sma(ctx['close'],ma_n)
    return ctx

# We need entry functions that read from a per-asset prepared ctx. Since backtest builds its own ctx,
# override: build ctx before and pass into backtest via closure.
def backtest2(kl, entry_fn, sl_mult, tp_mult, time_stop=None, trend_filter=None, prep=None, trend_prep=None, tf_ma=200):
    n=len(kl); close=[k['close'] for k in kl]
    ctx={'close':close,'A':atr(kl,14)}
    if prep: ctx.update(prep(kl))
    if trend_prep: ctx['ma']=sma(close,tf_ma)
    A=ctx['A']
    trades=[]; pos=None; warm=60
    for i in range(1,n):
        if pos:
            b=kl[i]; dir=pos['dir']; entry=pos['entry']; stop=pos['stop']; tp=pos['tp']
            ex=None; rsn=None
            if dir==1:
                if b['low']<=stop: ex=stop; rsn='stop'
                elif tp is not None and b['high']>=tp: ex=tp; rsn='target'
            else:
                if b['high']>=stop: ex=stop; rsn='stop'
                elif tp is not None and b['low']<=tp: ex=tp; rsn='target'
            if ex is None and time_stop and (i-pos['ti'])>=time_stop:
                ex=close[i]; rsn='time'
            if ex is None and trend_filter:
                ma=ctx.get('ma')
                if ma is not None and ma[i] is not None:
                    tf=1 if close[i]>ma[i] else -1
                    if tf!=dir: ex=close[i]; rsn='flip'
            if ex is not None:
                gross=(ex-entry)/entry*dir; net=gross-COST
                trades.append({'dir':dir,'entry':entry,'exit':ex,'net':net,'rsn':rsn,'time':b['time'],'risk_amt':pos['risk']})
                pos=None
        if i<warm: continue
        if pos: continue
        if A[i] is None or A[i]<=0: continue
        s=entry_fn(i,kl,ctx)
        if s==0: continue
        if trend_filter:
            ma=ctx.get('ma')
            if ma is not None and ma[i] is not None:
                tf=1 if close[i]>ma[i] else -1
                if tf!=s: continue
        e=close[i]; risk=sl_mult*A[i]
        if risk<=0 or e<=0: continue
        pos={'dir':s,'entry':e,'stop':e-s*risk,'tp':(e+s*tp_mult*A[i]) if tp_mult else None,'ti':i,'risk':risk}
    return trades

def agg2(cfg, label):
    alltr=[]
    for a in ASSETS:
        kl=load(a,cfg['tf'])[-cfg.get('bars',600):]
        tr=backtest2(kl, cfg['entry'], cfg['sl'], cfg['tp'], cfg.get('time_stop'), cfg.get('trend_filter'), cfg.get('prep'), cfg.get('trend_prep'), cfg.get('tf_ma',200))
        for t in tr:
            t['asset']=a; t['r']=(t['net']*t['entry'])/t['risk_amt'] if t['risk_amt']>0 else 0
        alltr+=tr
    m=metrics(alltr)
    times=sorted(t['time'] for t in alltr)
    if times:
        med=times[len(times)//2]
        h1=[t for t in alltr if t['time']<=med]; h2=[t for t in alltr if t['time']>med]
        m1=metrics(h1); m2=metrics(h2); flag="✓" if (m1['netR']>0 and m2['netR']>0) else "✗"
        hh=f"h1={m1['netR']:>6.1f} h2={m2['netR']:>6.1f} h1PF={m1['pf']:>4.2f} h2PF={m2['pf']:>4.2f} {flag}"
    else:
        hh="no trades"
    print(f"{label:<46} T={m['trades']:>4} WR={m['wr']:>3.0f}% netR={m['netR']:>7.2f} PF={m['pf']:>5.2f} avgR={m.get('avg',0):>+5.2f} {hh}")
    return m

if __name__ == "__main__":
    print("="*120)
    print("ROUND 6: WIN RATE frontier — can 80%+ WR coexist with positive netR (after 0.10% taker fees)?")
    print("R defined: risk=SL_MULT*ATR (1R); TP=TP_MULT*ATR absolute. TP in R = TP_MULT/SL_MULT. Fees 0.0010 r/t.")
    print("="*120)

    # --- 1h: reversion entries, tight TP / wide SL ---
    for tf in ['1h','4h']:
        print(f"\n### {tf.upper()} — RSI2 reversion (Connors), tight TP / wide SL")
        for sl,tp in [(2.0,0.5),(2.0,1.0),(3.0,1.0),(2.0,1.5),(1.0,0.5),(1.0,1.0)]:
            for lo,hi,lab in [(5,95,'R2<5'),(10,90,'R2<10')]:
                agg2({'tf':tf,'entry':mk_rsi2(lo,hi),'prep':prep_rsi2,'sl':sl,'tp':tp}, f"RSI2 {lab} SL={sl}xA TP={tp}xA ({tp/sl:.2f}R)")
