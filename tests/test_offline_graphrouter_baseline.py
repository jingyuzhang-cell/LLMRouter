import json
from pathlib import Path
import numpy as np

from scripts.run_offline_graphrouter_baseline import MODELS, make_graph


def test_graph_masks_keep_validation_and_test_edges_invisible():
    ids=['train','validation','test']
    qmap={x:np.zeros(4,dtype=np.float32) for x in ids}
    utilities={x:{m:{'utility':0.5} for m in MODELS} for x in ids}
    graph=make_graph(ids,qmap,np.zeros((4,4),dtype=np.float32),utilities,['train'],['validation'])
    visible,target=graph[-2],graph[-1]
    assert int(visible.sum())==4
    assert int(target.sum())==4
    assert not bool((visible & target).any())


def test_generated_graphrouter_report_passes_leakage_checks():
    path=Path('run_logs/offline_graphrouter_baseline/report.json')
    report=json.loads(path.read_text())
    assert report['split_counts']=={'train':60,'validation':20,'test':20}
    assert all(report['leakage_checks'].values())
    assert report['graph']['test_edges_visible_during_training'] is False
    assert report['test']['count']==20
