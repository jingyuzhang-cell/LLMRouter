"""Pre-registered analysis of the paired decomposition benchmark (zero new calls)."""
import json
import math
import random
import time

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .confirmation_200 import OUT as CONF1
from .cross_model_matrix import OUT as CM
from .paired_decomposition import OUT, close, extract_value, n_ops, stratum

SEED = 20260918
B = 10000


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n * 2)


def ci(diffs, seed=SEED):
    rng = random.Random(seed)
    n = len(diffs)
    out = []
    for _ in range(B):
        out.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    out.sort()
    return [round(out[int(0.025 * B)], 4), round(out[int(0.975 * B) - 1], 4)]


def run():
    pol = json.loads((CONF1 / 'CONF_POLICY.json').read_text())
    tasks = {t['uid']: t for t in pol['tasks']}
    conf_resp = {}
    for l in (CONF1 / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); conf_resp[r['key']] = r
    cm_resp = {}
    for l in (CM / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); cm_resp[r['key']] = r
    mono = {}
    for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); mono[r['key']] = r

    rows = []
    for uid, t in tasks.items():
        gold = t['answer']
        m = mono.get(f'MONO:large:{uid}')
        q_mono = int(close(extract_value(m['response']['answer']), gold)) if m else None
        q_dag = {}
        for tag, rsn_m in (('LL', 'large'), ('LM', 'medium')):
            ext = conf_resp.get(f'EXT:large:{uid}')
            rsn = cm_resp.get(f'X:large:{rsn_m}:{uid}')
            if ext is None or rsn is None:
                q_dag[tag] = None; continue
            try:
                facts = v.parse_facts(ext['response']['answer'])
            except Exception:
                facts = {'facts': []}
            try:
                val = exec_calc(v.decode(rsn['response']['answer'])['expression'], facts)
                q_dag[tag] = int(close(val, gold))
            except Exception:
                q_dag[tag] = 0
        k = n_ops(t.get('program', ''))
        rows.append(dict(uid=uid, mono=q_mono, LL=q_dag['LL'], LM=q_dag['LM'], stratum=stratum(k), n_ops=k))
    rows = [r for r in rows if r['mono'] is not None and r['LL'] is not None and r['LM'] is not None]
    n = len(rows)

    def q(key):
        return round(sum(r[key] for r in rows) / n, 4)

    def contrast(a, b):
        d = [r[a] - r[b] for r in rows]
        bb = sum(1 for x in d if x == 1); cc = sum(1 for x in d if x == -1)
        return dict(dQ=round(sum(d) / n, 4), ci=ci(d), mcnemar=dict(b=bb, c=cc, p_exact=round(mcnemar_exact(bb, cc), 5)))

    strata = {}
    for s in ('2ops', '3-4ops', '5+ops'):
        sub = [r for r in rows if r['stratum'] == s]
        if not sub: continue
        strata[s] = dict(n=len(sub),
                         mono=round(sum(r['mono'] for r in sub) / len(sub), 4),
                         dag_LL=round(sum(r['LL'] for r in sub) / len(sub), 4),
                         dag_LM=round(sum(r['LM'] for r in sub) / len(sub), 4))
    rep = dict(generated_unix=time.time(), n=n,
               Q=dict(mono_L=q('mono'), dag_L_L=q('LL'), dag_L_M=q('LM')),
               C1_decomposition_value=contrast('LL', 'mono'),
               C2_heterogeneous_value=contrast('LM', 'LL'),
               strata=strata,
               protocol='extraction failure => task fail; no retry; no gold; strictly paired frozen panel')
    (OUT / 'PD_ANALYSIS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    run()
