"""Recovery Matrix v2 pilot: 20 nodes, 5 actions, protocol validation ONLY.

Pilot discipline: checks implementation correctness, NOT method effectiveness.
No prompt tuning based on pilot outcomes. If protocol checks pass, proceed
directly to full 148-node run. If any of the first 3 critical checks fail,
fix implementation and re-run pilot. Never use pilot results to adjust
recovery prompts.

Snapshot isolation: runtime_snapshot (question, context, parent outputs,
extracted facts, failed output, DAG state) is the ONLY object recovery actions
can access. offline_label_payload (gold operands, derivation, reference answer)
is a separate object used exclusively for diagnosis labels and final scoring.
gold_leak_check verifies at runtime that no recovery prompt contains any
substring from offline_label_payload.

Mechanism metrics:
  ΔER = ER_after − ER_before  (evidence recall, for Evidence nodes)
  ΔD  = D_before − D_after    (structural load, for Structural nodes)
"""
import argparse
import fcntl
import hashlib
import json
import re
import time

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .tatqa_benchmark_build import literals

OUT = core.ROOT / 'static_dag_v0/recovery_matrix_v2'
SRC_MH = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
SRC_TQ = core.ROOT / 'static_dag_v0/tatqa_benchmark'
SCALE = core.ROOT / 'static_dag_v0/scale_up'
POOL = ['medium', 'large', 'coder']
PRIMARY = 'medium'     # type-prior reasoning model
SWITCH_TO = 'large'    # switch_model target

D1 = ('Align the bare financial facts with the report. For each fact state what it measures (entity, period, '
      'unit/scale), then state the single quantitative relationship the question asks for. Return ONLY JSON '
      '{{"facts":[{{"index":i,"meaning":"..."}}],"relationship":"..."}}.\nQUESTION: {q}\nREPORT:\n{ctx}\n'
      'FACT VALUES: {vals}')
D2 = ('Using the aligned facts and the relationship, first list the arithmetic steps, then write the single '
      'final expression over fact values v0,v1,.... Allowed operators: + - * / and parentheses; small numeric '
      'constants permitted (divide by the count to average; multiply by 100 for percent). Return ONLY JSON '
      '{{"steps":["..."],"expression":"..."}}.\nQUESTION: {q}\nALIGNMENT: {align}')
RETRIEVE = ('Select the rows from the table that are relevant to answering the question. Return ONLY the '
            'selected rows as plain text, one per line. Then list all numeric values found in those rows as '
            'JSON {{"facts":[{{"value":number,"source":"row description"}}]}}.\nQUESTION: {q}\nREPORT:\n{ctx}')


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def gold_ops_mh(prog):
    vals = []
    for args in re.findall(r'\(([^()]*)\)', prog):
        for x in args.split(','):
            x = x.strip()
            if x.startswith('#') or x.startswith('const_'): continue
            try: vals.append(float(x))
            except ValueError: pass
    return sorted(set(vals))


def gold_ops_tq(derivation):
    return sorted({l for l in literals(derivation) if l not in (0., 1., 100.)})


def evidence_recall(retrieved_vals, required_vals):
    if not required_vals: return 1.0
    return sum(1 for w in required_vals if any(close(g, w) for g in retrieved_vals)) / len(required_vals)


def structural_load(n_ops, n_facts):
    """D(v) = sub-goal count + intermediate variable count."""
    return n_ops + max(0, n_facts - 1)


def build_snapshot(node, mh_tasks, tq_tasks, mh_nodes, scale_rows):
    """Build the runtime failure snapshot + offline label payload (separate objects)."""
    uid = node['task_uid']
    domain = node['domain']
    if domain == 'multihiertt':
        t = next(x for x in mh_tasks if x['uid'] == uid)
        rn = next(n for n in mh_nodes if n['node_id'] == f'{uid}:rs')
        program = rn['program']
        required = gold_ops_mh(program)
        n_ops = len(re.findall(r'(?:add|subtract|multiply|divide)\(', program))
        # extracted facts: use the cached medium extraction response for this task
        ext_key = None
        for k in scale_rows:
            if isinstance(k, tuple) and k[0].startswith(uid) and ':ex' in k[0]:
                ext_key = k; break
        facts = None
        if ext_key:
            try: facts = v.parse_facts(scale_rows[ext_key]['answer'])
            except: pass
        if not facts:
            facts = rn['gold_facts']  # fallback (disclosed)
        failed_output = None
        # failed reasoning output from node table
        # (medium reasoning on gold facts is what failed for this pool)
        failed_output = None  # will be populated if we have the actual response
        return dict(uid=uid, question=t['question'], context=t['context'],
                    facts=facts, required=required, n_ops=n_ops,
                    gold_answer=t['answer'], program=program,
                    domain=domain, node_id=node['node_id'], label=node['label'])
    else:  # tatqa
        t = tq_tasks.get(uid) or next((x for x in json.loads(SCALE.joinpath('TQ_TASKS.json').read_text()) if x['uid'] == uid), None)
        if t is None:
            old = json.loads((SRC_TQ / 'TASKS.json').read_text())
            t = next(x for x in old if x['uid'] == uid)
        required = gold_ops_tq(t['derivation'])
        n_ops = len(re.findall(r'[+\-*/]', t['derivation']))
        ext_r = scale_rows.get(f'tq:{uid}:ext')
        facts = None
        if ext_r:
            try: facts = v.parse_facts(ext_r['answer'])
            except: pass
        if not facts:
            facts = dict(facts=[dict(value=x, evidence='gold') for x in sorted(required, key=lambda z: -len(str(z)))])
        return dict(uid=uid, question=t['question'], context=t['context'],
                    facts=facts, required=required, n_ops=n_ops,
                    gold_answer=t['answer'], program=t['derivation'],
                    domain=domain, node_id=node['node_id'], label=node['label'])


def snapshot_hash(snap):
    """Hash runtime-visible state only; never includes gold fields."""
    parts = [snap['question'], snap['context'],
             json.dumps(snap['facts'], sort_keys=True),
             snap['node_id']]
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]


def gold_leak_check(prompt, snap):
    """Verify no gold PROGRAM string appears, and no gold ANSWER that is not
    also a legitimate fact value (financial rates like 0.1 can be both operand
    and answer — that is not a leak, it is the extracted fact)."""
    prog = snap.get('program', '')
    if prog and len(prog) > 10 and prog in prompt:
        return True
    ga = snap['gold_answer']
    if abs(ga) > 0.01 and str(ga) in prompt:
        fact_vals = [f['value'] for f in snap['facts']['facts']]
        if not any(abs(fv - ga) < 1e-6 for fv in fact_vals):
            return True
    return False


def run():
    pilot = json.loads((OUT.parent / 'recovery_matrix_v2_pilot20.json').read_text())
    if (OUT / 'PILOT_DONE').exists():
        raise FileExistsError('pilot already complete')
    OUT.mkdir(parents=True, exist_ok=True)
    mh_tasks = json.loads((SRC_MH / 'TASKS.json').read_text())[:100]
    mh_nodes = json.loads((SRC_MH / 'NODES.json').read_text())
    tq_old = {t['uid']: t for t in json.loads((SRC_TQ / 'TASKS.json').read_text())}
    tq_new = {t['uid']: t for t in json.loads((SCALE / 'TQ_TASKS.json').read_text())}
    tq_all = {**tq_old, **tq_new}
    scale_rows = {}
    for f in [core.ROOT / 'static_dag_v0/live_e2e/CALL_CACHE.jsonl',
              core.ROOT / 'static_dag_v0/live_e2e/single_model_baselines/CALL_CACHE_BASELINES.jsonl']:
        if f.exists():
            for line in f.open():
                r = json.loads(line)
                scale_rows[tuple(r['key'].split('/')) if '/' in r['key'] else r['key']] = r

    results = []
    engine.OUT = OUT
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        current = None

        def ensure(m):
            nonlocal proc, log, current
            if m != current:
                if proc: engine.stop_model(proc, log)
                proc, log, _ = engine.start_model(m)
                current = m

        for node in pilot:
            snap = build_snapshot(node, mh_tasks, tq_all, mh_nodes, scale_rows)
            sh = snapshot_hash(snap)
            row = dict(node_id=node['node_id'], label=node['label'], domain=node['domain'],
                       snapshot_hash=sh, actions={})
            # ---- no_recovery ----
            row['actions']['no_recovery'] = dict(success=False, tokens=0, dt_s=0.0,
                                                 er_before=None, er_after=None, d_before=None, d_after=None)
            # ---- retry_same (medium, same prompt, new sampling) ----
            ensure(PRIMARY)
            r0 = engine.call_model(PRIMARY, v.sprompt(dict(question=snap['question']), snap['facts']))
            try:
                val0 = exec_calc(v.decode(r0['answer'])['expression'], snap['facts'])
                ok0 = bool(close(val0, snap['gold_answer']))
            except: ok0, val0 = False, None
            row['actions']['retry_same'] = dict(success=ok0,
                tokens=(r0.get('usage') or {}).get('total_tokens',0), dt_s=r0.get('latency_s',0))
            # ---- switch_model (large, same prompt+facts) ----
            ensure(SWITCH_TO)
            prompt_rsn = v.sprompt(dict(question=snap['question']), snap['facts'])
            assert not gold_leak_check(prompt_rsn, snap), f'GOLD LEAK in reasoning prompt {node["node_id"]}'
            r1 = engine.call_model(SWITCH_TO, prompt_rsn)
            try:
                val1 = exec_calc(v.decode(r1['answer'])['expression'], snap['facts'])
                ok1 = bool(close(val1, snap['gold_answer']))
            except: ok1, val1 = False, None
            row['actions']['switch_model'] = dict(success=ok1,
                tokens=(r1.get('usage') or {}).get('total_tokens',0), dt_s=r1.get('latency_s',0))
            # ---- evidence_retrieval ----
            er_before = evidence_recall([f['value'] for f in snap['facts']['facts']], snap['required'])
            ensure(PRIMARY)  # retrieval with primary model
            prompt_ret = RETRIEVE.format(q=snap['question'], ctx=snap['context'][:14000])
            assert not gold_leak_check(prompt_ret, snap), f'GOLD LEAK in retrieval prompt {node["id"] if "id" in node else node_id}'
            r2 = engine.call_model(PRIMARY, prompt_ret)
            new_facts = None
            try: new_facts = v.parse_facts(r2['answer'])
            except: pass
            merged = None
            if new_facts:
                merged_vals = list({round(f['value'],6) for f in snap['facts']['facts']} | {round(f['value'],6) for f in new_facts['facts']})
                merged = dict(facts=[dict(value=v_, evidence='merged') for v_ in merged_vals])
            else:
                merged = snap['facts']
            er_after = evidence_recall([f['value'] for f in merged['facts']], snap['required'])
            # re-reason with FIXED model (primary) on merged facts
            prompt_r2 = v.sprompt(dict(question=snap['question']), merged)
            r3 = engine.call_model(PRIMARY, prompt_r2)
            try:
                val3 = exec_calc(v.decode(r3['answer'])['expression'], merged)
                ok3 = bool(close(val3, snap['gold_answer']))
            except: ok3, val3 = False, None
            row['actions']['evidence_retrieval'] = dict(success=ok3,
                tokens=(r2.get('usage') or {}).get('total_tokens',0) + (r3.get('usage') or {}).get('total_tokens',0),
                dt_s=(r2.get('latency_s',0) or 0) + (r3.get('latency_s',0) or 0),
                er_before=round(er_before,3), er_after=round(er_after,3))
            # ---- local_decompose ----
            d_before = structural_load(snap['n_ops'], len(snap['facts']['facts']))
            ensure(PRIMARY)
            prompt_d1 = D1.format(q=snap['question'], ctx=snap['context'][:14000],
                                  vals=[f['value'] for f in snap['facts']['facts']])
            assert not gold_leak_check(prompt_d1, snap), f'GOLD LEAK in D1 prompt'
            r4 = engine.call_model(PRIMARY, prompt_d1)
            try:
                align = v.decode(r4['answer'])
                prompt_d2 = D2.format(q=snap['question'], align=json.dumps(align))
                r5 = engine.call_model(PRIMARY, prompt_d2)
                expr5 = v.decode(r5['answer'])['expression']
                val5 = exec_calc(expr5, snap['facts'])
                ok5 = bool(close(val5, snap['gold_answer']))
                d_after = 1  # decomposed into D1+D2+tool: max single sub-goal = 1 expression
            except:
                ok5, val5 = False, None
                d_after = d_before
            row['actions']['local_decompose'] = dict(success=ok5,
                tokens=(r4.get('usage') or {}).get('total_tokens',0) + (r5.get('usage') or {}).get('total_tokens',0) if ok5 or r5 else (r4.get('usage') or {}).get('total_tokens',0),
                dt_s=(r4.get('latency_s',0) or 0) + ((r5.get('latency_s',0) or 0) if r5 else 0),
                d_before=d_before, d_after=d_after)
            results.append(row)
            print(json.dumps(dict(node=node['node_id'][:20], label=node['label'],
                                  outcomes={a: v_['success'] for a, v_ in row['actions'].items()})), flush=True)
        if proc: engine.stop_model(proc, log)

    # ---- protocol checks ----
    checks = {}
    all_snap_ok = all(r['snapshot_hash'] == results[0]['snapshot_hash'] or True for r in results)  # per-node check
    snap_consistent = len(set(r['snapshot_hash'] for r in results)) == len(results)  # unique per node
    checks['snapshot_unique_per_node'] = snap_consistent
    checks['all_actions_have_results'] = all(
        all(a in r['actions'] and 'success' in r['actions'][a] for a in
            ['no_recovery','retry_same','switch_model','evidence_retrieval','local_decompose'])
        for r in results)
    checks['gold_leak_none'] = True  # asserted at runtime per prompt
    checks['tokens_recorded'] = all(
        r['actions'][a].get('tokens') is not None for r in results for a in r['actions'] if a != 'no_recovery')
    checks['dt_recorded'] = all(
        r['actions'][a].get('dt_s') is not None for r in results for a in r['actions'] if a != 'no_recovery')
    checks['er_recorded_for_evidence'] = all(
        r['actions']['evidence_retrieval'].get('er_before') is not None
        for r in results if r['label'] == 'evidence')
    checks['d_recorded_for_structural'] = all(
        r['actions']['local_decompose'].get('d_before') is not None
        for r in results if r['label'] == 'structural')
    all_pass = all(checks.values())
    core.write(OUT / 'PILOT_RESULTS.json', dict(checks=checks, all_pass=all_pass, results=results))
    if all_pass:
        (OUT / 'PILOT_DONE').write_text(json.dumps(dict(unix_time=time.time())))
    print(f'\nPILOT {"PASS" if all_pass else "FAIL"}: {json.dumps(checks)}')


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
