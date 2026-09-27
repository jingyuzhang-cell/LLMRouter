"""P0-1c: decompose the frozen200 selective-oracle headroom (zero calls).

Splits the Single-vs-Dynamic oracle gap into:
  (1) fault-driven recovery — help concentrated on randomly-injected tasks,
      inherently unpredictable from any pre-execution feature;
  (2) task-intrinsic help/harm — the clean-panel (no faults) D-S contrast,
      where Dynamic is NET harmful (35 harm vs 8 help).
Also computes the clairvoyant fault-aware gate (intervene iff injected) as the
runtime-observability ceiling.
"""
import json
from pathlib import Path

import numpy as np

F200 = Path('/root/r3_own_pool/static_dag_v0/frozen200')
OUT = F200.parent / 'frozen200_selective_gate'


def run():
    res = json.loads((F200 / 'FROZEN200_RESULTS.json').read_text())['results']
    pol = json.loads((F200 / 'FROZEN200_POLICY.json').read_text())
    uids = [t['uid'] for t in pol['tasks']]
    S_c = np.array([res['clean|single'][u]['ok'] for u in uids], float)
    D_c = np.array([res['clean|dynamic'][u]['ok'] for u in uids], float)
    U_c = D_c - S_c
    rows = [(res[f'f30_s{s}|single'][u], res[f'f30_s{s}|dynamic'][u])
            for s in ['20260923', '20260924', '20260925'] for u in uids]
    S_f = np.array([r[0]['ok'] for r in rows], float)
    D_f = np.array([r[1]['ok'] for r in rows], float)
    inj = np.array([bool(r[0].get('injected', False)) for r in rows])
    U_f = D_f - S_f
    clairvoyant = float(np.where(inj, D_f, S_f).mean())
    out = dict(
        clean_panel=dict(single=float(S_c.mean()), dynamic=float(D_c.mean()),
                         help=int((U_c > 0).sum()), harm=int((U_c < 0).sum()),
                         neutral=int((U_c == 0).sum()),
                         oracle=float(np.maximum(S_c, D_c).mean()),
                         note='Dynamic is NET harmful without faults: intervention on '
                              'healthy tasks breaks 35 to help 8'),
        fault_panel=dict(n=len(rows), injected=int(inj.sum()),
                         help_total=int((U_f > 0).sum()),
                         help_on_injected=int(((U_f > 0) & inj).sum()),
                         help_on_noninjected=int(((U_f > 0) & ~inj).sum()),
                         harm_total=int((U_f < 0).sum()),
                         harm_on_injected=int(((U_f < 0) & inj).sum()),
                         harm_on_noninjected=int(((U_f < 0) & ~inj).sum()),
                         single_on_injected=f'{int(S_f[inj].sum())}/{int(inj.sum())}',
                         dynamic_on_injected=f'{int(D_f[inj].sum())}/{int(inj.sum())}',
                         noninjected=dict(single=float(S_f[~inj].mean()),
                                          dynamic=float(D_f[~inj].mean()),
                                          oracle=float(np.maximum(S_f, D_f)[~inj].mean())),
                         injected_subset=dict(single=float(S_f[inj].mean()),
                                              dynamic=float(D_f[inj].mean()))),
        gates=dict(always_single=float(S_f.mean()), always_dynamic=float(D_f.mean()),
                   oracle_selective=float(np.maximum(S_f, D_f).mean()),
                   clairvoyant_fault_aware=clairvoyant,
                   never_on_healthy_max=clairvoyant,
                   note='Even PERFECT runtime fault detection reaches only '
                        f'{clairvoyant:.4f}; the residual to oracle '
                        f'({float(np.maximum(S_f, D_f).mean()):.4f}) requires predicting '
                        'task-intrinsic help, which is 14 samples against 67 intrinsic harm'),
        conclusion='80% of help (57/71) sits on randomly-injected tasks -> unpredictable '
                   'ex ante by ANY pre-execution feature; on healthy tasks harm:help = '
                   '67:14. The learnable signal must be RUNTIME state (deployable failure '
                   'signals), not task features — directing the method to trust '
                   'estimation / state observability (M1/M2), not a priori gating.')
    (OUT / 'DECOMPOSITION.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    run()
