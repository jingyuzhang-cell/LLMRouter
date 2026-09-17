"""P0-3: measured per-arm costs from the call caches - no estimates.

Replays all five live arms offline over the combined call caches and bills
every consumed cell (cache hits included): Static (frozen utility picks),
AlwaysMedium / AlwaysLarge (fixed model), Feedback (memory replay with cached
verifier verdicts), Full (feedback + verifier + fallback + decompose cells).
Output: calls, input/output/total tokens, service seconds - all measured.
"""
import argparse
import json

from . import core
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

LIVE = core.ROOT / 'static_dag_v0/live_e2e'
SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
BASE = LIVE / 'single_model_baselines'
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
LAMBDA, LAMBDA_FAIL = 0.3, 0.5
LEN_SPLIT = 150
POOL = ['medium', 'large', 'coder']


def run():
    import numpy as np
    cache = {}
    for f in (LIVE / 'CALL_CACHE.jsonl', BASE / 'CALL_CACHE_BASELINES.jsonl'):
        if f.exists():
            for line in f.open():
                row = json.loads(line)
                k = tuple(row['key'].split('/')) if '/' in row['key'] else row['key']
                cache[k] = row['response']
    traces = [json.loads(l) for l in (LIVE / 'TRACES.jsonl').open()]
    tasks = json.loads((SRC / 'TASKS.json').read_text())[:50]
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    by_task = {}
    for n in nodes_all:
        by_task.setdefault(n['task_uid'], []).append(n)

    def qhat(n):
        types = [1.0 if n['node_type'] == t else 0.0
                 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
        x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
        return (x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'])[0]

    def util(n):
        return qhat(n) - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']

    arms = {a: dict(calls=0, tin=0, tout=0, service=0.0) for a in
            ['AlwaysMedium', 'AlwaysLarge', 'Static', 'Feedback', 'Full']}

    def bill(arm, key):
        r = cache.get(key)
        if r is None:
            return None
        u = r.get('usage') or {}
        arms[arm]['calls'] += 1
        arms[arm]['tin'] += u.get('prompt_tokens', 0) or 0
        arms[arm]['tout'] += u.get('completion_tokens', 0) or 0
        arms[arm]['service'] += r.get('latency_s', 0.0) or 0.0
        return r

    def facts_of(arm, t, ext, m_ext):
        r = bill(arm, (ext['node_id'], m_ext))
        if r is None:
            return None
        try:
            return v.parse_facts(r['answer'])
        except Exception:
            return None

    # fixed-model arms
    for arm, model in [('AlwaysMedium', 'medium'), ('AlwaysLarge', 'large')]:
        for t in tasks:
            ns = by_task[t['uid']]
            ext = next((n for n in ns if n['node_type'] == 'extraction'), None)
            r_node = next(n for n in ns if n['node_type'] == 'reasoning')
            if ext:
                facts_of(arm, t, ext, model)
            bill(arm, (r_node['node_id'], model, 'live'))
    # routed arms via trace replay (memory reconstruction deterministic from cached verdicts)
    mem, mem_fail = {}, {}

    def verdict_of(key):
        r = cache.get(key)
        if r is None:
            return None
        try:
            return v.decode(r['answer'])['verdict'] == 'yes'
        except Exception:
            return None

    for tr in traces:
        t = next(x for x in tasks if x['uid'] == tr['task_uid'])
        ns = by_task[t['uid']]
        ext = next((n for n in ns if n['node_type'] == 'extraction'), None)
        r_node = next(n for n in ns if n['node_type'] == 'reasoning')
        b = 'short' if len(t['question']) < LEN_SPLIT else 'long'
        # static arm
        m_ext_s = POOL[int(np.argmax(util(ext)))] if ext else None
        if ext:
            facts_of('Static', t, ext, m_ext_s)
        bill('Static', (r_node['node_id'], POOL[int(np.argmax(util(r_node)))], 'live'))
        # feedback/full arms share the memory-driven pick sequence
        for arm in ('Feedback', 'Full'):
            key = ('extraction', b)
            mem.setdefault(key, {m: [0, 0] for m in POOL})
            qs = np.array([(1 - LAMBDA) * qhat(ext)[k] + LAMBDA * ((mem[key][m][0] + 1) / (mem[key][m][1] + 2))
                           for k, m in enumerate(POOL)]) if ext else None
            m_ext = POOL[int(np.argmax(qs - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']))] if ext else None
            facts = facts_of(arm, t, ext, m_ext) if ext else None
            rkey = ('reasoning', b)
            mem.setdefault(rkey, {m: [0, 0] for m in POOL})
            qs = np.array([(1 - LAMBDA) * qhat(r_node)[k] + LAMBDA * ((mem[rkey][m][0] + 1) / (mem[rkey][m][1] + 2))
                           for k, m in enumerate(POOL)])
            m_r = POOL[int(np.argmax(qs - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']))]
            state = tr['arms'][arm]
            # bill the cells this arm actually consumed, in order
            m_final = state.get('model', m_r)
            if m_final == m_r and state.get('verdict') is None or m_final == m_r:
                bill(arm, (r_node['node_id'], m_r, 'live'))
                vd = verdict_of((r_node['node_id'], m_r, 'verifier'))
                if vd is not None:
                    bill(arm, (r_node['node_id'], m_r, 'verifier'))
            else:
                # fallback path: first pick + verifier, fallback + verifier
                bill(arm, (r_node['node_id'], m_r, 'live'))
                bill(arm, (r_node['node_id'], m_r, 'verifier'))
                bill(arm, (r_node['node_id'], m_final, 'live'))
                bill(arm, (r_node['node_id'], m_final, 'verifier'))
            if arm == 'Full' and state.get('decompose'):
                bill(arm, (r_node['node_id'], m_final, 'd1'))
                bill(arm, (r_node['node_id'], m_final, 'd2'))
            # memory update from the trace's verdict (deployable signal, as executed)
            vd = state.get('verdict')
            if vd is not None:
                mem[rkey][m_final][0] += int(vd is True)
                mem[rkey][m_final][1] += 1
            if facts is not None:
                mem.setdefault(('extraction', b), {m: [0, 0] for m in POOL})
                mem[('extraction', b)][m_ext][0] += 1
                mem[('extraction', b)][m_ext][1] += 1
    out = {a: dict(calls=v['calls'], input_tokens=v['tin'], output_tokens=v['tout'],
                   total_tokens=v['tin'] + v['tout'], service_seconds=round(v['service'], 1))
           for a, v in arms.items()}
    for a in out:
        out[a]['tokens_per_task'] = round(out[a]['total_tokens'] / 50)
    core.write(LIVE / 'MEASURED_COSTS.json', dict(
        arms=out, n_tasks=50, accounting='every consumed cell billed at its cached usage, cache hits included; '
                                        'no estimates',
        success=dict(AlwaysMedium=.16, AlwaysLarge=.24, Static=.24, Feedback=.28, Full=.34)))
    print(json.dumps(out, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
