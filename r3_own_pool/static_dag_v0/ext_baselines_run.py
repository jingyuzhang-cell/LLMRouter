"""External baselines runner (addendum to frozen panels; protocol c4ac148/2de6fab).

RouteLLM-style learned query router: logistic regression on GTE question
embeddings, trained on the 900-task finance profiling corpus with per-task
propagated outcomes recomputed by the frozen scorer (replay-level).
FrugalGPT-style cascade: medium first, escalate to large on deployable
confidence failure. Both reuse existing mono cells (finance medium mono
collected here, 200 calls). Self-Refine-style iterative refinement: critique
+ revise (finance, large) and test-failure-driven revision (code, large),
bounded. No gold at runtime; one-shot.
"""
import argparse
import fcntl
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

ROOT = core.ROOT / 'static_dag_v0'
P3 = ROOT / 'p3_xdomain'
OUT = ROOT / 'external_baselines'
TQB = ROOT / 'tatqa_benchmark'
SU = ROOT / 'scale_up'
PAIR = ROOT / 'decomposition_benchmark' / 'paired_run'
MBPP_RUN = P3 / 'mbpp_run'
CAP = ROOT / 'capability_profiling'
GTE = '/root/autodl-tmp/models/gte-Qwen2-7B-instruct-fp16'

MONO = ('Answer the financial question using the report. Think as needed, then give ONLY the final numeric '
        'answer on the last line in the format: Answer: <number>\nQUESTION: {q}\nREPORT:\n{ctx}')
CRITIQUE_P = ('You are checking a draft answer to a financial question. List the errors in the draft, then '
              'state the corrected final answer on the last line inside \\boxed{{...}}. '
              'QUESTION: {q}\nDRAFT ANSWER: {draft}')
REVISE_P = ('Revise the answer to the financial question using the critique. Give ONLY the corrected final '
            'answer on the last line inside \\boxed{{...}}. '
            'QUESTION: {q}\nDRAFT ANSWER: {draft}\nCRITIQUE: {critique}')
CODE_REVISE_P = ('The submitted code failed. Fix it. Write only the python code (function + any imports). '
                 'Do not explain.\nTASK: {q}\nTESTS:\n{tests}\nSUBMITTED CODE:\n{code}\nFAILURE REPORT:\n{err}')


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def extract_value(text):
    m = re.findall(r'Answer:\s*(-?[\d,]+(?:\.\d+)?)', text or '') or \
        re.findall(r'(-?[\d,]+(?:\.\d+)?)\s*$', (text or '').strip())
    if not m:
        return None
    try:
        return float(m[-1].replace(',', ''))
    except ValueError:
        return None


def extract_boxed(text):
    boxes = re.findall(r'\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}', text or '')
    if boxes:
        return boxes[-1].strip()
    lines = [l.strip() for l in (text or '').splitlines() if l.strip()]
    return lines[-1] if lines else ''


def extract_code(text):
    t = (text or '').strip()
    m = re.search(r'```(?:python)?\s*\n(.*?)```', t, re.S)
    return (m.group(1) if m else t).strip()


def run_code_tests(code, tests, timeout=20):
    prog = code + '\n\n' + '\n'.join(tests) + '\n'
    try:
        p = subprocess.run([sys.executable, '-I', '-c', prog], capture_output=True,
                           timeout=timeout, cwd='/tmp', env={'PATH': '/usr/bin:/bin', 'HOME': '/tmp'})
        if p.returncode == 0:
            return True, ''
        err = (p.stderr.decode(errors='ignore') or p.stdout.decode(errors='ignore'))[-1200:]
        return False, err.strip() or 'non-zero exit'
    except subprocess.TimeoutExpired:
        return False, 'timeout'
    except Exception as e:
        return False, type(e).__name__ + ': ' + str(e)


def tok(r):
    if not r:
        return 0
    return (r.get('usage') or {}).get('total_tokens', 0)


def load_panels():
    tq_freeze = json.loads((ROOT / 'decomposition_benchmark' / 'decomposition_final_tatqa_200.json').read_text())
    tq = {t['uid']: t for t in json.loads((TQB / 'TASKS.json').read_text())}
    tq.update({t['uid']: t for t in json.loads((SU / 'TQ_TASKS.json').read_text())})
    fin = []
    for e in tq_freeze:
        t = tq[e['task_id']]
        fin.append(dict(task_id=t['uid'], question=t['question'], context=t['context'], answer=t['answer']))
    code_detail = json.loads((P3 / 'P3_CODE_TASKS_100_DETAIL.json').read_text())
    cod = [dict(task_id=t['task_id'], question=t['query'], tests=t['tests']) for t in code_detail]
    return fin, cod


def route_llm_style(fin, cod):
    prof_tasks = {t['uid']: t for t in json.loads((CAP / 'PROFILE_POLICY.json').read_text())['tasks']}
    resp = {json.loads(l)['key']: json.loads(l) for l in (CAP / 'RESPONSES.jsonl').open()}
    labels, qs = [], []
    for uid, t in prof_tasks.items():
        outs = {}
        for m in ('medium', 'large'):
            ext = resp.get(f'EXT:{m}:{uid}')
            rsn = resp.get(f'RSN:{m}:{uid}')
            q = 0
            try:
                facts = v.parse_facts(ext['response']['answer'])
                expr = v.decode(rsn['response']['answer'])['expression']
                q = int(close(exec_calc(expr, facts), t['answer']))
            except Exception:
                q = 0
            outs[m] = q
        if outs['large'] == outs['medium']:
            continue
        labels.append(int(outs['large'] > outs['medium']))
        qs.append(t['question'].strip().lower())
    emb = np.load(CAP / 'PROFILE_EMB.npz')
    qmap = {q.strip().lower(): i for i, q in enumerate(emb['questions'])}
    idx = [i for i, q in enumerate(qs) if q in qmap]
    X = np.array([emb['emb'][qmap[qs[i]]].astype('float32') for i in idx])
    y = np.array([labels[i] for i in idx])
    from sklearn.linear_model import LogisticRegression
    clf = LogisticRegression(C=1.0, max_iter=2000)
    clf.fit(X, y)
    from sentence_transformers import SentenceTransformer
    st = SentenceTransformer(GTE, device='cpu')
    routes = {}
    fq = [t['question'] for t in fin]
    cq = [t['question'] for t in cod]
    Xf = np.array(st.encode(fq, normalize_embeddings=True, batch_size=8, show_progress_bar=False), dtype='float32')
    Xc = np.array(st.encode(cq, normalize_embeddings=True, batch_size=8, show_progress_bar=False), dtype='float32')
    pf = clf.predict(Xf)
    pc = clf.predict(Xc)
    for i, t in enumerate(fin):
        routes[t['task_id']] = 'large' if pf[i] == 1 else 'medium'
    for i, t in enumerate(cod):
        routes[t['task_id']] = 'large' if pc[i] == 1 else 'medium'
    return routes, dict(n_train=len(y), pos_rate=float(np.mean(y)),
                        fin_large_share=float(np.mean(pf == 1)), cod_large_share=float(np.mean(pc == 1)))


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    engine.OUT = OUT
    fin, cod = load_panels()
    resp_path = OUT / 'RESPONSES.jsonl'
    cache = {}
    if resp_path.exists():
        for line in resp_path.open():
            r = json.loads(line)
            cache[r['key']] = r

    pair_rows = {json.loads(l)['key']: json.loads(l) for l in (PAIR / 'RESPONSES.jsonl').open()}
    mbpp_rows = {json.loads(l)['key']: json.loads(l) for l in (MBPP_RUN / 'RESPONSES.jsonl').open()}
    pair_pt = {p['task_id']: p for p in [json.loads(l) for l in (PAIR / 'per_task.jsonl').open()] if p['dataset'] == 'TAT-QA'}
    mbpp_res = {r['task_id']: r for r in json.loads((MBPP_RUN / 'RESULTS.json').read_text())['rows']}

    def mbpp_cell(tid, model):
        for k, r in mbpp_rows.items():
            if k.startswith(f'{tid}:mono:{model}:'):
                return r
        return None

    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        cur = {'m': None}
        try:
            def ensure(model):
                nonlocal proc, log
                if model != cur['m']:
                    if proc is not None:
                        engine.stop_model(proc, log)
                        proc = log = None
                    proc, log, _ = engine.start_model(model)
                    cur['m'] = model

            def call(model, key, prompt, meta):
                if key in cache:
                    return cache[key]
                ensure(model)
                r = engine.call_model(model, prompt)
                row = dict(key=key, model=model, prompt=prompt, **meta, **r)
                with resp_path.open('a') as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
                    f.flush()
                cache[key] = row
                return row

            fin_med = {}
            for t in fin:
                fin_med[t['task_id']] = call(
                    'medium', f'base:tq:{t["task_id"]}:mono',
                    MONO.format(q=t['question'], ctx=t['context'][:14000]),
                    dict(task_id=t['task_id'], node='mono'))
            print(json.dumps(dict(phase='fin_medium_mono_done')))

            fin_sr = {}
            for t in fin:
                draft = pair_rows[f'tq:{t["task_id"]}:mono']['answer']
                cr = call('large', f'base:tq:{t["task_id"]}:critique',
                          CRITIQUE_P.format(q=t['question'], draft=draft),
                          dict(task_id=t['task_id'], node='critique'))
                rv = call('large', f'base:tq:{t["task_id"]}:revise',
                          REVISE_P.format(q=t['question'], draft=draft, critique=cr['answer']),
                          dict(task_id=t['task_id'], node='revise'))
                fin_sr[t['task_id']] = rv
            print(json.dumps(dict(phase='fin_selfrefine_done')))

            cod_sr = {}
            for t in cod:
                base = mbpp_cell(t['task_id'], 'large')
                code = extract_code(base['answer'])
                ok, err = run_code_tests(code, t['tests'])
                n_extra = 0
                last = base
                while not ok and n_extra < 2:
                    last = call('large', f'base:mbpp:{t["task_id"]}:revise{n_extra}',
                                CODE_REVISE_P.format(q=t['question'], tests='\n'.join(t['tests']),
                                                     code=code, err=err),
                                dict(task_id=t['task_id'], node='revise'))
                    n_extra += 1
                    code = extract_code(last['answer'])
                    ok, err = run_code_tests(code, t['tests'])
                cod_sr[t['task_id']] = dict(ok=ok, n_extra=n_extra, last=last)
            print(json.dumps(dict(phase='cod_selfrefine_done')))
        finally:
            if proc is not None:
                engine.stop_model(proc, log)

    routes, train_info = route_llm_style(fin, cod)

    # ---------- finance evaluation ----------
    fin_rows = []
    for t in fin:
        tid = t['task_id']
        gold = t['answer']
        rl = pair_rows[f'tq:{tid}:mono']
        ql = bool(pair_pt[tid]['mono'])
        tl = tok(rl)
        rm = fin_med[tid]
        val_m = extract_value(rm.get('answer'))
        qm = rm.get('status') == 'delivered' and close(val_m, gold)
        tm = tok(rm)
        # RouteLLM-style
        qr = ql if routes[tid] == 'large' else qm
        tr = tl if routes[tid] == 'large' else tm
        # FrugalGPT-style cascade: medium first, escalate iff deployable check fails
        conf_ok = rm.get('status') == 'delivered' and val_m is not None
        qc = qm if conf_ok else ql
        tc = tm if conf_ok else tm + tl
        # Self-Refine-style: critique + revise, frozen numeric scorer
        sr_ans = extract_boxed(fin_sr[tid].get('answer'))
        sr_val = extract_value(sr_ans)
        qs = fin_sr[tid].get('status') == 'delivered' and close(sr_val, gold)
        ts = tl + tok(cache[f'base:tq:{tid}:critique']) + tok(fin_sr[tid])
        budget = max(200, 1.2 * pair_pt[tid]['tokens']['dag_LM'])
        fin_rows.append(dict(task_id=tid, always_large=ql, route_llm=qr, cascade=qc, selfrefine=qs,
                             dyn_ref=pair_pt[tid]['dagLM'],
                             tok_large=tl, tok_route=tr, tok_cascade=tc, tok_selfrefine=ts, budget=budget))

    # ---------- code evaluation ----------
    cod_rows = []
    for t in cod:
        tid = t['task_id']
        base = mbpp_cell(tid, 'large')
        med = mbpp_cell(tid, 'medium')
        ql = mbpp_res[tid]['arms']['always_large']
        qm = mbpp_res[tid]['arms']['always_medium']
        tl = tok(base)
        tm = tok(med)
        qr = ql if routes[tid] == 'large' else qm
        tr = tl if routes[tid] == 'large' else tm
        okm, _ = run_code_tests(extract_code(med['answer']), t['tests'])
        qc = okm or ql
        tc = tm + (tl if not okm else 0)
        qs = cod_sr[tid]['ok']
        ts = tl + sum(tok(cache.get(f'base:mbpp:{tid}:revise{i}')) for i in range(cod_sr[tid]['n_extra']))
        budget = mbpp_res[tid]['budget']
        cod_rows.append(dict(task_id=tid, always_large=ql, route_llm=qr, cascade=qc, selfrefine=qs,
                             dyn_ref=mbpp_res[tid]['arms']['dynamic_real'],
                             tok_large=tl, tok_route=tr, tok_cascade=tc, tok_selfrefine=ts, budget=budget))

    core.write(OUT / 'EXTERNAL_BASELINES_RESULTS.json',
               dict(created_unix=time.time(), train_info=train_info,
                    finance=fin_rows, code=cod_rows, n_fin=len(fin_rows), n_cod=len(cod_rows)))
    core.write(OUT / 'ALL_DONE', dict(unix_time=time.time()))
    print(json.dumps(dict(fin=len(fin_rows), cod=len(cod_rows), train=train_info), indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
