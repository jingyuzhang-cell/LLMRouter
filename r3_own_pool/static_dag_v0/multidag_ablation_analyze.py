"""Pre-registered analysis of the two control arms (zero model calls).

Q_static / Q_dynamic come from the frozen base panel analysis. New arms:
  SM (Static-Matched)  : static semantics + dynamic escalation targets.
  RD (Dynamic-RealDetector): dynamic rules + deployable-only detection.
Readout (pre-registered):
  attribution: Q_SM vs Q_dynamic (does the policy add value beyond targets?)
               Q_SM vs Q_static (how much is just escalation targets?)
  retention: (Q_RD - Q_static)/(Q_dynamic - Q_static) with task bootstrap CI.
"""
import json
import random
import time

from .multidag_dynamic import OUT
from .multidag_ablation import ABL

SEED = 20260918
B = 10000


def boot_ci(vals, seed=SEED):
    rng = random.Random(seed)
    n = len(vals)
    out = []
    for _ in range(B):
        out.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    out.sort()
    return [round(out[int(0.025 * B)], 4), round(out[int(0.975 * B) - 1], 4)]


def mcnemar_exact(b, c):
    import math
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n * 2)


def run():
    base = json.loads((OUT / 'CONFIRM_ANALYSIS.json').read_text())
    pol = json.loads((OUT / 'POLICY.json').read_text())
    raw = json.loads((ABL / 'RAW_TAIL.json').read_text())
    uids = [t['uid'] for t in pol['tasks']]
    base_raw = json.loads((OUT / 'RAW_TAIL.json').read_text())
    s_ok = [int(base_raw['static'][u]['ok']) for u in uids]
    d_ok = [int(base_raw['dynamic'][u]['ok']) for u in uids]
    sm_ok = [int(raw['sm'][u]['ok']) for u in uids]
    rd_ok = [int(raw['rd'][u]['ok']) for u in uids]
    n = len(uids)

    def q(x):
        return round(sum(x) / n, 4)

    ret = [(r - s) / (d - s) if d != s else None for r, s, d in zip(rd_ok, s_ok, d_ok)]
    # retention ratio is a ratio of means; bootstrap the ratio of paired differences
    rng = random.Random(SEED)
    num = [r - s for r, s in zip(rd_ok, s_ok)]
    den = [d - s for d, s in zip(d_ok, s_ok)]
    boots = []
    for _ in range(B):
        i = [rng.randrange(n) for _ in range(n)]
        dn = sum(num[k] for k in i); dd = sum(den[k] for k in i)
        if dd > 0:
            boots.append(dn / dd)
    boots.sort()
    ret_ci = [round(boots[int(0.025 * len(boots))], 4), round(boots[int(0.975 * len(boots)) - 1], 4)]
    costs = {arm: round(sum(raw_a[u]['used'] for u in uids) / n, 1) for arm, raw_a in
             (('sm', raw['sm']), ('rd', raw['rd']))}
    b1 = sum(1 for a, b_ in zip(sm_ok, d_ok) if a == 0 and b_ == 1)
    c1 = sum(1 for a, b_ in zip(sm_ok, d_ok) if a == 1 and b_ == 0)
    b2 = sum(1 for a, b_ in zip(rd_ok, d_ok) if a == 0 and b_ == 1)
    c2 = sum(1 for a, b_ in zip(rd_ok, d_ok) if a == 1 and b_ == 0)
    rep = dict(generated_unix=time.time(), n=n,
               Q_static=q(s_ok), Q_dynamic_ideal=q(d_ok), Q_static_matched=q(sm_ok), Q_dynamic_realdetector=q(rd_ok),
               attribution=dict(
                   targets_only_gain=dict(dQ=round(q(sm_ok) - q(s_ok), 4), ci=boot_ci([a - b_ for a, b_ in zip(sm_ok, s_ok)])),
                   policy_beyond_targets=dict(dQ=round(q(d_ok) - q(sm_ok), 4), ci=boot_ci([a - b_ for a, b_ in zip(d_ok, sm_ok)]),
                                              mcnemar=dict(b=b1, c=c1, p_exact=round(mcnemar_exact(b1, c1), 6)))),
               retention=dict(value=round(sum(num) / sum(den), 4) if sum(den) else None, ci=ret_ci,
                              rd_vs_dynamic_mcnemar=dict(b=b2, c=c2, p_exact=round(mcnemar_exact(b2, c2), 6))),
               costs=dict(sm=costs['sm'], rd=costs['rd'],
                          static=base['A_main']['static_C'], dynamic=base['A_main']['dynamic_C']),
               notes='RD arm ungated (the frozen dynamic arm fired zero budget skips, so gating is moot); e-node deployable detection equals ideal by definition (parse/empty)')
    (ABL / 'ABLATION_ANALYSIS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    run()
