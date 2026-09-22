from __future__ import annotations

import argparse, hashlib, json, os, glob
from pathlib import Path
import numpy as np
import pandas as pd

DEV_START = pd.Timestamp("2019-05-12T00:00:00Z")
DEV_END = pd.Timestamp("2023-06-20T06:08:00Z")
HORIZONS = (30, 60, 120, 240, 480, 720, 1440)
ROOT = Path("/var/tmp/traiding_pilot_ui_workspace")
ART = ROOT / "artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1"
OUT = ROOT / "artifacts/PROBABILITY-MODEL-TRAINING-DATASET-1"

def sha256_file(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def build(start=DEV_START, end=DEV_END, smoke=False):
    out=OUT / ("smoke" if smoke else "full")
    out.mkdir(parents=True,exist_ok=True)
    start=pd.Timestamp(start); end=pd.Timestamp(end)
    bars=pd.read_parquet('/var/tmp/traiding_pilot_market_cache/resampled/ETHUSDT_15m.parquet')
    bars['open_time_utc']=pd.to_datetime(bars['open_time_utc'],utc=True)
    bars['close_time_utc']=pd.to_datetime(bars['close_time_utc'],utc=True)
    bars=bars[(bars.open_time_utc>=start)&(bars.close_time_utc<=end)].sort_values('open_time_utc').reset_index(drop=True)
    if bars.empty: raise RuntimeError('empty development grid')
    dec=bars.close_time_utc.to_numpy(dtype='datetime64[ns]')
    n=len(bars)
    row=pd.DataFrame({'row_id':np.arange(n,dtype=np.int64),'open_time_utc':bars.open_time_utc,'decision_at':bars.close_time_utc,'symbol':'ETHUSDT','decision_tf':'15m','split':np.where(bars.close_time_utc<pd.Timestamp('2020-05-21T01:32Z'),'FOLD_1',np.where(bars.close_time_utc<pd.Timestamp('2021-05-31T03:04Z'),'FOLD_2',np.where(bars.close_time_utc<pd.Timestamp('2022-06-10T04:36Z'),'FOLD_3','FOLD_4')))} )
    row.to_parquet(out/'training_row_index_v1.parquet',index=False)
    # dense causal context, all values use current/past 15m bars only
    c=bars.copy(); op=c.open.astype(float); hi=c.high.astype(float); lo=c.low.astype(float); close=c.close.astype(float); vol=c.volume.astype(float); trades=c.trade_count.astype(float); ret=close.pct_change(); cfeat=pd.DataFrame({'row_id':np.arange(n),'open':op,'high':hi,'low':lo,'close':close,'volume':vol,'trade_count':trades,'return_1':ret,'log_return_1':np.log(close).diff(),'range_pct':(hi-lo)/close,'close_position':(close-lo)/(hi-lo).replace(0,np.nan),'volume_log1p':np.log1p(vol),'atr_14':(hi-lo).rolling(14,min_periods=2).mean(),'volume_mean_32':vol.rolling(32,min_periods=2).mean(),'volume_std_32':vol.rolling(32,min_periods=2).std()})
    cfeat['volume_z_32']=(vol-cfeat.volume_mean_32)/cfeat.volume_std_32.replace(0,np.nan)
    cfeat=cfeat.replace([np.inf,-np.inf],np.nan).fillna(0.0)
    cfeat.to_parquet(out/'training_features_dense_v1.parquet',index=False)
    dense_cols=[x for x in cfeat.columns if x!='row_id']
    # sparse event matrix assembled as CSR arrays, without scipy dependency
    hand=json.load(open(ART/'model_feature_handoff_v1.json'))
    comp_ids=[x['composite_id'] for x in hand['features']]
    comp_ids=sorted(comp_ids); comp_col={x:i for i,x in enumerate(comp_ids)}
    stream_dir=ART/'composite_survivor_streams_v1'; metas=glob.glob(str(stream_dir/'*.meta.json'))
    byid={json.load(open(p))['composite_id']:p[:-10] for p in metas}
    indptr=[0]; indices=[]; data=[]
    dec_ns=dec.astype('datetime64[ns]').astype('int64')
    for r in range(n): indptr.append(indptr[-1])
    # transpose-friendly COO then CSR
    rr=[]; cc=[]
    for cid in comp_ids:
        p=byid.get(cid)
        if not p: continue
        z=np.load(p); ts=np.asarray(z['available_at_ns'],dtype=np.int64)
        ix=np.searchsorted(dec_ns,ts,side='left'); ix=ix[(ix>=0)&(ix<n)]
        if len(ix): rr.extend(ix.tolist()); cc.extend([comp_col[cid]]*len(ix))
    if rr:
        order=np.lexsort((np.asarray(cc),np.asarray(rr))); rr=np.asarray(rr)[order]; cc=np.asarray(cc)[order]
        uniq=np.ones(len(rr),bool); uniq[1:]=(rr[1:]!=rr[:-1])|(cc[1:]!=cc[:-1]); rr=rr[uniq]; cc=cc[uniq]
        data=np.ones(len(rr),dtype=np.float32); indptr=np.zeros(n+1,dtype=np.int64); np.add.at(indptr,rr+1,1); indptr=np.cumsum(indptr); indices=cc.astype(np.int32)
    else: data=np.empty(0,np.float32); indices=np.empty(0,np.int32); indptr=np.zeros(n+1,np.int64)
    np.savez_compressed(out/'training_composite_feature_matrix_v1.npz',data=data,indices=indices,indptr=indptr,shape=np.array([n,len(comp_ids)],dtype=np.int64))
    json.dump({'feature_ids':comp_ids,'n_features':len(comp_ids),'matrix_format':'csr','causal_rule':'available_at <= decision_at'},open(out/'training_composite_feature_columns_v1.json','w'),indent=2)
    atomic_ids=sorted(hand['atomic_feature_ids'])
    json.dump({'feature_ids':atomic_ids,'n_features':len(atomic_ids),'source':'frozen model_feature_handoff_v1.json'},open(out/'model_training_feature_registry_v1.json','w'),indent=2)
    # targets from 1m cache; only fully observed windows inside development end are labeled
    parts=sorted(glob.glob('/var/tmp/traiding_pilot_market_cache/1m/*.parquet'))
    m=pd.concat([pd.read_parquet(p) for p in parts],ignore_index=True)
    tcol='open_time_utc' if 'open_time_utc' in m else 'open_time'; m[tcol]=pd.to_datetime(m[tcol],utc=True); m=m[(m[tcol]>=start)&(m[tcol]<=end)].sort_values(tcol).reset_index(drop=True)
    mt=m[tcol].to_numpy(dtype='datetime64[ns]'); mc=m.close.to_numpy(float); mh=m.high.to_numpy(float); ml=m.low.to_numpy(float)
    base=bars.close.to_numpy(float); targ={'row_id':np.arange(n)}
    for mins in HORIZONS:
        delta=np.timedelta64(mins,'m'); vals=[]; mfe=[]; mae=[]; cens=[]
        for i,dt in enumerate(dec):
            j=np.searchsorted(mt,dt.astype('datetime64[ns]'),'right'); k=np.searchsorted(mt,(dt.astype('datetime64[ns]')+delta),'right')-1
            ok=(k>=j and k<len(mc) and (pd.Timestamp(dt).tz_localize('UTC')+pd.Timedelta(minutes=mins))<=end and j<len(mc))
            cens.append(not ok)
            if ok:
                vals.append(mc[k]/base[i]-1); mfe.append(np.max(mh[j:k+1])/base[i]-1); mae.append(np.min(ml[j:k+1])/base[i]-1)
            else: vals.append(np.nan); mfe.append(np.nan); mae.append(np.nan)
        key=f'{mins}m'; targ[f'fwd_return_{key}']=vals; targ[f'mfe_up_{key}']=mfe; targ[f'mfe_down_{key}']=mae; targ[f'censor_{key}']=cens
    targets=pd.DataFrame(targ); targets.to_parquet(out/'training_targets_v1.parquet',index=False)
    freg={'feature_count_dense':len(dense_cols),'feature_count_atomic':len(atomic_ids),'feature_count_composite':len(comp_ids),'families':['price_volume','rolling_context','frozen_atomic','frozen_composite'],'development_only':True,'oos_rows':0}
    json.dump(freg,open(out/'model_training_target_registry_v1.json','w'),indent=2)
    split_counts={k:int((row['split']==k).sum()) for k in sorted(row['split'].unique())}
    json.dump({'split_boundaries_utc':{'FOLD_1_END':'2020-05-21T01:32:00Z','FOLD_2_END':'2021-05-31T03:04:00Z','FOLD_3_END':'2022-06-10T04:36:00Z','FOLD_4_END':'2023-06-20T06:08:00Z'},'counts':split_counts,'development_only':True,'oos_rows':0},open(out/'model_training_split_manifest_v1.json','w'),indent=2)
    manifest={'dataset_version':'MODEL_TRAINING_DATASET_V1','development_start':str(start),'development_end':str(end),'rows':n,'smoke':smoke,'oos_included':False,'training_run':False,'source_hash':hand['COMPOSITE_SURVIVOR_SET_HASH'],'artifacts':{}}
    for p in out.iterdir():
        if p.is_file() and p.name not in {'model_training_dataset_manifest_v1.json','model_training_dataset_integrity_v1.json','model_training_dataset_summary_v1.json'}: manifest['artifacts'][p.name]={'bytes':p.stat().st_size,'sha256':sha256_file(p)}
    json.dump(manifest,open(out/'model_training_dataset_manifest_v1.json','w'),indent=2)
    json.dump({'files':manifest['artifacts'],'row_count':n,'oos_rows':0},open(out/'model_training_dataset_integrity_v1.json','w'),indent=2)
    json.dump({'dataset':'MODEL_TRAINING_DATASET_V1','rows':n,'dense_columns':len(dense_cols),'atomic_columns':len(atomic_ids),'composite_columns':len(comp_ids),'target_horizons_minutes':HORIZONS,'censored_rows_by_horizon':{k:int(targets[f'censor_{k}'].sum()) for k in [f'{x}m' for x in HORIZONS]}},open(out/'model_training_dataset_summary_v1.json','w'),indent=2)
    print(json.dumps({'out':str(out),'rows':n,'dense':len(dense_cols),'atomic':len(atomic_ids),'composite':len(comp_ids),'nnz':int(len(data)),'smoke':smoke}))

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--smoke-start'); ap.add_argument('--smoke-end'); a=ap.parse_args()
    build(pd.Timestamp(a.smoke_start,tz='UTC') if a.smoke_start else DEV_START,pd.Timestamp(a.smoke_end,tz='UTC')+pd.Timedelta(days=1)-pd.Timedelta(minutes=15) if a.smoke_end else DEV_END,bool(a.smoke_start))
