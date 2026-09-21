import json,csv,hashlib,sys
from pathlib import Path
from collections import Counter
import pyarrow.parquet as pq
root=Path('/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1')
names=['composite_results_all_v1.parquet','composite_results_all_v1.csv','composite_fold_stability_v1.csv',
 'composite_exact_duplicate_clusters_v1.csv','composite_redundancy_v1.csv',
 'frozen_composite_survivor_bank_raw_v1.json','frozen_composite_survivor_bank_v1.json',
 'composite_survivor_stream_manifest_v1.json','composite_summary_by_template_v1.csv',
 'composite_summary_by_tf_direction_v1.csv','composite_summary_by_family_v1.csv',
 'composite_negative_results_v1.csv','composite_execution_report_v1.json',
 'model_feature_handoff_v1.json','composite_finalization_status_v1.json']
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
files=[]
for name in names:
 p=root/name
 assert p.exists(),name
 entry={'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
 if name.endswith('.parquet'):
  pf=pq.ParquetFile(p);entry.update(row_count=pf.metadata.num_rows,schema=str(pf.schema_arrow))
 elif name.endswith('.csv'):
  with p.open(newline='') as f:
   r=csv.reader(f);entry['schema']=next(r);entry['row_count']=sum(1 for _ in r)
 else:
  doc=json.loads(p.read_text());entry['schema']=list(doc)
 files.append(entry)
results=pq.read_table(root/names[0],columns=['composite_id','composite_class','COMPOSITE_STREAM_SHA256','TOTAL_SIGNALS','trigger_candidate_id']).to_pylist()
byid={r['composite_id']:r for r in results}
classes=Counter(r['composite_class'] for r in results)
raw=json.loads((root/'frozen_composite_survivor_bank_raw_v1.json').read_text())
model=json.loads((root/'frozen_composite_survivor_bank_v1.json').read_text())
handoff=json.loads((root/'model_feature_handoff_v1.json').read_text())
configs=json.loads((root/'composite_atomic_bank_v1.json').read_text())['configs']
config_ids={c['candidate_id'] for c in configs}
expected={r['composite_id'] for r in results if r['composite_class'] in ('INCREMENTAL_BALANCED','INCREMENTAL_SELECTIVE')}
raw_ids={s['composite_id'] for s in raw['survivors']}
model_ids={s['composite_id'] for s in model['survivors']}
assert len(results)==len(byid)==200829
assert classes.keys()<=set(['INCREMENTAL_BALANCED','INCREMENTAL_SELECTIVE','WEAK_INCREMENTAL','NO_INCREMENTAL_EDGE','INSUFFICIENT'])
assert expected==raw_ids and len(raw_ids)==raw['n_survivors']
coverage=set(model_ids);alias_list=[]
for s in model['survivors']:
 assert s['COMPOSITE_STREAM_SHA256']==byid[s['composite_id']]['COMPOSITE_STREAM_SHA256']
 assert s['trigger_candidate_id'] in config_ids
 assert set(s['context_candidate_ids'])<=config_ids
 assert all(s['context_families'])
 alias_list.extend(s['alias_composite_ids']);coverage.update(s['alias_composite_ids'])
assert coverage==raw_ids,('alias coverage',len(raw_ids-coverage),len(coverage-raw_ids))
assert len(alias_list)==len(set(alias_list)) and not model_ids.intersection(alias_list)
assert len({s['COMPOSITE_STREAM_SHA256'] for s in model['survivors']})==len(model_ids)
for doc,key in [(raw,'RAW_COMPOSITE_SURVIVOR_SET_HASH'),(model,'COMPOSITE_SURVIVOR_SET_HASH')]:
 ids=sorted(s['composite_id'] for s in doc['survivors'])
 assert hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()==doc[key]
assert set(handoff['composite_feature_ids'])==model_ids
assert set(handoff['atomic_feature_ids'])<=config_ids
assert handoff['COMPOSITE_SURVIVOR_SET_HASH']==model['COMPOSITE_SURVIVOR_SET_HASH']
manifest=json.loads((root/'composite_survivor_stream_manifest_v1.json').read_text())
assert {s['composite_id'] for s in manifest['streams']}==raw_ids
assert manifest['n_streams']==len(raw_ids)
for s in manifest['streams']:
 r=byid[s['composite_id']]
 assert s['COMPOSITE_STREAM_SHA256']==r['COMPOSITE_STREAM_SHA256']
 assert s['n_signals']==r['TOTAL_SIGNALS']
meta_counts=Counter()
for p in sorted((root/'composite_survivor_metadata_parts_v1').glob('part-*.jsonl')):
 for line in p.read_text().splitlines():
  s=json.loads(line);meta_counts[s['composite_id']]+=1
  assert s['COMPOSITE_STREAM_SHA256']==byid[s['composite_id']]['COMPOSITE_STREAM_SHA256']
  assert s['n_signals']==byid[s['composite_id']]['TOTAL_SIGNALS']
assert set(meta_counts)==raw_ids and all(v==1 for v in meta_counts.values())
family_by_id={c['candidate_id']:c['family'] for c in configs}
expected_families=Counter(family_by_id[r['trigger_candidate_id']] for r in results)
with (root/'composite_summary_by_family_v1.csv').open(newline='') as f:
 actual_families={r['trigger_family_proxy']:int(r['n']) for r in csv.DictReader(f)}
assert dict(expected_families)==actual_families
for name in ['composite_summary_by_family_v1.csv','composite_summary_by_template_v1.csv','composite_summary_by_tf_direction_v1.csv']:
 with (root/name).open(newline='') as f: summary=list(csv.DictReader(f))
 assert sum(int(r['n']) for r in summary)==200829
 for cls,count in classes.items():assert sum(int(r['n_'+cls]) for r in summary)==count
with (root/'composite_results_all_v1.csv').open(newline='') as f:
 csv_rows=list(csv.DictReader(f))
assert len(csv_rows)==200829 and {r['composite_id'] for r in csv_rows}==set(byid)
assert all(r['COMPOSITE_STREAM_SHA256']==byid[r['composite_id']]['COMPOSITE_STREAM_SHA256'] for r in csv_rows)
del csv_rows
with (root/'composite_fold_stability_v1.csv').open(newline='') as f:
 keys=Counter((r['composite_id'],r['fold_id']) for r in csv.DictReader(f))
assert len(keys)==803316 and all(v==1 for v in keys.values())
assert {cid for cid,fid in keys}==set(byid)
assert Counter(cid for cid,fid in keys)==Counter({cid:4 for cid in byid})
print(json.dumps({'FINAL_OUTPUT_AUDIT':'PASS','files':files,'CLASS_COUNTS':dict(classes),
 'RAW_COMPOSITE_SURVIVOR_COUNT':len(raw_ids),'RAW_COMPOSITE_SURVIVOR_SET_HASH':raw['RAW_COMPOSITE_SURVIVOR_SET_HASH'],
 'DEDUPLICATED_MODEL_SURVIVOR_COUNT':len(model_ids),'COMPOSITE_SURVIVOR_SET_HASH':model['COMPOSITE_SURVIVOR_SET_HASH'],
 'MODEL_ATOMIC_FEATURE_COUNT':len(handoff['atomic_feature_ids']),'MODEL_COMPOSITE_FEATURE_COUNT':len(model_ids),
 'MODEL_FEATURE_HANDOFF_READY':handoff['MODEL_FEATURE_HANDOFF_READY'],'SURVIVOR_ALIAS_COVERAGE':'PASS',
 'MODEL_EXACT_DUPLICATE_COUNT':0,'SURVIVOR_MANIFEST_COUNT':manifest.get('n_streams')},indent=2))
