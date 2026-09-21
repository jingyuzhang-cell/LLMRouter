"""One-shot confirmatory analysis for the 250-task Dynamic-v2 confirmation.

Reuses the frozen live analyzer (identical definitions) and adds the
pre-registered confirmatory readout: paired delta-Q bootstrap CI, McNemar
exact test, Help/Harm, tokens, latency, budget violations, and the three-case
interpretation rule fixed before the run:
  case 1: dQ 95% CI excludes 0 and > 0  -> confirmed small positive effect
  case 2: dQ > 0 but CI covers 0        -> directionally positive, not confirmed
  case 3: dQ <= 0                       -> no end-to-end quality benefit
No threshold or policy may be changed after this analysis regardless of outcome.
"""
import json
import math

from .recovery_matrix_v2_devset import BASE
from . import live_static_dynamic as L
from . import live_static_dynamic_analyze as A

OUT = BASE / 'dynamic_v2_confirm_250'


def mcnemar_exact(b, c):
    """Two-sided exact McNemar via binomial tail; b,c are discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n * 2
    return min(1.0, p)


def run():
    L.OUT = OUT
    A.OUT = OUT
    A.run()
    raw = json.loads((OUT / 'RAW_TAIL.json').read_text())
    rep = json.loads((OUT / 'LIVE_ANALYSIS.json').read_text())
    tasks = json.loads((OUT / 'LIVE_POLICY.json').read_text())['tasks']
    s_ok = {t['uid']: raw['static'][t['uid']]['ok'] for t in tasks}
    d_ok = {t['uid']: raw['dynamic'][t['uid']]['ok'] for t in tasks}
    b = sum(1 for u in s_ok if not s_ok[u] and d_ok[u])   # static wrong -> dynamic right
    c = sum(1 for u in s_ok if s_ok[u] and not d_ok[u])   # static right -> dynamic wrong
    dQ = rep['A_main']['paired_dQ']
    lo, hi = rep['A_main']['paired_dQ_ci']
    if lo > 0:
        case = 1
    elif dQ > 0:
        case = 2
    else:
        case = 3
    confirm = dict(
        one_shot=True,
        n=len(tasks),
        paired_dQ=dQ, paired_dQ_ci=[lo, hi],
        mcnemar=dict(b=b, c=c, p_exact=round(mcnemar_exact(b, c), 4)),
        help=rep['B_help_harm']['help'], harm=rep['B_help_harm']['harm'],
        static_C=rep['A_main']['static_C'], dynamic_C=rep['A_main']['dynamic_C'],
        budget_violation_rate=rep['C_dynamic_behavior']['budget_violation_rate'],
        preregistered_rule='case1 CI excludes 0 & >0; case2 dQ>0 & CI covers 0; case3 dQ<=0',
        case=case,
        verdict={1: 'confirmed small positive end-to-end effect',
                 2: 'directionally positive, NOT confirmed (CI covers 0)',
                 3: 'no end-to-end quality benefit'}[case])
    (OUT / 'CONFIRM_ANALYSIS.json').write_text(json.dumps(confirm, ensure_ascii=False, indent=2))
    print(json.dumps(confirm, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run()
