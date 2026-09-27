"""P1b-1: Independent Semantic Contract Verification (deployable equiv_gold proxy).

Pipeline per task:
  1. VERIFIER (one LLM call, temp 0, model 'large', fixed JSON schema): from
     (question, numbered facts f0..fk) ONLY — no gold, no stored expression —
     emit a semantic contract C_sem = (operation_family, required_facts, roles,
     canonical_expression over f-refs, output_scale, output_unit,
     update_dependencies, confidence). Parse fail => abstain.
  2. DETERMINISTIC ADJUDICATION (zero calls): compare canonical_expression
     with the forest's stored expression via random-perturbation equivalence
     (K=32 seeded perturbations) + dependency checks + mismatch typing.
  3. Labels/policy replay: oracle equiv_gold offline only; action outcomes
     reuse frozen P0-2 A/B results (no workflow calls).

Dev = GFv2-20 (prompt design, <=3 iterations, then FROZEN).
Test = P0-2 96-task panel; PRIMARY evaluation on the 76 clean-test tasks
(96 minus the 20 dev tasks). Contract generated for all 96 (amortization
replay), frozen test metrics on 76 only.
"""
import fcntl
import json
import re
import time
from pathlib import Path

import numpy as np

from . import core
from . import run as engine
from .decompose_v1 import exec_calc

ROOT = core.ROOT
OUT = ROOT / 'static_dag_v0/graph_forest_v2_p1b'
SRC = ROOT / 'static_dag_v0/fresh_static_confirmation'
V1DIR = ROOT / 'static_dag_v0/graph_forest_v1'
MODEL = 'large'
PROMPT_VERSION = 2
FAMILIES = ['sum', 'difference', 'ratio', 'percentage', 'percentage_change',
            'product', 'average', 'other']

PROMPT = (
    'Translate the financial question into a SEMANTIC CONTRACT. You see ONLY the question '
    'and a numbered fact list. Return ONLY JSON, no prose, with exactly these fields:\n'
    '{"operation_family": one of [sum, difference, ratio, percentage, percentage_change, '
    'product, average, other],\n'
    ' "required_facts": fact ids used, e.g. ["f0","f2"],\n'
    ' "roles": mapping of semantic roles to fact ids, e.g. {"new_value":"f2","base_value":"f0"},\n'
    ' "canonical_expression": arithmetic expression over fact ids (f0,f1,...) using only '
    '+ - * / and parentheses; numeric constants 0,1,100 allowed; MUST compute the final '
    'answer to the question,\n'
    ' "output_scale": "raw" or "percent",\n'
    ' "output_unit": short unit string or "none",\n'
    ' "update_dependencies": fact ids whose value change would change the answer,\n'
    ' "confidence": number 0..1}\n'
    'CLASSIFICATION RULES: a question asking "the ratio of X to Y" or "how many times" is '
    'family "ratio" with expression X/Y and output_scale "raw" (never multiplied by 100). '
    'Use family "percentage_change" ONLY if the question literally asks for a percent '
    'increase/decrease/change; then use (new-base)/base*100. A question asking "what is X" '
    'or "what amount" is sum/difference/ratio with output_scale "raw".\n'
    'QUESTION: {q}\nFACTS: {facts}')


def contract_prompt(question, facts):
    fs = ', '.join(f"f{k}={f['value']:g}" for k, f in enumerate(facts['facts']))
    return PROMPT.replace('{q}', question).replace('{facts}', fs)


def parse_contract(answer):
    """Strict parse; returns contract dict or None (abstain)."""
    try:
        text = (answer or '').strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        c = json.loads(text)
        assert c['operation_family'] in FAMILIES
        assert isinstance(c['required_facts'], list) and c['required_facts']
        expr = c['canonical_expression']
        assert isinstance(expr, str) and len(expr) <= 300
        assert re.fullmatch(r'[f0-9+\-*/(). ]+', expr)
        assert 0.0 <= float(c['confidence']) <= 1.0
        return c
    except Exception:
        return None


def to_vref(expr):
    return re.sub(r'\bf(\d+)\b', r'v\1', expr)


def equiv(expr_a, expr_b, facts, k=32, seed=7, tol=1e-6):
    """Random-perturbation equivalence of two v-ref expressions on the fact set."""
    rng = np.random.default_rng(seed)
    n = len(facts['facts'])
    base = np.array([float(f['value']) for f in facts['facts']], dtype=float)
    agree = True
    try:
        exec_calc(expr_a, facts)
        exec_calc(expr_b, facts)
    except Exception:
        return None  # not executable -> no verdict (abstain)
    for _ in range(k):
        vals = base * rng.uniform(0.5, 1.5, n) + rng.uniform(-1, 1, n)
        pert = {'facts': [dict(value=float(v)) for v in vals]}
        try:
            a, b = exec_calc(expr_a, pert), exec_calc(expr_b, pert)
        except Exception:
            continue
        if abs(a - b) > tol * max(1.0, abs(a), abs(b)):
            agree = False
            break
    return agree


def mismatch_type(contract_expr, stored_expr, facts):
    refs = lambda e: set(re.findall(r'v(\d+)', e))
    mc, ms = refs(contract_expr), refs(stored_expr)
    if not mc <= ms:
        return 'missing_operand_in_stored'      # contract needs facts stored lacks
    if not ms <= mc:
        return 'extra_operand_in_stored'
    has100 = lambda e: bool(re.search(r'(^|[^0-9.])100([^0-9.]|$)', e))
    if has100(contract_expr) != has100(stored_expr):
        return 'scale_mismatch'
    nd = lambda e: len(re.findall(r'/', e))
    if nd(contract_expr) != nd(stored_expr):
        return 'operator_structure_mismatch'
    return 'other_mismatch'


def run(phase='dev', limit=None):
    OUT.mkdir(parents=True, exist_ok=True)
    nodes = json.loads((SRC / 'NODES.json').read_text())
    rs = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':rs')}
    dry = json.loads((ROOT / 'static_dag_v0/graph_forest_v2_p02/DRYRUN.json').read_text())
    rows = sorted([r for r in dry['fresh_rows'] if r['ok']], key=lambda r: r['uid'])
    dev = {r['task_uid'] for r in json.loads((V1DIR / 'RESULTS.json').read_text())['rows']}
    panel = [r for r in rows if (r['uid'] in dev)] if phase == 'dev' else rows
    if limit:
        panel = panel[:limit]

    engine.OUT = OUT
    path = OUT / 'RESPONSES.jsonl'
    cache = {}
    if path.exists():
        for l in path.read_text().splitlines():
            rec = json.loads(l)
            cache[rec['key']] = rec

    def call(key, prompt):
        if key in cache:
            return cache[key]['response']
        with (OUT / 'REQUESTS.jsonl').open('a') as f:
            f.write(json.dumps(dict(key=key, model=MODEL,
                                    prompt_sha256=__import__('hashlib').sha256(
                                        prompt.encode()).hexdigest(),
                                    unix_time=time.time())) + '\n')
        resp = engine.call_model(MODEL, prompt)
        rec = dict(key=key, model=MODEL, response=resp)
        with path.open('a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        cache[key] = rec
        return resp

    with (ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        try:
            proc, log, _ = engine.start_model(MODEL)
            contracts = {}
            for r in panel:
                uid = r['uid']
                node = rs[uid]
                key = f'p1b:contract:v{PROMPT_VERSION}:{uid}'
                resp = call(key, contract_prompt(node['question'], node['gold_facts']))
                c = parse_contract(resp.get('answer'))
                rec = dict(uid=uid, contract=c,
                           abstain=c is None,
                           tokens=float(resp.get('usage', {}).get('total_tokens', 0)),
                           latency=float(resp.get('latency_s', 0)))
                if c:
                    vexpr = to_vref(c['canonical_expression'])
                    try:
                        rec['contract_value'] = exec_calc(vexpr, node['gold_facts'])
                    except Exception:
                        rec['contract_value'] = None
                    rec['contract_exec'] = rec['contract_value'] is not None
                    rec['equiv_stored'] = equiv(vexpr, r['expr'], node['gold_facts'])
                contracts[uid] = rec
            out = dict(phase=phase, n=len(panel), prompt=PROMPT, model=MODEL,
                       abstain=sum(c['abstain'] for c in contracts.values()),
                       contracts=contracts)
            (OUT / f'CONTRACTS_{phase}_v{PROMPT_VERSION}.json').write_text(json.dumps(out, indent=1))
            n_exec = sum(bool(c.get('contract_exec')) for c in contracts.values())
            print(json.dumps(dict(phase=phase, n=len(panel), abstain=out['abstain'],
                                  contract_exec=n_exec)))
        finally:
            if proc is not None:
                engine.stop_model(proc, log)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('phase', choices=['dev', 'test'])
    ap.add_argument('--limit', type=int)
    a = ap.parse_args()
    run(a.phase, a.limit)
