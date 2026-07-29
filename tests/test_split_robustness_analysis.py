import json
from pathlib import Path

from scripts.run_split_robustness_analysis import split_labels


def test_each_seed_produces_strict_split_and_keeps_rare_in_train():
    labels={f't{i:03d}':('rare' if i==0 else 'a' if i<61 else 'b') for i in range(100)}
    for seed in range(10):
        split=split_labels(labels,seed)
        sets=[set(split[x]) for x in ('train','validation','test')]
        assert list(map(len,sets))==[60,20,20]
        assert not (sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2])
        assert 't000' in sets[0]


def test_generated_ten_split_report_is_complete_and_leakage_checked():
    report=json.loads(Path('run_logs/split_robustness_analysis/report.json').read_text())
    assert len(report['runs'])==10
    assert report['protocol']['counts']=={'train':60,'validation':20,'test':20}
    assert all(all(run['leakage_checks'].values()) for run in report['runs'])
    assert report['summary']['graph_beats_fixed_count']==3
    assert report['summary']['knn_beats_fixed_count']==3
