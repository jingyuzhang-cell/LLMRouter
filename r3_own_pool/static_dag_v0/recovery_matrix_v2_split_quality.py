"""Decomposition quality evaluation (rule-based, offline, zero new calls).
For each sampled task DAG: Coverage / Atomicity / Dependency / Executability scores,
then their relationship with the criterion-pure final quality (original reasoning
expression executed on actual extracted facts vs gold)."""
import json
import re
from collections import Counter
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE

OUT = BASE / 'recovery_matrix_v2/split_quality'

def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))

def mh_required(prog):
    vals = []
    for args in re.findall(r'\(([^()]*)\)', prog):
        for x in args.split(','):
            x = x.strip()
            if x.startswith('#') or x.startswith('const_'): continue
            try: vals.append(float(x))
            except ValueError: pass
    return sorted(set(vals))

def ops_count(prog):
    return len(re.findall(r'(?:add|subtract|multiply|divide)\(', prog))

def run():
    tasks = {t['uid']: t for t in json.loads((BASE / 'fresh_static_confirmation/TASKS.json').read_text())}
    nodes = json.loads((BASE / 'fresh_static_confirmation/NODES.json').read_text())
    resp = list(map(json.loads, (BASE / 'fresh_static_confirmation/medium_RESPONSES.jsonl').open()))
    ext = {r['task_uid']: r for r in resp if r['node_type'] == 'extraction'}
    rsn = {r['task_uid']: r for r in resp if r['node_type'] == 'reasoning'}
    ver = [r for r in resp if r['node_type'] == 'verification']
    rows = []
    for uid, t in tasks.items():
        e, r = ext.get(uid), rsn.get(uid)
        if e is None or r is None: continue
        req = mh_required(t['program'])
        try: facts = v.parse_facts(e['answer'])
        except Exception: facts = {'facts': []}
        fvals = [f['value'] for f in facts['facts']]
        # Coverage: required operands present in actual extracted facts
        present = sum(any(close(fv, x) for fv in fvals) for x in req)
        coverage = present / len(req) if req else 1.0
        # Atomicity: ops per node across the task DAG
        task_nodes = [n for n in nodes if n['task_uid'] == uid]
        def node_ops(n):
            if 'program' in n: return ops_count(n['program'])
            return 1  # transformation / verification are single-op by construction
        max_ops = max(node_ops(n) for n in task_nodes)
        atomicity = 1.0 if max_ops <= 2 else (0.5 if max_ops == 3 else 0.0)
        # Dependency: reasoning v-refs must be within the actually-extracted fact list
        dep_ok = True; n_vrefs = 0
        try:
            expr = v.decode(r['answer'])['expression']
            n_vrefs = len(re.findall(r'\bv([0-9]+)\b', expr))
            for m in re.finditer(r'\bv([0-9]+)\b', expr):
                if int(m.group(1)) >= len(fvals): dep_ok = False; break
        except Exception:
            dep_ok = False
        dependency = 1.0 if dep_ok else 0.0
        # Executability: fraction of task nodes whose outputs parse/execute
        exe = []
        exe.append(bool(facts['facts']) if e.get('status') == 'delivered' else False)
        try:
            expr = v.decode(r['answer'])['expression']; exec_calc(expr, facts); exe.append(True)
        except Exception: exe.append(False)
        tv = [x for x in ver if x['task_uid'] == uid]
        for x in tv:
            try: v.decode(x['answer']); exe.append(True)
            except Exception: exe.append(False)
        executability = sum(exe) / len(exe) if exe else 0.0
        # criterion-pure final quality
        final_q = 0
        try:
            val = exec_calc(v.decode(r['answer'])['expression'], facts)
            final_q = 1 if close(val, t['answer']) else 0
        except Exception: final_q = 0
        rows.append(dict(uid=uid, coverage=round(coverage, 3), atomicity=atomicity, max_ops=max_ops,
                         dependency=dependency, executability=round(executability, 3),
                         n_facts=len(fvals), n_required=len(req), final_q=final_q))
    # relationship with final quality
    import statistics
    def corr(xs, ys):
        n = len(xs)
        if n < 3: return None
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = sum((x - mx) ** 2 for x in xs); vy = sum((y - my) ** 2 for y in ys)
        if not vx or not vy: return None
        return cov / (vx * vy) ** 0.5
    comps = ['coverage', 'atomicity', 'dependency', 'executability']
    rel = {}
    for c in comps:
        xs = [r[c] for r in rows]; ys = [r['final_q'] for r in rows]
        ok = [r for r in rows if r['final_q'] == 1]; bad = [r for r in rows if r['final_q'] == 0]
        rel[c] = dict(pearson=round(corr(xs, ys), 3) if corr(xs, ys) is not None else None,
                      mean_final_correct=round(sum(r[c] for r in ok) / len(ok), 3) if ok else None,
                      mean_final_wrong=round(sum(r[c] for r in bad) / len(bad), 3) if bad else None)
    rep = dict(n_tasks=len(rows), n_final_correct=sum(r['final_q'] for r in rows),
               components=rel,
               ops_distribution=dict(Counter(r['max_ops'] for r in rows)),
               coverage_distribution={f'{k[0]}_{k[1]}': v for k, v in Counter((r['coverage'] > 0.999, r['final_q']) for r in rows).items()},
               rows=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'SPLIT_QUALITY.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return rep

if __name__ == '__main__':
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != 'rows'}, ensure_ascii=False, indent=1))
