"""FLARE-DAG Phase 1: chain-consistent v-node calls for (L,C) and (M,L).

(L,C): v(coder) fed with r(large) expression + e1/e2(large) facts
(M,L): v(large) fed with r(medium) expression + e1/e2(large) facts

e1/e2 always large (frozen). Prompts match original v-node format exactly.
"""
import argparse
import fcntl
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, '/root/r3_own_pool')

from static_dag_v0 import run as engine

ROOT = Path('/root/r3_own_pool/static_dag_v0')
MDIR = ROOT / 'multidag_dynamic_120'
ADIR = ROOT / 'multidag_ablation_120'
OUT = ROOT / 'frp_dag'

V_PROMPT = ('You are verifying a computed answer for a financial question. '
            'Given the extracted facts and a proposed expression, check that every referenced value '
            'binds to the correct fact and that the arithmetic is right, recompute independently, '
            'then return ONLY JSON {{"value": <number>}} with the corrected final value '
            '(preserve reported units; percentages as ratios x100).\n'
            'QUESTION: {q}\nFACTS: {facts}\nPROPOSED EXPRESSION: {expr}')


def load_inputs():
    """Load r expressions + e1/e2 facts + gold answers for all 120 tasks."""
    policy = json.loads((MDIR / 'POLICY.json').read_text())
    tasks = {t['uid']: t for t in policy['tasks']}

    # Load e1/e2 large facts
    facts = {}
    for line in (MDIR / 'RESPONSES.jsonl').open():
        r = json.loads(line)
        key = r['key']
        node = key.split(':')[0]
        tid = key.split(':', 1)[1]
        if node == 'e1' and r['model'] == 'large':
            resp = r.get('response') or {}
            if isinstance(resp, str):
                try: resp = json.loads(resp)
                except: resp = {}
            facts.setdefault(tid, {})['e1'] = resp.get('answer', '')

    # Also load e2 from the main panel
    for line in (MDIR / 'RESPONSES.jsonl').open():
        r = json.loads(line)
        key = r['key']
        node = key.split(':')[0]
        tid = key.split(':', 1)[1]
        if node == 'e2' and r['model'] == 'large':
            resp = r.get('response') or {}
            if isinstance(resp, str):
                try: resp = json.loads(resp)
                except: resp = {}
            facts.setdefault(tid, {})['e2'] = resp.get('answer', '')

    # Load r expressions: r(large) from ablation, r(medium) from main panel
    r_exprs = {}
    for line in (MDIR / 'RESPONSES.jsonl').open():
        r = json.loads(line)
        key = r['key']
        node = key.split(':')[0]
        tid = key.split(':', 1)[1]
        resp = r.get('response') or {}
        if isinstance(resp, str):
            try: resp = json.loads(resp)
            except: resp = {}
        ans = resp.get('answer', '')
        if node == 'r' and r['model'] == 'medium' and tid not in r_exprs:
            r_exprs.setdefault(tid, {})['medium'] = ans
    for line in (ADIR / 'RESPONSES.jsonl').open():
        r = json.loads(line)
        key = r['key']
        node = key.split(':')[0]
        tid = key.split(':', 1)[1]
        resp = r.get('response') or {}
        if isinstance(resp, str):
            try: resp = json.loads(resp)
            except: resp = {}
        ans = resp.get('answer', '')
        if node == 'r' and r['model'] == 'large' and tid not in r_exprs.get(tid, {}):
            r_exprs.setdefault(tid, {})['large'] = ans

    return tasks, facts, r_exprs


def extract_facts_json(e1_answer, e2_answer):
    """Combine e1 and e2 facts into a single JSON list."""
    all_facts = []
    for ans in [e1_answer, e2_answer]:
        if not ans:
            continue
        t = re.sub(r'^```(?:json)?\s*\n?', '', ans.strip())
        t = re.sub(r'\n?```\s*$', '', t)
        try:
            obj = json.loads(t)
            if 'facts' in obj:
                all_facts.extend(obj['facts'])
        except Exception:
            pass
    return json.dumps(dict(facts=all_facts), ensure_ascii=False)


def extract_expression(r_answer):
    """Extract expression string from r node output."""
    if not r_answer:
        return None
    t = re.sub(r'^```(?:json)?\s*\n?', '', r_answer.strip())
    t = re.sub(r'\n?```\s*$', '', t)
    try:
        obj = json.loads(t)
        return obj.get('expression')
    except Exception:
        return None


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    engine.OUT = OUT

    tasks, facts, r_exprs = load_inputs()
    print(f'loaded: {len(tasks)} tasks, {len(facts)} fact sets, {len(r_exprs)} r expressions')

    resp_path = OUT / 'phase1_responses.jsonl'
    cache = {}
    if resp_path.exists():
        for line in resp_path.open():
            r = json.loads(line)
            cache[r['key']] = r

    # Build call plan
    calls = []  # (model, key, prompt, meta)
    for tid, task in tasks.items():
        q = task['question']
        gold = task['answer']

        # Get combined facts
        f = facts.get(tid, {})
        combined = extract_facts_json(f.get('e1', ''), f.get('e2', ''))

        # (L,C): v(coder) with r(large) expression
        r_l = r_exprs.get(tid, {}).get('large')
        if r_l:
            expr_l = extract_expression(r_l)
            if expr_l:
                prompt = V_PROMPT.format(q=q, facts=combined, expr=expr_l)
                calls.append(('coder', f'LC:{tid}', prompt,
                              dict(task_id=tid, combo='LC', r_model='large', v_model='coder',
                                   gold=gold, expression=expr_l)))

        # (M,L): v(large) with r(medium) expression
        r_m = r_exprs.get(tid, {}).get('medium')
        if r_m:
            expr_m = extract_expression(r_m)
            if expr_m:
                prompt = V_PROMPT.format(q=q, facts=combined, expr=expr_m)
                calls.append(('large', f'ML:{tid}', prompt,
                              dict(task_id=tid, combo='ML', r_model='medium', v_model='large',
                                   gold=gold, expression=expr_m)))

    print(f'planned calls: {len(calls)}')
    by_model = {}
    for m, k, p, meta in calls:
        by_model.setdefault(m, []).append((k, p, meta))
    for m, items in by_model.items():
        print(f'  {m}: {len(items)} calls')

    # Execute
    with (Path('/root/r3_own_pool/collect/logs/local_gpu.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        cur = None
        try:
            def ensure(model):
                nonlocal proc, log, cur
                if model != cur:
                    if proc is not None:
                        engine.stop_model(proc, log)
                        proc = log = None
                    proc, log, _ = engine.start_model(model)
                    cur = model

            def call(model, key, prompt, meta):
                if key in cache:
                    return cache[key]
                ensure(model)
                r = engine.call_model(model, prompt)
                row = dict(key=key, model=model, prompt=prompt, **meta, **r)
                with resp_path.open('a') as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
                cache[key] = row
                return row

            # Group by model to minimize switches
            for model in ['large', 'coder']:
                if model not in by_model:
                    continue
                items = by_model[model]
                print(f'\n--- {model}: {len(items)} calls ---')
                for i, (key, prompt, meta) in enumerate(items):
                    call(model, key, prompt, meta)
                    if (i + 1) % 20 == 0:
                        print(f'  {i+1}/{len(items)} done')
        finally:
            if proc is not None:
                engine.stop_model(proc, log)

    # Score
    from math import comb
    import numpy as np

    def parse_value(ans):
        if not ans:
            return None
        t = re.sub(r'^```(?:json)?\s*\n?', '', ans.strip())
        t = re.sub(r'\n?```\s*$', '', t)
        try:
            return json.loads(t).get('value')
        except:
            return None

    def close(a, b):
        return a is not None and b is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))

    results = {}
    for combo in ['LC', 'ML']:
        combo_results = []
        for line in resp_path.open():
            r = json.loads(line)
            if r.get('combo') != combo:
                continue
            val = parse_value(r.get('answer'))
            ok = close(val, r.get('gold'))
            tok = (r.get('usage') or {}).get('total_tokens', 0)
            combo_results.append(dict(task_id=r['task_id'], ok=bool(ok), tokens=tok,
                                      value=val, gold=r.get('gold')))
        n = len(combo_results)
        if n > 0:
            q = sum(1 for r in combo_results if r['ok']) / n
            c = np.mean([r['tokens'] for r in combo_results])
            results[combo] = dict(n=n, Q=round(q, 4), C=round(float(c), 1))
            print(f'\n{combo}: n={n} Q={q:.4f} C={c:.0f}')

    # Compare with existing (M,C)
    mc_results = []
    for line in (MDIR / 'RESPONSES.jsonl').open():
        r = json.loads(line)
        if r['key'].startswith('v:') and r['model'] == 'coder':
            tid = r['key'].split(':', 1)[1]
            resp = r.get('response') or {}
            if isinstance(resp, str):
                try: resp = json.loads(resp)
                except: resp = {}
            val = parse_value(resp.get('answer', ''))
            task = tasks.get(tid, {})
            ok = close(val, task.get('answer'))
            tok = (resp.get('usage') or {}).get('total_tokens', 0)
            mc_results.append(dict(task_id=tid, ok=bool(ok), tokens=tok))
    if mc_results:
        n = len(mc_results)
        q = sum(1 for r in mc_results if r['ok']) / n
        c = np.mean([r['tokens'] for r in mc_results])
        results['MC'] = dict(n=n, Q=round(q, 4), C=round(float(c), 1))
        print(f'MC (existing): n={n} Q={q:.4f} C={c:.0f}')

    # Pareto analysis
    print('\n=== Phase 1: Pareto Space Check ===')
    pts = [(v['Q'], v['C'], k) for k, v in results.items()]
    for q, c, k in sorted(pts, key=lambda x: -x[0]):
        dominated = any(q2 >= q and c2 <= c and (q2 > q or c2 < c)
                        for q2, c2, _ in pts if (q2, c2) != (q, c))
        print(f'  {k}: Q={q:.4f} C={c:.0f} {"[DOMINATED]" if dominated else "[NON-DOMINATED]"}')

    non_dominated = [(q, c, k) for q, c, k in pts
                     if not any(q2 >= q and c2 <= c and (q2 > q or c2 < c)
                                for q2, c2, _ in pts if (q2, c2) != (q, c))]
    print(f'\nNon-dominated solutions: {len(non_dominated)}')
    if len(non_dominated) >= 2:
        print('>>> PARETO SPACE EXISTS → proceed to Phase 2')
    else:
        print('>>> PARETO SPACE INSUFFICIENT → stop')

    json.dump(results, open(OUT / 'phase1_results.json', 'w'), indent=1)
    print('\nphase1_results.json written')


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
