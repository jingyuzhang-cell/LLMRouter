#!/usr/bin/env python3
"""V6B_AUDIT：有限测量效度核查（操作者 2026-11-10 授权，边界明确）。

范围：4 个问题槽所在任务（002667/002766/300216/600556）× FC 臂 × pair1 种子，各 1 次执行。
独立记账：30 调用 / 300K token / ¥0.50 三上限，独立于已关闭的 V6 预算。
产出：完整原始节点输出（本次审计新增持久化）→ 零调用分类：评分工件 vs 能力缺口。
边界（操作者令）：重跑只验证评分规则与新执行表现，不构成对 V6 历史原始输出的追溯。
"""
import json, os, time, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import v6_executor as E

AUD = HERE / 'v6_audit'; AUD.mkdir(exist_ok=True)
E.BUDGET_F = AUD / 'budget_state.json'          # independent ledger
E.CAPS = dict(calls=30, tokens=300_000, yuan=0.50)
TARGETS = ['002667', '002766', '300216', '600556']

def main():
    if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
        raise SystemExit('REFUSED')
    pkgs = json.load(open(E.PKG_F))['packages']
    rand = {e['task']: e for e in json.load(open(E.RAND_F))['table'] if e['pair'] == 1}
    out_f = AUD / 'results_audit.json'
    results = json.load(open(out_f)) if out_f.exists() else []
    done = {r['task'] for r in results}
    for t in TARGETS:
        if t in done:
            continue
        e = rand[t]
        rec = E.logged_call_guard(E.execute, pkgs[t], 'Fixed-Composite', e['scenario'],
                                  e['inject_node'], 1)
        results.append(rec)
        json.dump(results, open(out_f, 'w'), ensure_ascii=False, indent=1)
        print(f"[audit] {t}: TP={rec.get('tp')}/{rec.get('n_slots')} calls={rec.get('calls')} "
              f"¥={rec.get('cost_yuan')}")
    print('AUDIT COMPLETE:', len(results), 'executions')

if __name__ == '__main__':
    main()
