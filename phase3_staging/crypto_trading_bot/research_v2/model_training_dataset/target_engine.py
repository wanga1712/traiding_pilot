from __future__ import annotations

from collections import deque
import time
import numpy as np

NS_MINUTE = 60_000_000_000

def close_minute_bucket(ns):
    a=np.asarray(ns,dtype=np.int64)
    return ((a+NS_MINUTE-1)//NS_MINUTE)*NS_MINUTE

def forward_extreme(values: np.ndarray, window: int, maximum: bool) -> tuple[np.ndarray, np.ndarray]:
    """O(N) forward fixed-window extreme with earliest-index tie rule."""
    a=np.asarray(values,dtype=np.float64); n=len(a); out=np.full(n,np.nan); idx=np.full(n,-1,np.int64); q=deque()
    for i in range(n-1,-1,-1):
        limit=i+window
        while q and q[0]>=limit: q.popleft()
        if maximum:
            while q and a[i]>=a[q[-1]]: q.pop()
        else:
            while q and a[i]<=a[q[-1]]: q.pop()
        q.append(i)
        if i+window<=n: out[i]=a[q[0]]; idx[i]=q[0]
    return out,idx

def complete_window_mask(close_ns: np.ndarray, decision_ns: np.ndarray, horizon_minutes: int, development_end_ns: int):
    t=close_minute_bucket(close_ns); d=close_minute_bucket(decision_ns); dev=int(close_minute_bucket([development_end_ns])[0]); h=int(horizon_minutes); starts=np.searchsorted(t,d,side='right'); ends=starts+h-1
    valid=ends<len(t); safe=np.minimum(ends,max(len(t)-1,0)); expected_start=d+NS_MINUTE; expected_end=d+h*NS_MINUTE
    if len(t)>1:
        bad=np.r_[0,np.cumsum(np.diff(t)!=NS_MINUTE)]
        gapfree=valid & ((bad[safe]-bad[np.minimum(starts,max(len(t)-1,0))])==0)
    else: gapfree=np.zeros(len(d),bool)
    complete=valid & gapfree & (t[np.minimum(starts,max(len(t)-1,0))]==expected_start) & (t[safe]==expected_end) & (expected_end<=dev)
    boundary=expected_end>dev
    gap=(~complete)&(~boundary)
    return starts,complete,gap,boundary

def optimized_targets(close_ns,close,high,low,decision_ns,decision_close,horizons,development_end_ns):
    t=np.asarray(close_ns,dtype=np.int64); tq=close_minute_bucket(t); c=np.asarray(close,float); hi=np.asarray(high,float); lo=np.asarray(low,float); d=np.asarray(decision_ns,dtype=np.int64); dq=close_minute_bucket(d); base=np.asarray(decision_close,float); result={}; counters={'complete':0,'censored_gap':0,'censored_boundary':0}
    for h in horizons:
        starts,ok,gap,boundary=complete_window_mask(t,d,h,development_end_ns); maxv,maxi=forward_extreme(hi,h,True); minv,mini=forward_extreme(lo,h,False); s=np.minimum(starts,max(len(t)-1,0)); endpoint=s+h-1
        def masked(x): return np.where(ok,x,np.nan)
        exact=np.where(ok,c[np.minimum(endpoint,len(c)-1)],np.nan); mx=masked(maxv[s]); mn=masked(minv[s]); result[h]={'fwd_return':masked(exact/base-1),'fwd_log_return':masked(np.log(exact/base)),'mfe_up':masked(mx/base-1),'mfe_down':masked(mn/base-1),'max_future_high':mx,'min_future_low':mn,'time_to_max':masked((tq[maxi[s]]-dq)/NS_MINUTE),'time_to_min':masked((tq[mini[s]]-dq)/NS_MINUTE),'censor':~ok}
        counters['complete']+=int(ok.sum());counters['censored_gap']+=int(gap.sum());counters['censored_boundary']+=int(boundary.sum())
    return result,counters

def slow_reference(close_ns,close,high,low,decision_ns,decision_close,horizon,development_end_ns):
    t=np.asarray(close_ns,dtype=np.int64);tq=close_minute_bucket(t);c=np.asarray(close,float);hi=np.asarray(high,float);lo=np.asarray(low,float);d=np.asarray(decision_ns,dtype=np.int64);dq=close_minute_bucket(d);base=np.asarray(decision_close,float);dev=int(close_minute_bucket([development_end_ns])[0]);rows=[]
    for x,xq,b in zip(d,dq,base):
        ix=np.flatnonzero((tq>xq)&(tq<=xq+horizon*NS_MINUTE)); expected=xq+np.arange(1,horizon+1,dtype=np.int64)*NS_MINUTE; ok=xq+horizon*NS_MINUTE<=dev and len(ix)==horizon and np.array_equal(tq[ix],expected)
        if not ok: rows.append((True,)+(np.nan,)*8);continue
        qh=hi[ix];ql=lo[ix];mx=float(qh.max());mn=float(ql.min());imax=ix[np.flatnonzero(qh==mx)[0]];imin=ix[np.flatnonzero(ql==mn)[0]];exact=c[ix[-1]]
        rows.append((False,exact/b-1,np.log(exact/b),mx/b-1,mn/b-1,mx,mn,(tq[imax]-xq)/NS_MINUTE,(tq[imin]-xq)/NS_MINUTE))
    return rows

def parity_check(close_ns,close,high,low,decision_ns,decision_close,horizons,development_end_ns,max_rows=64):
    take=np.linspace(0,len(decision_ns)-1,min(max_rows,len(decision_ns)),dtype=int); opt,_=optimized_targets(close_ns,close,high,low,np.asarray(decision_ns)[take],np.asarray(decision_close)[take],horizons,development_end_ns)
    for h in horizons:
        ref=slow_reference(close_ns,close,high,low,np.asarray(decision_ns)[take],np.asarray(decision_close)[take],h,development_end_ns)
        keys=['fwd_return','fwd_log_return','mfe_up','mfe_down','max_future_high','min_future_low','time_to_max','time_to_min']
        if not np.array_equal(opt[h]['censor'],np.array([r[0] for r in ref])): return False
        for j,k in enumerate(keys,1):
            if not np.allclose(opt[h][k],np.array([r[j] for r in ref]),rtol=0,atol=1e-12,equal_nan=True): return False
    return True
