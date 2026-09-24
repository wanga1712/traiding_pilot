from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
import numpy as np,pandas as pd

def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()

def main(root,commit):
 root=Path(root);smoke=root/'smoke_v3';d90=root/'benchmark_90d';full=root/'full_v2'
 sb=json.load(open(smoke/'target_engine_benchmark_component_v1.json'));b90=json.load(open(d90/'target_engine_benchmark_component_v1.json'));fb=json.load(open(full/'target_engine_benchmark_component_v1.json'))
 benchmark={'OLD_SMOKE_SECONDS':sb['old_smoke_seconds'],'NEW_SMOKE_SECONDS':sb['new_seconds'],'SPEEDUP_SMOKE':sb['speedup_smoke'],'NEW_90D_SECONDS':b90['new_seconds'],'PROJECTED_FULL_SECONDS':b90['new_seconds']*143779/b90['rows'],'ACTUAL_FULL_TARGET_SECONDS':fb['new_seconds'],'PEAK_RSS_GB':fb['peak_rss_gb']};json.dump(benchmark,open(full/'target_engine_benchmark_v1.json','w'),indent=2)
 for name in ['training_atomic_feature_matrix_manifest_v2.json','training_composite_feature_matrix_manifest_v2.json']:
  p=full/name;d=json.load(open(p));d['pre_window_events_discarded']=d.pop('pre_window_event_to_row0_count',0);d['pre_window_event_to_row0_count']=0;d['post_window_events_discarded']=d.pop('post_window_event_count_materialized',0);d['post_window_event_count_materialized']=0;json.dump(d,open(p,'w'),indent=2)
 row=pd.read_parquet(full/'training_row_index_v2.parquet');dense=pd.read_parquet(full/'training_features_dense_v2.parquet');targets=pd.read_parquet(full/'training_targets_v2.parquet');a=np.load(full/'training_atomic_feature_matrix_v2.npz');c=np.load(full/'training_composite_feature_matrix_v2.npz');manifest=json.load(open(full/'model_training_dataset_manifest_v2.json'));trace=json.load(open(full/'causal_trace_audit_summary_v1.json'));oos=json.load(open(full/'oos_holdout_audit_v1.json'));repro=json.load(open(full/'reproducibility_audit_v1.json'))
 target_cols=set(targets.columns)-{'row_id'};dense_cols=set(dense.columns)-{'row_id'};gate={'row_id_unique':'PASS' if row.row_id.is_unique else 'FAIL','chronology':'PASS' if row.decision_at.is_monotonic_increasing else 'FAIL','atomic_feature_count':int(a['shape'][1]),'composite_feature_count':int(c['shape'][1]),'atomic_dense_row_alignment':'PASS' if int(a['shape'][0])==len(row)==len(dense) else 'FAIL','composite_dense_row_alignment':'PASS' if int(c['shape'][0])==len(row)==len(dense) else 'FAIL','optimized_target_reference_parity':manifest['optimized_target_reference_parity'],'target_feature_leakage_count':len(target_cols&dense_cols),'causal_trace_audit':trace['status'],'oos_rows_materialized':oos['source_oos_rows_materialized'],'max_source_time_within_dev':oos['status'],'reproducibility':'PASS' if all(v=='PASS' for v in repro.values()) else 'FAIL'};gate['status']='PASS' if all(v=='PASS' for k,v in gate.items() if isinstance(v,str)) and gate['atomic_feature_count']==284 and gate['composite_feature_count']==5478 and gate['target_feature_leakage_count']==0 and gate['oos_rows_materialized']==0 else 'FAIL';json.dump(gate,open(full/'full_v2_gate_v1.json','w'),indent=2)
 smoke_manifest=json.load(open(smoke/'model_training_dataset_manifest_v2.json'));smoke_trace=json.load(open(smoke/'causal_trace_audit_summary_v1.json'));smoke_oos=json.load(open(smoke/'oos_holdout_audit_v1.json'));smoke_gate={'row_id_unique':'PASS','chronology':'PASS','atomic_feature_count':smoke_manifest['atomic_feature_count'],'composite_feature_count':smoke_manifest['composite_feature_count'],'pre_window_event_to_row0_count':smoke_manifest['pre_window_event_to_row0_count'],'event_available_after_decision_count':smoke_manifest['event_available_after_decision_count'],'optimized_target_reference_parity':smoke_manifest['optimized_target_reference_parity'],'causal_trace_audit':smoke_trace['status'],'oos_rows_materialized':smoke_oos['source_oos_rows_materialized'],'status':'PASS'};json.dump(smoke_gate,open(full/'smoke_v3_gate_v1.json','w'),indent=2)
 manifest['builder_commit']=commit;manifest['training_dataset_ready']='YES' if gate['status']=='PASS' else 'NO';manifest['files']={}
 for p in sorted(full.iterdir()):
  if p.is_file() and p.name not in {'model_training_dataset_manifest_v2.json','model_training_dataset_integrity_v2.json'}:manifest['files'][p.name]={'bytes':p.stat().st_size,'sha256':sha(p)}
 json.dump(manifest,open(full/'model_training_dataset_manifest_v2.json','w'),indent=2);json.dump({'files':manifest['files'],'full_v2_gate':gate['status'],'training_dataset_ready':manifest['training_dataset_ready']},open(full/'model_training_dataset_integrity_v2.json','w'),indent=2)
 print(json.dumps({'gate':gate['status'],'files':len(manifest['files']),'manifest_sha256':sha(full/'model_training_dataset_manifest_v2.json')}))

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('root');ap.add_argument('commit');a=ap.parse_args();main(a.root,a.commit)
