import os, sys, json, hashlib
from pathlib import Path
from collections import Counter
root=Path('/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1')
code=Path('/var/tmp/traiding_pilot_ui_workspace/phase3_staging')
sys.path.insert(0,str(code))
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['COMPOSITE_SIGNAL_SEARCH_ARTIFACT_ROOT']=str(root)
import pyarrow.parquet as pq
from crypto_trading_bot.research_v2.composite_signal_search.enumeration_authority import stream_composite_ids
from crypto_trading_bot.research_v2.composite_signal_search.finalize import assert_finalization_allowed
from crypto_trading_bot.research_v2.composite_signal_search.config import DEVELOPMENT_FOLDS
report={}
h=hashlib.sha256(); expected=set()
for cid in stream_composite_ids(artifact_root=root):
    h.update((cid+'\n').encode()); expected.add(cid)
report['COMPOSITE_ENUMERATION_SHA256']=h.hexdigest()
counts=Counter(); classes=Counter(); rows=0
for p in sorted((root/'composite_results_partial_parts_v1').glob('part-*.parquet')):
    t=pq.read_table(p,columns=['composite_id','composite_class']).to_pydict()
    counts.update(t['composite_id']); classes.update(t['composite_class']); rows+=len(t['composite_id'])
report.update(RESULT_ROW_COUNT=rows, UNIQUE_COMPOSITE_ID_COUNT=len(counts), DUPLICATE_COMPOSITE_ID_COUNT=sum(v-1 for v in counts.values()), MISSING_COMPOSITE_COUNT=len(expected-counts.keys()), UNKNOWN_COMPOSITE_COUNT=len(counts.keys()-expected), CLASS_COUNTS=dict(classes))
folds={}; nfold=0; dup=0; invalid=0
fold_ids={x[0]:1<<i for i,x in enumerate(DEVELOPMENT_FOLDS)}
for p in sorted((root/'composite_fold_partial_parts_v1').glob('part-*.parquet')):
    t=pq.read_table(p,columns=['composite_id','fold_id']).to_pydict()
    for cid,fid in zip(t['composite_id'],t['fold_id']):
        nfold+=1; bit=fold_ids.get(fid,0); invalid+=int(not bit)
        old=folds.get(cid,0); dup+=int(bool(old&bit)); folds[cid]=old|bit
report.update(FOLD_ROW_COUNT=nfold,FOLD_DUPLICATE_KEY_COUNT=dup,INVALID_FOLD_ID_COUNT=invalid,FOLD_INCOMPLETE_COMPOSITE_COUNT=sum(folds.get(cid,0)!=15 for cid in expected),FOLD_UNKNOWN_COMPOSITE_COUNT=len(folds.keys()-expected))
report['RESULT_SET_INTEGRITY']='PASS' if rows==len(counts)==len(expected)==200829 and set(counts)==expected else 'FAIL'
report['FOLD_SET_INTEGRITY']='PASS' if nfold==803316 and dup==invalid==report['FOLD_INCOMPLETE_COMPOSITE_COUNT']==report['FOLD_UNKNOWN_COMPOSITE_COUNT']==0 else 'FAIL'
report['FINALIZER_CODE_GATE']=assert_finalization_allowed(root)
print(json.dumps(report,indent=2))
