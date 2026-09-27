"""Graph Forest v2 — 3x2 paired experiment: write-time validation x follow-up
strategy (real GPU calls, ~75 total; see PROTOCOL in graph_forest_v2_3x2.py).

Arms:
  follow-up strategy on the SAME 20 tasks and the SAME +10% fact modification:
    A reuse    re-execute the stored expression on modified facts (0 calls)
    B regen    re-generate reasoning (v1 arm; FROZEN results reused, temp 0)
    C full     full-chain rerun: extraction(follow_q) -> reasoning -> verifier
  write condition:
    V0         store round-1 expression as-is (frozen responses)
    V1D        deployable write validation -> flagged nodes get ONE
               feedback-targeted repair retry (new calls, this script)
    V1O        oracle selection (retry exactly the 8 known-wrong nodes) with
               the SAME deployable feedback — upper bound, no gold leaked
               into prompts

Analysis (PAIRED_3X2.json / REPORT.md): 6-cell Q/calls/tokens/latency table,
validator precision/recall, cross-model-agreement null result, repair
effectiveness (can targeted feedback break systematic errors at temp 0?).
"""
import fcntl
import json
import re
import time
from pathlib import Path

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .tool_aware_v1 import decode

GF2 = core.ROOT / 'static_dag_v0/graph_forest_v2'
SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
V1 = core.ROOT / 'static_dag_v0/graph_forest_v1'
POOL = ['medium', 'large', 'coder']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0

GUIDE = {
    'exec': 'The previous expression failed to parse or execute; fix syntax and fact references.',
    'ref_complete': 'The previous expression must reference ALL provided facts (v0..v{k}).',
    'percent': 'The percentage scaling is inconsistent: whether the expression multiplies by 100 '
               'must match whether the question asks for a percentage; correct the scaling.',
    'magnitude': 'The result magnitude is inconsistent with the question type (sum vs average): '
                 'a sum result must be at least the largest fact, an average must lie between '
                 'the smallest and largest facts; remove spurious divisions or scalings.',
    'rel_div': 'A relative/ratio quantity requires a division in the expression.',
    'generic': 'Re-derive the expression step by step, checking whether each fact enters as a sum, '
               'difference, or ratio; verify operand order; then return ONLY the JSON.',
}


def feedback(flags, n_facts):
    if not flags:
        return GUIDE['generic']
    msgs = [GUIDE[f].format(k=n_facts) for f in flags]
    return ' '.join(msgs[:2])


def repair_prompt(question, facts, expr, flags):
    return ('You previously answered with the JSON expression {"expression": "%s"} for the question below. '
            'Static validation found problems: %s '
            'Return ONLY corrected JSON {"expression":"..."} referencing fact values as v0,v1,... in their '
            'listed order; allowed operators + - * / and parentheses; only numeric constants 0,1,100.\n'
            'QUESTION: %s\nFACTS: %s' % (expr, feedback(flags, len(facts['facts'])), question,
                                         json.dumps(facts)))


def run():
    gpu = GF2 / 'gpu_3x2'
    gpu.mkdir(parents=True, exist_ok=True)
    wv = json.loads((GF2 / 'WRITE_VALIDATION.json').read_text())
    reuse = json.loads((GF2 / 'REUSE_ARM.json').read_text())
    rr = {r['task_uid']: r for r in reuse['rows']}
    wrows = {r['task_uid']: r for r in wv['rows']}
    nodes = json.loads((SRC / 'NODES.json').read_text())
    tasks = json.loads((SRC / 'TASKS.json').read_text())
    tmap = {t['uid']: t for t in tasks}
    import numpy as np
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}

    def top_model(n):  # verbatim from graph_forest_v1
        types = [1.0 if n['node_type'] == t else 0.0
                 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
        x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
        u = x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'] - \
            ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
        return int(np.argmax(u))

    # repair targets: V1D = deployable-flagged; V1O = all known-wrong (oracle set)
    targets = {}
    for uid, w in wrows.items():
        if w['flagged']:
            targets.setdefault('V1D', []).append((uid, w['flagged']))
        if not w['round1_correct']:
            targets.setdefault('V1O', []).append((uid, []))

    engine.OUT = gpu
    cache = {}
    path = gpu / 'RESPONSES.jsonl'
    if path.exists():
        for l in path.read_text().splitlines():
            r = json.loads(l)
            cache[r['key']] = r
    calls = []
    repairs, arm_c = {}, {}

    def call(key, model, prompt):
        if key in cache:
            return cache[key]['response']
        with (gpu / 'REQUESTS.jsonl').open('a') as f:
            f.write(json.dumps(dict(key=key, model=model,
                                    prompt_sha256=__import__('hashlib').sha256(prompt.encode()).hexdigest(),
                                    unix_time=time.time())) + '\n')
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp)
        with path.open('a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        cache[key] = rec
        calls.append(key)
        return resp

    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current, proc, log = None, None, None
        try:
            def ensure(model):
                nonlocal current, proc, log
                if model != current:
                    if proc is not None:
                        engine.stop_model(proc, log)
                    proc, log, _ = engine.start_model(model)
                    current = model

            def batched(jobs):
                """jobs: list of (model, key, prompt); executed grouped by model."""
                out = {}
                for model in sorted({m for m, _, _ in jobs}):
                    ensure(model)
                    for m, key, prompt in jobs:
                        if m == model:
                            out[key] = call(key, model, prompt)
                return out

            # ---- phase 1: write-time repair retries (V1D and V1O sets) ----
            jobs = []
            for arm in ['V1D', 'V1O']:
                for uid, flags in targets.get(arm, []):
                    w = wrows[uid]
                    jobs.append((w['model'], f'repair:{arm}:{uid}',
                                 repair_prompt(w['question'], _facts(uid, nodes),
                                               w['stored_expr'], flags)))
            reps = batched(jobs)
            repairs = {}
            for arm in ['V1D', 'V1O']:
                for uid, flags in targets.get(arm, []):
                    w = wrows[uid]
                    resp = reps[f'repair:{arm}:{uid}']
                    try:
                        new_expr = decode(resp['answer'])['expression']
                        val = exec_calc(new_expr, _facts(uid, nodes))
                        ok_exec = True
                    except Exception:
                        new_expr, val, ok_exec = None, None, False
                    repairs[f'{arm}:{uid}'] = dict(model=w['model'], old_expr=w['stored_expr'],
                                                   new_expr=new_expr, value=val, exec=ok_exec,
                                                   changed=new_expr != w['stored_expr'],
                                                   flags=flags,
                                                   tokens=float(resp.get('usage', {}).get('total_tokens', 0)))
                    print(f'repair {arm} {uid[:8]} exec={ok_exec} '
                          f'{w["stored_expr"][:26]} -> {str(new_expr)[:26]}', flush=True)

            # ---- phase 2: arm C full rerun (forest-ignoring), batched e -> r -> v ----
            follow = {uid: tmap[uid]['question'] +
                      ' (Assume the FIRST listed fact value is 10 percent higher than reported.)'
                      for uid in rr}
            exts = batched([(rr[uid]['model'], f'c_e:{uid}',
                             v.eprompt(dict(question=follow[uid], context=tmap[uid]['context'])))
                            for uid in rr])
            cfacts = {}
            for uid in rr:
                try:
                    cfacts[uid] = v.parse_facts(exts[f'c_e:{uid}']['answer'])
                except Exception:
                    cfacts[uid] = {'facts': []}
            rs = batched([(rr[uid]['model'], f'c_r:{uid}',
                           v.sprompt(dict(question=follow[uid]), cfacts[uid])) for uid in rr])
            arm_c = {}
            vals = {}
            for uid in rr:
                try:
                    expr = decode(rs[f'c_r:{uid}']['answer'])['expression']
                    vals[uid] = (expr, exec_calc(expr, cfacts[uid]))
                except Exception:
                    vals[uid] = (None, None)
            vs = batched([(rr[uid]['model'], f'c_v:{uid}',
                           'Answer STRICTLY with JSON only, no prose: {"accept":true} or {"accept":false}. '
                           f'Does the value {vals[uid][1]} correctly answer the question '
                           f'"{follow[uid][:160]}" given these facts?') for uid in rr])
            for uid in rr:
                e, r_, vv = exts[f'c_e:{uid}'], rs[f'c_r:{uid}'], vs[f'c_v:{uid}']
                tok = sum(float(x.get('usage', {}).get('total_tokens', 0)) for x in (e, r_, vv))
                lat = sum(float(x.get('latency_s', 0)) for x in (e, r_, vv))
                exp = _expected(uid)
                arm_c[uid] = dict(expr=vals[uid][0], value=vals[uid][1],
                                  exec=vals[uid][1] is not None,
                                  correct=vals[uid][1] is not None and _close(vals[uid][1], exp),
                                  tokens=tok, latency=lat)
                print(f'C {uid[:8]} {"ok" if arm_c[uid]["correct"] else "wrong"} '
                      f'val={vals[uid][1]} exp={round(exp, 4)}', flush=True)
            core.write(gpu / 'RAW.json', dict(repairs=repairs, arm_c=arm_c, new_calls=calls))
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    print(json.dumps(dict(new_calls=len(calls), repairs=len(repairs), arm_c=len(arm_c))))


def _facts(uid, nodes):
    node = next(n for n in nodes if n['node_id'] == f'{uid}:rs')
    return node['gold_facts']


def _close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def _expected(uid):
    d = json.loads((GF2 / 'DIAGNOSTIC.json').read_text())
    return next(r['expected_new'] for r in d['rows'] if r['task_uid'] == uid)


if __name__ == '__main__':
    run()
