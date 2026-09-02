import json
from collections import Counter
from pathlib import Path
MODELS={'deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash'}
def test_balanced_plan_and_disjoint_split():
 root=Path(__file__).resolve().parents[1]; split=json.loads((root/'phase_e4_0/E4_0_B_SPLIT.json').read_text()); plans=[json.loads(x) for x in (root/'phase_e4_0/E4_0_B_EXPLORATION_PLAN.jsonl').read_text().splitlines() if x]
 assert len(plans)==200 and len(split['exploration_train_task_ids'])==40 and len(split['internal_holdout_task_ids'])==20
 assert not set(split['exploration_train_task_ids'])&set(split['internal_holdout_task_ids'])
 for tid in split['exploration_train_task_ids']:
  ps=[p for p in plans if p['task_id']==tid]; assert len(ps)==5
  for node in ('N1','N2','N3','N4'): assert {p['assignment'][node] for p in ps}==MODELS
 assert all(p['behavior_probability']==.2 and not p['action_depends_on_state'] for p in plans)
