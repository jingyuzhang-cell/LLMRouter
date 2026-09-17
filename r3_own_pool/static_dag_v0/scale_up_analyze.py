"""Scale-up analysis: 300-task decomposition utility + decompose triggers."""
import json
import re

import numpy as np

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .tatqa_benchmark_build import literals

ROOT = __import__('pathlib').Path('/root/r3_own_pool')
ROWS = {json.loads(l)['key']: json.loads(l) for l in (ROOT / 'static_dag_v0/scale_up/RESPONSES.jsonl').open()}
TQ_NEW = json.loads((ROOT / 'static_dag_v0/scale_up/TQ_TASKS.json').read_text())
TQ_OLD = json.loads((ROOT / 'static_dag_v0/tatqa_benchmark/TASKS.json').read_text())
MH = json.loads((ROOT / 'static_dag_v0/fresh_static_confirmation/TASKS.json').read_text())[:100]
MH_NODES = json.loads((ROOT / 'static_dag_v0/fresh_static_confirmation/NODES.json').read_text())
MT = dict(np.load(ROOT / 'static_dag_v0/fresh_static_confirmation/SCORED_MATRIX_EXEC.npz', allow_pickle=False))
LIVE = {json.loads(l)['task_uid']: json.loads(l) for l in (ROOT / 'static_dag_v0/live_e2e/TRACES.jsonl').open()}
TQ_OLD_RSN = {}
for _r in map(json.loads, (ROOT / 'static_dag_v0/tatqa_benchmark/medium_RESPONSES.jsonl').open()):
    for _nid in _r['node_ids']:
        TQ_OLD_RSN[_nid] = _r
NODE_IDX = {n['node_id']: i for i, n in enumerate(MH_NODES)}


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def extract_value(text):
    m = re.findall(r'Answer:\s*(-?[\d,]+(?:\.\d+)?)', text or '') or \
        re.findall(r'(-?[\d,]+(?:\.\d+)?)\s*$', (text or '').strip())
    if not m:
        return None
    try:
        return float(m[-1].replace(',', ''))
    except ValueError:
        return None


def gold_facts(t):
    vals = sorted({l for l in literals(t['derivation']) if l not in (0., 1., 100.)},
                  key=lambda z: -len(str(z)))
    return dict(facts=[dict(value=x, evidence='gold') for x in vals])


def chain_ok(t, rsn_r, ext_r=None):
    try:
        expr = v.decode(rsn_r['answer'])['expression']
        facts = None
        if ext_r is not None:
            try:
                facts = v.parse_facts(ext_r['answer'])
            except Exception:
                facts = None
        if not facts:
            facts = gold_facts(t)
        return bool(close(exec_calc(expr, facts), t['answer']))
    except Exception:
        return False


def mono_ok(t, r):
    if r is None or r['status'] != 'delivered':
        return None
    return bool(close(extract_value(r['answer']), t['answer']))


def main():
    tq_mono, tq_chain, tq_pair = [], [], []
    for t in TQ_OLD:
        rs = TQ_OLD_RSN.get(f'{t["uid"]}:rs')
        c = chain_ok(t, rs) if rs and rs['status'] == 'delivered' else False
        tq_chain.append(c)
    for t in TQ_NEW:
        m = mono_ok(t, ROWS.get(f'tq:{t["uid"]}:mono'))
        c = chain_ok(t, ROWS.get(f'tq:{t["uid"]}:rsn'), ROWS.get(f'tq:{t["uid"]}:ext'))
        if m is not None:
            tq_mono.append(m)
            tq_pair.append((m, c))
        tq_chain.append(c)

    mh_mono, mh_chain, mh_pair = [], [], []
    for i, t in enumerate(MH):
        m = mono_ok(t, ROWS.get(f'mh:{t["uid"]}:mono')) if i >= 50 else None
        if i < 50 and t['uid'] in LIVE:
            c = LIVE[t['uid']]['arms']['Static']['task_success']
        else:
            c = bool(MT['Q'][NODE_IDX[f"{t['uid']}:rs"], 0] > 0)
        if m is not None:
            mh_mono.append(m)
            mh_pair.append((m, c))
        mh_chain.append(c)

    def boot(vals, seed=20260916):
        vals = np.array(vals)
        n = len(vals)
        rng = np.random.default_rng(seed)
        means = [rng.choice(vals, n).mean() for _ in range(10000)]
        return [round(float(np.percentile(means, 2.5)), 3), round(float(np.percentile(means, 97.5)), 3)]

    print('=== 300-task decomposition utility ===')
    print(f"{'domain':12s} {'mono n':>7s} {'mono':>6s} {'chain n':>8s} {'chain':>6s}  paired diff [CI]")
    result = {}
    for dom, mo, ch, pr in [('TAT-QA', tq_mono, tq_chain, tq_pair),
                            ('MultiHiertt', mh_mono, mh_chain, mh_pair),
                            ('POOLED', tq_mono + mh_mono, tq_chain + mh_chain, tq_pair + mh_pair)]:
        d = np.array([c - m for m, c in pr])
        ci = boot(d) if len(d) else None
        cistr = f'{d.mean():+.3f} [{ci[0]:+.3f},{ci[1]:+.3f}]' if ci else 'n/a'
        print(f'{dom:12s} {len(mo):>7d} {np.mean(mo):>6.3f} {len(ch):>8d} {np.mean(ch):>6.3f}  {cistr}')
        result[dom] = dict(mono_n=len(mo), mono=float(np.mean(mo)),
                           chain_n=len(ch), chain=float(np.mean(ch)),
                           paired_diff=float(d.mean()) if len(d) else None, ci=ci)
    json.dump(result, open(ROOT / 'static_dag_v0/scale_up/DECOMP_UTILITY.json', 'w'), indent=1)
    print('written DECOMP_UTILITY.json')


if __name__ == '__main__':
    main()
