#!/usr/bin/env python3
import json
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'data/finance_router/finrome_300/judges.jsonl'
rows=[json.loads(line) for line in p.read_text().splitlines() if line.strip()]
done={(r['task_id'],r['candidate_model'],r['repeat'],r['judge_model']) for r in rows if r.get('parsed')}
required=1800
print(f'成功进度：{len(done)}/{required} ({len(done)/required:.1%})')
print(f'剩余：{max(0,required-len(done))}')
print(f'物理行数（含历史失败）：{len(rows)}')
