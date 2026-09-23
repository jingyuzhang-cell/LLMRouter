"""Decomposition Loss Attribution Ablation: versions C (full-context) and D (gold facts).

Reuses frozen extraction from decomposition_benchmark. Only reasoning calls are new.
Version C: reasoning sees extracted facts + full original context.
Version D: reasoning sees gold facts (from derivation) instead of actual extraction.
"""
import argparse, fcntl, json, re, sys, time
from pathlib import Path

sys.path.insert(0, '/root/r3_own_pool')
from static_dag_v0 import run as engine
from static_dag_v0 import tool_aware_v1 as v
from static_dag_v0.decompose_v1 import exec_calc
from static_dag_v0.tatqa_benchmark_build import literals

ROOT = Path('/root/r3_own_pool/static_dag_v0')
DECOMP = ROOT / 'decomposition_benchmark'
OUT = DECOMP / 'loss_attribution'

# Prompts (frozen)
RSN_C = ('Choose the arithmetic reasoning needed to answer the financial question. '
         'You have both extracted facts AND the full original report context. '
         'Use the context to verify fact meanings, resolve ambiguities, and understand units/scales. '
         'Return ONLY JSON {{"expression":"..."}}. Reference fact values as v0,v1,... in their listed order. '
         'Allowed operators: + - * / and parentheses. Only numeric constants 0,1,100 are permitted. '
         'Do not do the arithmetic. For a percentage question multiply the ratio by 100; '
         'for an absolute amount preserve the reported units.\n'
         'QUESTION: {q}\nFACTS: {facts}\nFULL REPORT CONTEXT:\n{ctx}')

RSN_D = ('Choose the arithmetic reasoning needed to answer the financial question using the extracted facts. '
         'Return ONLY JSON {{"expression":"..."}}. Reference fact values as v0,v1,... in their listed order. '
         'Allowed operators: + - * / and parentheses. Only numeric constants 0,1,100 are permitted. '
         'Do not do the arithmetic. For a percentage question multiply the ratio by 100; '
         'for an absolute amount preserve the reported units.\n'
         'QUESTION: {q}\nFACTS: {facts}')


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def gold_facts(task):
    vals = sorted({l for l in literals(task['derivation']) if l not in (0., 1., 100.)},
                  key=lambda z: -len(str(z)))
    return dict(facts=[dict(value=x, evidence='gold') for x in vals])


def load_all():
    # Frozen tasks + gold
    freeze = json.loads((DECOMP / 'decomposition_final_tatqa_200.json').read_text())
    tq = {t['uid']: t for t in json.loads((ROOT / 'tatqa_benchmark/TASKS.json').read_text())}
    tq.update({t['uid']: t for t in json.loads((ROOT / 'scale_up/TQ_TASKS.json').read_text())})
    tasks = []
    for e in freeze:
        t = tq[e['task_id']]
        tasks.append(dict(uid=t['uid'], question=t['question'], context=t['context'],
                          answer=t['answer'], derivation=t['derivation']))

    # Frozen responses (extraction from B)
    resp = {}
    for line in (DECOMP / 'paired_run/RESPONSES.jsonl').open():
        r = json.loads(line)
        resp[r['key']] = r

    # Frozen per-task results (for A/B baselines)
    per_task = {p['task_id']: p for p in [json.loads(l) for l in (DECOMP / 'paired_run/per_task.jsonl').open()]
                if p['dataset'] == 'TAT-QA'}

    return tasks, resp, per_task


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    engine.OUT = OUT

    tasks, frozen_resp, per_task = load_all()
    print(f'loaded: {len(tasks)} tasks, {len(frozen_resp)} frozen responses')

    resp_path = OUT / 'RESPONSES.jsonl'
    cache = {}
    if resp_path.exists():
        for line in resp_path.open():
            r = json.loads(line)
            cache[r['key']] = r

    with (Path('/root/r3_own_pool/collect/logs/local_gpu.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        try:
            # ---- Version C: full-context reasoning (large) ----
            print('\n--- Version C: full-context passthrough ---')
            proc, log, _ = engine.start_model('large')
            for i, t in enumerate(tasks):
                key = f'C:{t["uid"]}'
                if key in cache:
                    continue
                ext = frozen_resp.get(f'tq:{t["uid"]}:ext')
                facts = None
                try:
                    facts = v.parse_facts(ext['answer'])
                except Exception:
                    facts = None
                facts_str = ext['answer'] if facts else json.dumps(gold_facts(t))
                prompt = RSN_C.format(q=t['question'], facts=facts_str[:2000],
                                      ctx=t['context'][:10000])
                r = engine.call_model('large', prompt)
                row = dict(key=key, model='large', version='C', task_id=t['uid'],
                           prompt=prompt, **r)
                with resp_path.open('a') as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
                cache[key] = row
                if (i + 1) % 40 == 0:
                    print(f'  C: {i+1}/{len(tasks)}')
            engine.stop_model(proc, log)
            proc = log = None

            # ---- Version D: gold facts reasoning (large) ----
            print('\n--- Version D: gold facts ---')
            proc, log, _ = engine.start_model('large')
            for i, t in enumerate(tasks):
                key = f'D:{t["uid"]}'
                if key in cache:
                    continue
                gf = gold_facts(t)
                prompt = RSN_D.format(q=t['question'], facts=json.dumps(gf, ensure_ascii=False))
                r = engine.call_model('large', prompt)
                row = dict(key=key, model='large', version='D', task_id=t['uid'],
                           prompt=prompt, gold_facts=gf, **r)
                with resp_path.open('a') as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
                cache[key] = row
                if (i + 1) % 40 == 0:
                    print(f'  D: {i+1}/{len(tasks)}')
        finally:
            if proc is not None:
                engine.stop_model(proc, log)

    # ---- Scoring ----
    import numpy as np
    print('\n' + '=' * 70)
    print('DECOMPOSITION LOSS ATTRIBUTION RESULTS')
    print('=' * 70)

    # Score each version
    results = {}
    for ver in ['A', 'B', 'C', 'D']:
        ok_list = []
        for t in tasks:
            tid = t['uid']
            if ver == 'A':
                ok = per_task[tid]['mono']
            elif ver == 'B':
                ok = per_task[tid]['dagLL']
            elif ver == 'C':
                row = cache.get(f'C:{tid}')
                ok = False
                if row and row.get('status') == 'delivered':
                    try:
                        expr = v.decode(row['answer'])['expression']
                        ext = frozen_resp.get(f'tq:{tid}:ext')
                        facts = v.parse_facts(ext['answer'])
                        val = exec_calc(expr, facts)
                        ok = close(val, t['answer'])
                    except Exception:
                        ok = False
            elif ver == 'D':
                row = cache.get(f'D:{tid}')
                ok = False
                if row and row.get('status') == 'delivered':
                    try:
                        expr = v.decode(row['answer'])['expression']
                        gf = gold_facts(t)
                        val = exec_calc(expr, gf)
                        ok = close(val, t['answer'])
                    except Exception:
                        ok = False
            ok_list.append(dict(uid=tid, ok=bool(ok)))
        results[ver] = ok_list
        q = sum(1 for r in ok_list if r['ok']) / len(ok_list)
        print(f'  {ver}: Q={q:.4f} ({q*100:.1f}%)')

    # Harm recovery analysis
    harm_uids = [r['uid'] for r in results['A'] if r['ok'] and
                 not next(x['ok'] for x in results['B'] if x['uid'] == r['uid'])]
    print(f'\nHarm set (A correct, B wrong): {len(harm_uids)} tasks')

    for ver in ['C', 'D']:
        recovered = sum(1 for uid in harm_uids
                        if next(x['ok'] for x in results[ver] if x['uid'] == uid))
        print(f'  {ver} recovers {recovered}/{len(harm_uids)} Harm tasks')

    # Loss decomposition
    qA = sum(1 for r in results['A'] if r['ok']) / len(tasks)
    qB = sum(1 for r in results['B'] if r['ok']) / len(tasks)
    qC = sum(1 for r in results['C'] if r['ok']) / len(tasks)
    qD = sum(1 for r in results['D'] if r['ok']) / len(tasks)
    print(f'\nLoss decomposition:')
    print(f'  Total loss (A - B): {(qA - qB)*100:.1f}pp')
    print(f'  Recoverable by full context (C - B): {(qC - qB)*100:.1f}pp')
    print(f'  Recoverable by gold facts (D - B): {(qD - qB)*100:.1f}pp')
    print(f'  Residual after best fix (A - max(C,D)): {(qA - max(qC,qD))*100:.1f}pp')

    # Save
    summary = {ver: dict(Q=sum(1 for r in results[ver] if r['ok']) / len(tasks)) for ver in 'ABCD'}
    summary['harm_count'] = len(harm_uids)
    for ver in ['C', 'D']:
        summary[f'{ver}_harm_recovered'] = sum(1 for uid in harm_uids
                                                if next(x['ok'] for x in results[ver] if x['uid'] == uid))
    json.dump(summary, open(OUT / 'RESULTS.json', 'w'), indent=1)
    print('\nRESULTS.json written')


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
