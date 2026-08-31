import ast, json
from collections import Counter
from pathlib import Path
ROOT=Path('/root')
def test_schema_is_frozen_and_outcome_blind():
    s=json.loads((ROOT/'phase_c9_0/CAPABILITY_SCHEMA.json').read_text()); p=json.loads((ROOT/'phase_c9_0/C9_0_PROTOCOL.json').read_text())
    assert s['status']=='FROZEN_BEFORE_POOL_CONSTRUCTION' and p['outcome_blind'] is True
    assert sum(s['primary_strata'].values())==600 and 'winner' in s['forbidden_assignment_inputs']
def test_pool_shape_and_balance():
    path=ROOT/'phase_c9_0/C9_DEV_TASKS.jsonl'
    if not path.exists(): return
    rows=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    assert len(rows)==600 and len({x['task_id'] for x in rows})==600
    assert set(Counter(x['primary_capability'] for x in rows).values())=={60}
    assert Counter(x['split'] for x in rows)=={'development_train':480,'support_matched_validation':120}
