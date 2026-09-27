"""P0-2 zero-call protocol dry-run (no model calls).

Panel decision inputs, for two candidate panels:

  frozen200 (200 tasks): stored write state = clean initial DAG calls
    (fz:e1/e2/r:{uid} responses); stored facts = merged e1+e2 extractions;
    stored expression = r response. Exact follow-up target derivable only if
    stored facts[0] matches a gold-program operand (derivation string).
  fresh_static (100 tasks): nodes carry gold_facts == sorted unique program
    operands; stored expressions for all 3 models; contexts in TASKS.json.

Checks per panel:
  1. write-state availability (stored expr parses+execs on stored facts)
  2. facts[0] <-> gold-operand alignment (exact target derivability);
     for fresh_static this holds by construction
  3. C-prime source-mutation locatability: the facts[0] value must be
     findable as a numeric string in the task context (occurrence count)
  4. round-1 stored-correctness split (for the state-conditioned reporting)
  5. V1 deployable write-validation flag count (frozen checks)

Consistency: A/B inputs are the stored facts with facts[0] x1.10 (identical
objects); C-prime input = context with the facts[0] value string replaced by
its x1.10 rendering; same task ordering (uid ascending) everywhere.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, '/root/r3_own_pool')
import numpy as np

from static_dag_v0.decompose_v1 import exec_calc
from static_dag_v0.frozen200_run import BENCH, parse_router
from static_dag_v0.graph_forest_v2_write_validation import checks as wv_checks
from static_dag_v0.multidag_dynamic import parse_facts_safe
from static_dag_v0.tool_aware_v1 import decode

ROOT = Path('/root/r3_own_pool')
F200 = ROOT / 'static_dag_v0/frozen200'
FS = ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = ROOT / 'static_dag_v0/graph_forest_v2_p02'
POOL = ['medium', 'large', 'coder']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0


def _fmt_variants(v):
    out = {f'{v:g}', f'{v:.2f}', f'{v:.1f}', f'{v:,.1f}', f'{v:,.2f}'}
    if float(v).is_integer():
        out |= {str(int(v)), f'{int(v):,}'}
    return {s for s in out if s}


def locate_in_context(value, context):
    """Count occurrences of the value string; return (n_occurrences, variant)."""
    for s in sorted(_fmt_variants(value), key=len, reverse=True):
        n = context.count(s)
        if n:
            return n, s
    return 0, None


def top_model(dev, emb, qmap, n):
    types = [1.0 if n['node_type'] == t else 0.0
             for t in ['extraction', 'transformation', 'reasoning', 'verification']]
    x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
    u = x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'] - \
        ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
    return int(np.argmax(u))


def dry_fresh_static():
    nodes = json.loads((FS / 'NODES.json').read_text())
    tasks = json.loads((FS / 'TASKS.json').read_text())
    emb = np.load(FS / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(FS / 'DEV_MODELS.npz', allow_pickle=False)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    resp = {}
    for slot in POOL:
        for line in (FS / f'{slot}_RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(line)
            resp[(r['call_key'], slot)] = r
    tmap = {t['uid']: t for t in tasks}
    rows = []
    for t in tasks:
        uid = t['uid']
        node = next(n for n in nodes if n['node_id'] == f'{uid}:rs')
        m = POOL[top_model(dev, emb, qmap, node)]
        raw = resp.get((f'{uid}:rs', m))
        if raw is None or raw.get('status') != 'delivered':
            rows.append(dict(uid=uid, ok=False, reason='no_response'))
            continue
        try:
            expr = decode(raw['answer'])['expression']
            val0 = exec_calc(expr, node['gold_facts'])
        except Exception as e:
            rows.append(dict(uid=uid, ok=False, reason=f'exec:{type(e).__name__}'))
            continue
        f0 = node['gold_facts']['facts'][0]['value']
        n_occ, variant = locate_in_context(f0, t['context'])
        facts1 = json.loads(json.dumps(node['gold_facts']))
        facts1['facts'][0]['value'] = f0 * 1.10
        try:
            val1 = exec_calc(expr, facts1)
        except Exception as e:
            rows.append(dict(uid=uid, ok=False, reason=f'exec_mod:{type(e).__name__}'))
            continue
        ck, _ = wv_checks(node['question'], node['gold_facts'], expr)
        flagged = [k for k, v in ck.items() if not v]
        rows.append(dict(uid=uid, ok=True, model=m, expr=expr, facts0=f0,
                         n_occ=n_occ, variant=variant, round1_value=val0,
                         round1_correct=abs(val0 - t['answer']) <= max(1e-4, 1e-4 * abs(t['answer'])),
                         reuse_value=val1, flagged=flagged))
    return rows


def dry_frozen200():
    pol = json.loads((F200 / 'FROZEN200_POLICY.json').read_text())
    resp = {json.loads(l)['key']: json.loads(l) for l in (F200 / 'RESPONSES.jsonl').read_text().splitlines()}
    rows = []
    for t in pol['tasks']:
        uid = t['uid']
        try:
            f1, _ = parse_facts_safe(resp[f'fz:e1:{uid}']['response']['answer'])
            f2, _ = parse_facts_safe(resp[f'fz:e2:{uid}']['response']['answer'])
            expr = decode(resp[f'fz:r:{uid}']['response']['answer'])['expression']
        except Exception as e:
            rows.append(dict(uid=uid, ok=False, reason=f'parse:{type(e).__name__}'))
            continue
        merged = {'facts': f1['facts'] + f2['facts']}
        if not merged['facts']:
            rows.append(dict(uid=uid, ok=False, reason='empty_facts'))
            continue
        try:
            exec_calc(expr, merged)
        except Exception as e:
            rows.append(dict(uid=uid, ok=False, reason=f'exec:{type(e).__name__}'))
            continue
        f0 = merged['facts'][0]['value']
        ops = [float(x) for x in re.findall(r'-?\d+\.?\d*', t['derivation'])]
        align = any(abs(f0 - o) <= max(1e-6, 1e-6 * abs(o)) for o in ops)
        n_occ, variant = locate_in_context(f0, t['ctx_table'] + '\n' + t['ctx_text'])
        rows.append(dict(uid=uid, ok=True, expr=expr, facts0=f0, aligns_gold_operand=align,
                         n_occ=n_occ, variant=variant))
    return rows


def run():
    OUT.mkdir(exist_ok=False)
    fs_rows = dry_fresh_static()
    f2_rows = dry_frozen200()
    fs_ok = [r for r in fs_rows if r['ok']]
    f2_ok = [r for r in f2_rows if r['ok']]
    f2_align = [r for r in f2_ok if r['aligns_gold_operand'] and r['n_occ'] >= 1]
    f2_locatable = [r for r in f2_ok if r['n_occ'] >= 1]
    summary = dict(
        fresh_static=dict(n=100, write_state_ok=len(fs_ok),
                          source_locatable=sum(1 for r in fs_ok if r['n_occ'] >= 1),
                          unique_occurrence=sum(1 for r in fs_ok if r['n_occ'] == 1),
                          round1_correct=sum(1 for r in fs_ok if r.get('round1_correct')),
                          v1_flagged=sum(1 for r in fs_ok if r.get('flagged'))),
        frozen200=dict(n=200, write_state_ok=len(f2_ok),
                       facts0_aligns_gold_operand=len(f2_align),
                       source_locatable=len(f2_locatable),
                       aligns_and_locatable=len(f2_align)),
        recommendation=None)
    (OUT / 'DRYRUN.json').write_text(json.dumps(dict(summary=summary, fresh_rows=fs_rows,
                                                     f200_rows=f2_rows), indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    run()
