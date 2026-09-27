"""Graph Forest v2 reuse arm (zero model calls): stored-expression re-execution.

The v1 follow-up re-CALLED the model to regenerate the reasoning expression
(graph_forest_v1.py: sprompt(follow_q) -> expr -> exec). This arm instead
executes the expression STORED in round 1 (fresh_static_confirmation
{model}_RESPONSES.jsonl, call_key '<uid>:rs', same model the router picked in
v1) on the modified facts — index-consistent because both rounds present facts
in the node's gold_facts order (sorted(set(operand_values(program)))).

Arms compared on the same 20 tasks:
  A regen   (v1, already run): 2 calls/task, correctness vs exact expected;
  B reuse   (this script):     0 calls/task, stored expr re-executed on
                               facts[0]×1.1 — correctness inherited from the
                               round-1 expression plus guaranteed propagation.

Expected values come from graph_forest_v2/DIAGNOSTIC.json (gold-program exact
derivation). Pure post-processing of frozen artifacts; no GPU, no server.
"""
import json
from pathlib import Path

import numpy as np

from .decompose_v1 import exec_calc
from .tool_aware_v1 import decode

ROOT = Path('/root/r3_own_pool')
SRC = ROOT / 'static_dag_v0/fresh_static_confirmation'
V1 = ROOT / 'static_dag_v0/graph_forest_v1'
DG = ROOT / 'static_dag_v0/graph_forest_v2'
OUT = DG
POOL = ['medium', 'large', 'coder']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
TOL = 1e-4


def close(a, b):
    return a is not None and abs(a - b) <= max(TOL, TOL * abs(b))


def run():
    v1 = json.loads((V1 / 'RESULTS.json').read_text())
    diag = json.loads((DG / 'DIAGNOSTIC.json').read_text())
    expected = {r['task_uid']: r['expected_new'] for r in diag['rows'] if 'expected_new' in r}
    nodes = json.loads((SRC / 'NODES.json').read_text())
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    tasks = json.loads((SRC / 'TASKS.json').read_text())
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    resp = {}
    for slot in POOL:
        for line in (SRC / f'{slot}_RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(line)
            resp[(r['call_key'], slot)] = r
    tmap = {t['uid']: t for t in tasks}

    def top_model(n):  # verbatim from graph_forest_v1
        types = [1.0 if n['node_type'] == t else 0.0
                 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
        x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
        u = x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'] - \
            ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
        return int(np.argmax(u))

    rows = []
    for r in v1['rows']:
        uid = r['task_uid']
        node = next(n for n in nodes if n['node_id'] == f'{uid}:rs')
        model = POOL[top_model(node)]
        rec = dict(task_uid=uid, model=model, expected_new=expected.get(uid),
                   v1_new=r.get('new_value'), v1_verifier=r.get('verifier_accept'))
        raw = resp.get((f'{uid}:rs', model))
        if raw is None or raw.get('status') != 'delivered':
            rec.update(arm_b='NO_STORED_RESPONSE')
            rows.append(rec)
            continue
        try:
            expr = decode(raw['answer'])['expression']
        except Exception:
            rec.update(arm_b='UNDECODABLE', stored_answer=(raw.get('answer') or '')[:120])
            rows.append(rec)
            continue
        facts0 = json.loads(json.dumps(node['gold_facts']))
        facts1 = json.loads(json.dumps(node['gold_facts']))
        facts1['facts'][0]['value'] = facts1['facts'][0]['value'] * 1.10
        try:
            orig_value = exec_calc(expr, facts0)
            reuse_value = exec_calc(expr, facts1)
        except Exception as e:
            rec.update(arm_b='EXEC_FAILED', stored_expr=expr, error=f'{type(e).__name__}: {e}')
            rows.append(rec)
            continue
        gold = tmap[uid]['answer']
        rec.update(arm_b='OK', stored_expr=expr,
                   round1_value=orig_value, round1_correct=close(orig_value, gold),
                   reuse_value=reuse_value,
                   reuse_correct=close(reuse_value, expected[uid]),
                   v1_regen_correct=close(r.get('new_value'), expected[uid]))
        rows.append(rec)

    ok = [r for r in rows if r['arm_b'] == 'OK']
    summary = dict(
        n=len(rows), arm_b_ok=len(ok),
        no_response=len([r for r in rows if r['arm_b'] == 'NO_STORED_RESPONSE']),
        undecodable=len([r for r in rows if r['arm_b'] == 'UNDECODABLE']),
        exec_failed=len([r for r in rows if r['arm_b'] == 'EXEC_FAILED']),
        round1_correct=sum(r['round1_correct'] for r in ok),
        reuse_correct=sum(r['reuse_correct'] for r in ok),
        v1_regen_correct=sum(bool(r.get('v1_regen_correct')) for r in ok),
        consistency=sum(r['round1_correct'] == r['reuse_correct'] for r in ok),
        arm_b_calls_per_task=0.0, arm_a_calls_per_task=2.0,
    )
    (OUT / 'REUSE_ARM.json').write_text(json.dumps(
        dict(summary=summary, rows=rows,
             method='stored round-1 expression re-executed on facts[0]×1.1 (index-consistent: '
                    'both rounds use node gold_facts order); expected values from DIAGNOSTIC.json; '
                    'zero model calls',
             inputs=[str(SRC), str(V1 / 'RESULTS.json'), str(DG / 'DIAGNOSTIC.json')]), indent=1))
    lines = ['# Reuse Arm (B) vs Regen Arm (A) — zero model calls', '',
             f"- arm B ok: {summary['arm_b_ok']}/{summary['n']}  "
             f"(no_response={summary['no_response']}, undecodable={summary['undecodable']}, "
             f"exec_failed={summary['exec_failed']})",
             f"- round-1 expression correct: {summary['round1_correct']}",
             f"- arm B reuse correct: {summary['reuse_correct']}",
             f"- arm A regen correct (v1): {summary['v1_regen_correct']}",
             f"- round1_correct == reuse_correct per task: {summary['consistency']}/{len(ok)}", '',
             '| task | model | stored_expr | round1 | reuse | expected | v1_regen | B | A |', '|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        lines.append(f"| {r['task_uid'][:8]} | {r.get('model', '-')} | {r.get('stored_expr', r['arm_b'])} | "
                     f"{r.get('round1_value', '-')} | {r.get('reuse_value', '-')} | {r.get('expected_new', '-')} | "
                     f"{r.get('v1_new', '-')} | {r.get('reuse_correct', '-')} | {r.get('v1_regen_correct', '-')} |")
    (OUT / 'REUSE_ARM.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    run()
