import json
import pandas as pd
import pytest
from crypto_trading_bot.research_v2.composite_signal_search.finalize import (
    exact_duplicate_clusters, build_survivor_banks, build_model_handoff,
    _atomic_id_decoder, _exact_survivor_maps, FinalizationGateError,
)


def test_real_pipe_ids_survive_exact_dedup_and_model_handoff(tmp_path):
    a, b = 'COMP|T1|UP|aaaa', 'COMP|T1|UP|bbbb'
    trigger = 'MACD|MACD_V1|UP_EVENT|DOWN_EVENT|1H|UP'
    context = 'DMA|DMA_V1|UP_EVENT|DOWN_EVENT|2H|UP'
    rows = pd.DataFrame([dict(composite_id=cid, template_id='T1',
        composite_class='INCREMENTAL_BALANCED', COMPOSITE_STREAM_SHA256='same',
        trigger_candidate_id=trigger, context_candidate_ids=context,
        direction='UP', decision_tf='1H') for cid in (a, b)])
    rows.to_csv(tmp_path/'results.csv',index=False)
    exact_duplicate_clusters(tmp_path/'results.csv', tmp_path/'exact.csv')
    configs = {trigger:dict(family='MACD',decision_tf='1H'),
               context:dict(family='DMA',decision_tf='2H')}
    banks=build_survivor_banks(tmp_path, rows, pd.DataFrame(),
        exact_clusters=pd.read_csv(tmp_path/'exact.csv'),near_df=pd.DataFrame(),
        near_replace={},near_aliases={},config_by_id=configs)
    assert banks['n_model']==1
    entry=banks['model']['survivors'][0]
    assert entry['composite_id']==a
    assert entry['alias_composite_ids']==[b]
    assert entry['context_candidate_ids']==[context]
    assert entry['context_families']==['DMA']
    handoff=build_model_handoff(tmp_path,banks['model'],configs)
    assert set(handoff['atomic_feature_ids'])=={trigger,context}


def test_two_contexts_use_full_frozen_ids_and_unknown_fails_closed():
    a,b='DMA|A|2H|UP','MACD|B|4H|UP'
    decode=_atomic_id_decoder({a:{},b:{}})
    assert decode(a+'|'+b)==(a,b)
    assert decode(float('nan'))==()
    with pytest.raises(FinalizationGateError):
        decode(a+'|UNKNOWN')


def test_exact_then_near_keeps_a_representative_and_transitive_aliases(tmp_path):
    a,b,c=['COMP|T1|UP|'+x for x in ('a','b','c')]
    rows=pd.DataFrame([dict(composite_id=cid, composite_class='INCREMENTAL_BALANCED',
        COMPOSITE_STREAM_SHA256=sha, trigger_candidate_id='trigger',
        context_candidate_ids='ctx') for cid,sha in [(a,'same'),(b,'same'),(c,'near')]])
    replace,aliases=_exact_survivor_maps(rows)
    assert replace=={b:a}
    banks=build_survivor_banks(tmp_path,rows,pd.DataFrame(),exact_clusters=pd.DataFrame(),
        near_df=pd.DataFrame([dict(redundancy_cluster_id='NR-0',representative_composite_id=c,
            members=json.dumps([a,c]))]),near_replace={a:c},near_aliases={c:[a]},
        config_by_id={'ctx':{'family':'DMA'},'trigger':{'family':'MACD'}})
    assert banks['n_model']==1
    assert banks['model']['survivors'][0]['composite_id']==c
    assert banks['model']['survivors'][0]['alias_composite_ids']==[a,b]
