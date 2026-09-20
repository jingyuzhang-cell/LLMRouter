"""Analyze the 3x3 cross-model propagation matrix: E_i -> R_j quality for all 9 pairs.
Answers: does upstream extraction quality mask downstream reasoning complementarity?"""
import json

import numpy as np

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .recovery_matrix_v2_audit import close
from .cross_model_matrix import OUT as XM

def run():
    pol = json.loads((XM / 'CROSS_MODEL_POLICY.json').read_text())
    subset = set(pol['subset_uids'])
    tasks = {t['uid']: t for t in json.loads((CPROF / 'PROFILE_POLICY.json').read_text())['tasks']}
    dev_resp = {}
    for l in (CPROF / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); dev_resp[r['key']] = r
    xm_resp = {}
    for l in (XM / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); xm_resp[r['key']] = r
    # build 3x3 matrix
    matrix = {}  # (ext_m, rsn_m) -> list of Q values
    for uid in subset:
        t = tasks[uid]; gold = t['answer']
        for ext_m in POOL:
            ext = dev_resp.get(f'EXT:{ext_m}:{uid}')
            if ext is None: continue
            try: facts = v.parse_facts(ext['response']['answer'])
            except Exception: facts = {'facts': []}
            for rsn_m in POOL:
                if ext_m == rsn_m:
                    rsn = dev_resp.get(f'RSN:{rsn_m}:{uid}')
                else:
                    rsn = xm_resp.get(f'X:{ext_m}:{rsn_m}:{uid}')
                if rsn is None: continue
                try:
                    val = exec_calc(v.decode(rsn['response']['answer'])['expression'], facts)
                    q = int(close(val, gold))
                except Exception:
                    q = 0
                matrix.setdefault((ext_m, rsn_m), []).append(q)
    # report
    print("Cross-Model Propagation Matrix: Q(E_i -> R_j)")
    print(f"{'Extract\\\\Reason':>16} {'Medium':>8} {'Large':>8} {'Coder':>8}")
    for ext_m in POOL:
        row = f"{ext_m:>16}"
        for rsn_m in POOL:
            vals = matrix.get((ext_m, rsn_m), [])
            q = round(float(np.mean(vals)), 4) if vals else None
            row += f" {q:>8.3f}" if q is not None else f" {'N/A':>8}"
        print(row)
    print(f"\nN per cell: {len(matrix.get(('medium','medium'),[]))}")
    # key comparisons
    diag = {m: float(np.mean(matrix[(m, m)])) for m in POOL}
    # fixed extraction=large, vary reasoner
    ext_l = {r: float(np.mean(matrix[('large', r)])) for r in POOL}
    # fixed reasoner=medium, vary extraction
    rsn_m = {e: float(np.mean(matrix[(e, 'medium')])) for e in POOL}
    rep = dict(
        matrix={f'E_{e}->R_{r}': dict(Q=round(float(np.mean(v)), 4), n=len(v))
                for (e, r), v in matrix.items()},
        diagonal={f'E_{m}->R_{m}': round(q, 4) for m, q in diag.items()},
        fixed_extraction_large={f'R_{r}': round(q, 4) for r, q in ext_l.items()},
        fixed_reasoner_medium={f'E_{e}': round(q, 4) for e, q in rsn_m.items()},
        key_findings={})
    # does E_large->R_medium > E_medium->R_medium?
    if 'large' in ext_l and ext_l.get('medium', 0) > 0:
        rep['key_findings']['E_L_R_M_vs_E_M_R_M'] = dict(
            E_L_R_M=round(ext_l['medium'], 4), E_M_R_M=round(rsn_m['medium'], 4),
            gap_recovered=round(ext_l['medium'] - rsn_m['medium'], 4),
            interpretation='medium reasoning is better than its own extraction allows' if ext_l['medium'] > rsn_m['medium'] else 'medium extraction is not the bottleneck')
    # does E_large->R_medium > E_large->R_large?
    if 'medium' in ext_l and 'large' in ext_l:
        rep['key_findings']['E_L_R_M_vs_E_L_R_L'] = dict(
            E_L_R_M=round(ext_l['medium'], 4), E_L_R_L=round(ext_l['large'], 4),
            medium_advantage=round(ext_l['medium'] - ext_l['large'], 4),
            interpretation='medium reasoning complementarity re-emerges with good extraction' if ext_l['medium'] > ext_l['large'] else 'large remains best even with its own extraction')
    (XM / 'CROSS_MODEL_RESULTS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep['key_findings'], ensure_ascii=False, indent=2))
    print(json.dumps(dict(diagonal=rep['diagonal'],
                          fixed_ext_large=rep['fixed_extraction_large'],
                          fixed_rsn_medium=rep['fixed_reasoner_medium']),
                     ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
