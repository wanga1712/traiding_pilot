import sys,json,hashlib,resource
from pathlib import Path
from collections import Counter
import numpy as np
import pyarrow.parquet as pq
root=Path('/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1')
results={}
for p in sorted((root/'composite_results_partial_parts_v1').glob('part-*.parquet')):
 for row in pq.read_table(p,columns=['composite_id','COMPOSITE_STREAM_SHA256','TOTAL_SIGNALS','composite_class']).to_pylist():
  if row['composite_class'] in ('INCREMENTAL_BALANCED','INCREMENTAL_SELECTIVE'):
   results[row['composite_id']]=row
counts=Counter(); group_counts=Counter(); hashes=0; signals=0; audited=0; seen=set(); examples=[]
for p in sorted((root/'composite_survivor_streams_v1').glob('*.npz')):
 m=json.loads(Path(str(p)+'.meta.json').read_text()); cid=m['composite_id']; seen.add(cid)
 with np.load(p,allow_pickle=False) as z: ns=z['available_at_ns']
 h=hashlib.sha256();h.update(m['direction'].encode());h.update(b'\0');h.update(m['decision_tf'].encode());h.update(b'\0');h.update(np.asarray(ns,dtype=np.int64).tobytes(order='C'))
 r=results.get(cid); badhash=(h.hexdigest()!=m['COMPOSITE_STREAM_SHA256'] or r is None or h.hexdigest()!=r['COMPOSITE_STREAM_SHA256'])
 badcount=(len(ns)!=m['n_signals'] or r is None or len(ns)!=r['TOTAL_SIGNALS'])
 hashes+=int(badhash);signals+=int(badcount);audited+=1
 if (badhash or badcount) and len(examples)<10: examples.append(cid)
 counts[m['direction']+'/'+m['decision_tf']]+=len(ns);group_counts[m['direction']+'/'+m['decision_tf']]+=1
print(json.dumps({'SURVIVOR_STREAMS_AUDITED':audited,'SURVIVOR_STREAM_HASH_MISMATCH_COUNT':hashes,'SURVIVOR_STREAM_SIGNAL_COUNT_MISMATCH_COUNT':signals,'MISSING_SURVIVOR_SHARDS':len(results.keys()-seen),'UNEXPECTED_SURVIVOR_SHARDS':len(seen-results.keys()),'SURVIVOR_STREAM_HASH_AUDIT':'PASS' if hashes==signals==0 and seen==results.keys() else 'FAIL','GROUP_SIGNAL_COUNTS':dict(counts),'GROUP_SURVIVOR_COUNTS':dict(group_counts),'EXAMPLES':examples,'AUDIT_PEAK_RSS_GB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024**2},indent=2))
