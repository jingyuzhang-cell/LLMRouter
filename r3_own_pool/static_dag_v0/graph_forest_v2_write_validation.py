"""Graph Forest v2 — DEPLOYABLE write-time validation (zero model calls).

Validates a stored reasoning expression at forest-write time using ONLY
deployable signals (question text, provided facts, the expression itself).
Gold answers / gold programs are NEVER consulted — they are reserved for the
oracle write-validation arm and offline analysis only.

Checks (flag = untrusted write):
  exec        parses under the executor grammar, executes, finite, bounded
  ref_complete every provided fact is referenced (benchmark construction:
              facts == the gold program's operand set, so all belong in the
              expression; domain-specific, documented)
  percent     question asks percent/percentage  <=>  expression scales by 100
  magnitude   sum-type question: result >= max(facts); average-type: result
              within [min(facts), max(facts)]
  rel_div     relative-change keywords (ratio/proportion/fraction/%) require
              a division in the expression

Output: WRITE_VALIDATION.json with per-task flags, cross-tabulated against the
oracle round-1 correctness (12 right / 8 wrong on this panel) to measure the
deployable validator's precision/recall BEFORE any repair-retry calls.
"""
import json
import re
from pathlib import Path

import numpy as np

from .decompose_v1 import exec_calc
from .tool_aware_v1 import decode

ROOT = Path('/root/r3_own_pool')
SRC = ROOT / 'static_dag_v0/fresh_static_confirmation'
V1 = ROOT / 'static_dag_v0/graph_forest_v1'
GF2 = ROOT / 'static_dag_v0/graph_forest_v2'
POOL = ['medium', 'large', 'coder']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0

PCT_WORDS = ('percent', 'percentage', '%')
REL_WORDS = ('percent', 'percentage', '%', 'ratio', 'proportion', 'fraction')
SUM_WORDS = ('sum', 'total', 'combined', 'altogether', 'in all')
AVG_WORDS = ('average', 'mean', 'avg')


def checks(question, facts, expr):
    """Return dict of check -> passed (True = ok)."""
    out = dict(exec=True, ref_complete=True, percent=True, magnitude=True, rel_div=True)
    try:
        value = exec_calc(expr, facts)
    except Exception:
        out['exec'] = False
        return out, None
    vals = [abs(float(f['value'])) for f in facts['facts']]
    refs = set(re.findall(r'v(\d+)', expr))
    out['ref_complete'] = len(refs) >= len(vals) and all(int(r) < len(vals) for r in refs)
    q = question.lower()
    has_pct_word = any(w in q for w in PCT_WORDS)
    has_100 = bool(re.search(r'(^|[^0-9.])100(\.0*)?([^0-9.]|$)', expr)) and '* 100' in expr or \
        bool(re.search(r'\*\s*100\b', expr))
    out['percent'] = (has_pct_word == has_100)
    if any(w in q for w in SUM_WORDS):
        out['magnitude'] = abs(value) >= max(vals) - 1e-9
    elif any(w in q for w in AVG_WORDS):
        out['magnitude'] = min(vals) - 1e-9 <= abs(value) <= max(vals) + 1e-9
    if any(w in q for w in REL_WORDS):
        out['rel_div'] = '/' in re.sub(r'\s', '', expr)
    return out, value


def run():
    v1 = json.loads((V1 / 'RESULTS.json').read_text())
    reuse = json.loads((GF2 / 'REUSE_ARM.json').read_text())
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
    rr = {r['task_uid']: r for r in reuse['rows']}

    def top_model(n):  # verbatim from graph_forest_v1
        types = [1.0 if n['node_type'] == t else 0.0
                 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
        x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
        u = x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'] - \
            ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
        return int(np.argmax(u))

    rows = []
    for rec in v1['rows']:
        uid = rec['task_uid']
        node = next(n for n in nodes if n['node_id'] == f'{uid}:rs')
        model = POOL[top_model(node)]
        expr = decode(resp[(f'{uid}:rs', model)]['answer'])['expression']
        ck, value = checks(node['question'], node['gold_facts'], expr)
        flagged = [k for k, ok in ck.items() if not ok]
        rows.append(dict(task_uid=uid, model=model, question=node['question'],
                         stored_expr=expr, exec_value=value,
                         round1_correct=rr[uid]['round1_correct'], checks=ck,
                         flagged=flagged, trusted=not flagged))
    tp = sum(1 for r in rows if not r['trusted'] and not r['round1_correct'])
    fp = sum(1 for r in rows if not r['trusted'] and r['round1_correct'])
    fn = sum(1 for r in rows if r['trusted'] and not r['round1_correct'])
    tn = sum(1 for r in rows if r['trusted'] and r['round1_correct'])
    summary = dict(n=len(rows),
                   flagged=len([r for r in rows if not r['trusted']]),
                   validator_confusion=dict(TP=tp, FP=fp, FN=fn, TN=tn),
                   recall=tp / max(1, tp + fn), precision=tp / max(1, tp + fp))
    (GF2 / 'WRITE_VALIDATION.json').write_text(json.dumps(
        dict(summary=summary, rows=rows,
             checks_doc='exec / ref_complete / percent / magnitude / rel_div — '
                        'deployable only, no gold consulted'), indent=1))
    print(json.dumps(summary, indent=1))
    for r in rows:
        print(f"{r['task_uid'][:8]} {'OK ' if r['round1_correct'] else 'BAD'} "
              f"{'FLAG:' + ','.join(r['flagged']) if r['flagged'] else 'trust'}  {r['stored_expr'][:44]}")


if __name__ == '__main__':
    run()
