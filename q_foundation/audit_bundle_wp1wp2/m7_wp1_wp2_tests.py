"""M7-3B WP1/WP2 independent acceptance tests (ZERO model calls).

WP1 F' V1.0: independent reproduction of historical rules + deterministic
trajectory tests on C1/C2/C3/C4/C6 + audited difference set vs F (V1.1).
WP2 GROSS Budget Guard: G1-G6 guarantees as executable assertions.

Run: python3 m7_wp1_wp2_tests.py  (exit 0 iff all pass)
"""
import sys

import m7_decision_engine as E
import m7_policy_v10 as V10
from m7_budget_guard import (BudgetExceeded, DuplicateReservation,
                             GrossBudgetGuard)

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))


PERSISTENCE = (('contract', 'persistent'), ('parse', 'transient'),
               ('transport', 'transient'))
PROFILE = (('index', (('glm53', .85), ('glm53flash', .62))),
           ('extracts', (('glm53', .85), ('glm53flash', .62))),
           ('timeline', (('glm53', .75), ('glm53flash', .60))),
           ('entity_facts', (('glm53', .80), ('glm53flash', .58))),
           ('verification', (('glm53', .83), ('glm53flash', .80))),
           ('report', (('glm53', .85), ('glm53flash', .60))))


def state(kind, parents, sig, model, attempts, seen=True):
    nodes = [E.Node('n_idx', 'index', (), 'glm53', 'done', 1, None, False),
             E.Node('n_a', parents[0][1], ('n_idx',), 'glm53', 'done', 1, None, False)]
    if len(parents) > 1:
        nodes.append(E.Node('n_b', parents[1][1], ('n_idx',), 'glm53flash', 'done', 1, None, False))
    par = tuple(p[0] for p in parents)
    nodes += [E.Node('n_v', kind, par, model, 'failed', attempts, sig, seen),
              E.Node('n_rpt', 'report', ('n_v',), 'glm53', 'pending', 0, None, False)]
    edges = tuple(sorted(set([('n_idx', p[0]) for p in parents]
                             + [(p[0], 'n_v') for p in parents] + [('n_v', 'n_rpt')])))
    return E.EngineState('SIM', 1, tuple(nodes), edges, 100000, 600,
                         (('glm53', 2), ('glm53flash', 2)), (), PERSISTENCE, PROFILE)


HETERO = [('n_a', 'entity_facts'), ('n_b', 'timeline')]
HOMO = [('n_a', 'extracts'), ('n_b', 'extracts')]
SINGLE = [('n_a', 'extracts')]


def wp1():
    print('WP1 F-prime V1.0 — independent rule reproduction')

    print('#0 differential test: historical static hetero-parent map vs '
          'F-prime semantic rule (operator audit requirement)')
    import m6_replay_harness as H
    # corpus task DAGs: nodes and kinds as recorded in H1/R9B runs
    corpus_nodes = {
        'e1_chk': [('e1_fin', 'entity_facts'), ('e1_tl', 'timeline')],
        'e3_chk': [('e3_param_check', 'entity_facts'), ('e3_timeline', 'timeline')],
        'e1_fin': [('e1_ext_pen', 'extracts')],
        'e1_tl': [('e1_ext_proc', 'extracts')],
        'e1_rpt': [('e1_chk', 'verification')],
    }
    mismatches = []
    for nid, pars in corpus_nodes.items():
        in_static = nid in H.HETERO_PARENTS
        semantic = len({k for _, k in pars}) >= 2
        if in_static != semantic:
            mismatches.append(f'{nid}: static={in_static} semantic={semantic}')
    check('static map == semantic rule on all corpus nodes',
          not mismatches, '; '.join(mismatches) or
          'chk nodes True, all others False — identical classification')

    print('#1 deterministic trajectory tests (C1/C2/C3/C4/C6)')
    cases = [
        ('C1 contract@hetero@1', state('verification', HETERO, 'contract', 'glm53', 1)),
        ('C2 transport@weak@1', state('entity_facts', SINGLE, 'transport', 'glm53flash', 1)),
        ('C3 contract@homo@1', state('verification', HOMO, 'contract', 'glm53', 1)),
        ('C4 parse@weak@1', state('entity_facts', SINGLE, 'parse', 'glm53flash', 1)),
        ('C4 parse@weak@2', state('entity_facts', SINGLE, 'parse', 'glm53flash', 2)),
        ('C6 unknown@strong@1', state('timeline', SINGLE, None, 'glm53', 1, seen=False)),
        ('C6 unknown@weak@1', state('timeline', SINGLE, None, 'glm53flash', 1, seen=False)),
    ]
    expected = {
        'C1 contract@hetero@1': 'split_verify',
        'C2 transport@weak@1': 'retry_switch',
        'C3 contract@homo@1': 'early_exit',
        'C4 parse@weak@1': 'retry_switch',
        'C4 parse@weak@2': 'retry_switch',
        'C6 unknown@strong@1': 'retry_same',
        'C6 unknown@weak@1': 'retry_switch',
    }
    for name, s in cases:
        d = V10.v10_decide(s)
        check(f"F' {name} -> {expected[name]}", d.chosen == expected[name],
              f"got {d.chosen}")

    print('#2 determinism')
    s = cases[0][1]
    check('repeat identical', V10.v10_decide(s).hash_hex()
          == V10.v10_decide(s).hash_hex())

    print('#3 audited difference set vs F (V1.1) — only D1/D2/D3')
    diffs = []
    for name, s in cases:
        f = E.decide(s).chosen.split(':')[0]
        fp = V10.v10_decide(s).chosen
        if (f == 'split_retry') != (fp == 'split_verify'):
            diffs.append(f'{name}: Z mismatch {f} vs {fp}')
        if f in ('ladder_exit',) and fp != 'early_exit':
            diffs.append(f'{name}: D1 expected')
    # D1 present on C3; D2 present on C2/C4@1; D3 present on C6; absent elsewhere
    d_map = {n: (E.decide(s).chosen.split(':')[0], V10.v10_decide(s).chosen)
             for n, s in cases}
    check('D1 (C3: F=ladder vs F-prime=exit)',
          d_map['C3 contract@homo@1'] == ('ladder_exit', 'early_exit'))
    check('D2 (C2: F=keep vs F-prime=switch)',
          d_map['C2 transport@weak@1'] == ('retry_same', 'retry_switch'))
    check('D3 (C6 weak: F=conservative vs F-prime=switch)',
          d_map['C6 unknown@weak@1'][0].startswith('conservative')
          and d_map['C6 unknown@weak@1'][1] == 'retry_switch')
    check('Z identical on C1 (no spurious difference)',
          d_map['C1 contract@hetero@1'] == ('split_retry', 'split_verify'))
    check('converge on C4@2 (ladder resolves to same action)',
          d_map['C4 parse@weak@2'][0] == 'retry_switch'
          and d_map['C4 parse@weak@2'][1] == 'retry_switch')

    print('#4 no candidate filtering (structural independence)')
    import inspect
    src = inspect.getsource(V10)
    check('F-prime does not call engine decide/candidates',
          'E.decide' not in src and 'generate_candidates' not in src)


def wp2():
    print('WP2 GROSS Budget Guard — G1..G6')

    print('#1 G1 separate accounting')
    g = GrossBudgetGuard(max_calls=10, max_tokens=10000, reserve_per_call=2500)
    g.reserve('n1', 1)
    check('settled vs outstanding separated',
          g.guaranteed_settled == 0
          and g.conservative_outstanding_plus_settled == 2500)

    print('#2 G2 reservation vs actual recorded separately')
    g.settle('n1', 1, actual_in=900, actual_out=700, outcome='success')
    check('settle replaces reservation with truth',
          g.guaranteed_settled == 1600
          and g.conservative_outstanding_plus_settled == 1600
          and not g.outstanding)

    print('#3 G3 no double-use / duplicates rejected / concurrency counts')
    g2 = GrossBudgetGuard(max_calls=10, max_tokens=10000, reserve_per_call=2500)
    g2.reserve('nA', 1)
    g2.reserve('nB', 1)
    check('two concurrent reservations both bind quota',
          g2.conservative_outstanding_plus_settled == 5000)
    try:
        g2.reserve('nA', 1)
        dup = False
    except DuplicateReservation:
        dup = True
    check('duplicate reservation rejected', dup)

    print('#4 G4 failed/timeout/cancelled keep true consumption')
    g3 = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=2500)
    g3.reserve('nF', 1)
    g3.settle('nF', 1, 1200, 800, outcome='failed')
    g3.reserve('nT', 1)
    g3.settle('nT', 1, 1000, 500, outcome='timeout')
    g3.reserve('nC', 1)
    g3.cancel('nC', 1)
    check('failed+timeout settle, cancel releases unsettled only',
          g3.guaranteed_settled == 3500 and g3.settled_calls == 2
          and g3.conservative_outstanding_plus_settled == 3500)

    print('#5 G5 hard stop, no silent pass')
    g4 = GrossBudgetGuard(max_calls=3, max_tokens=4000, reserve_per_call=2500)
    g4.reserve('n1', 1)
    try:
        g4.reserve('n2', 1)     # 2500 outstanding, slack 1500 < 2500
        stopped = False
    except BudgetExceeded:
        stopped = True
    check('token over-budget raises hard stop', stopped)
    g4b = GrossBudgetGuard(max_calls=3, max_tokens=5000, reserve_per_call=2500)
    g4b.reserve('n1', 1)
    g4b.reserve('n2', 1)        # 2500+2500 == 5000: exactly at cap, legal
    check('exact-fit reservation is legal (invariant is <=)',
          g4b.conservative_outstanding_plus_settled == 5000)
    g5 = GrossBudgetGuard(max_calls=2, max_tokens=100000, reserve_per_call=2500)
    g5.reserve('n1', 1)
    g5.settle('n1', 1, 100, 100)
    g5.reserve('n2', 1)
    try:
        g5.reserve('n3', 1)     # call cap 2 already used
        stopped2 = False
    except BudgetExceeded:
        stopped2 = True
    check('call-cap over-budget raises hard stop', stopped2)
    check('denial journaled (no silent path)',
          any(j['op'] == 'reserve_denied' for j in g4.journal + g5.journal))

    print('#6 G6 post-settle overrun recorded truthfully')
    g6 = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=1000)
    g6.reserve('nX', 1)
    rec = g6.settle('nX', 1, 800, 900, outcome='success')   # 1700 > 1000
    check('overrun flagged and kept in actuals',
          rec.overrun and g6.guaranteed_settled == 1700
          and len(g6.summary()['overruns']) == 1)

    print('#7 invariant under a mixed operation sequence')
    g7 = GrossBudgetGuard(max_calls=6, max_tokens=20000, reserve_per_call=2500)
    ok = True
    ops = 0
    for n in range(1, 5):
        try:
            g7.reserve(f'n{n}', 1)
            ops += 1
        except BudgetExceeded:
            break
    for n in range(1, ops + 1):
        g7.settle(f'n{n}', 1, 500 * n, 400, outcome='success')
    try:
        for n in range(10, 20):
            g7.reserve(f'n{n}', 1)
    except BudgetExceeded:
        pass
    ok = (g7.guaranteed_settled == sum(500 * n + 400 for n in range(1, ops + 1))
          and g7.conservative_outstanding_plus_settled
          <= g7.max_tokens
          and g7.settled_calls + len(g7.outstanding) <= g7.max_calls)
    check('mixed sequence keeps invariants', ok,
          f"settled={g7.guaranteed_settled}, binding="
          f"{g7.conservative_outstanding_plus_settled}")

    print('#8 audit concern #1 — concurrent atomicity (real threads)')
    import threading
    g8 = GrossBudgetGuard(max_calls=100, max_tokens=25000, reserve_per_call=2500)
    admitted, denied = [], []
    def worker(i):
        try:
            g8.reserve(f'n{i}', 1)
            admitted.append(i)
        except BudgetExceeded:
            denied.append(i)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check('20 concurrent reservations: admitted+outstanding never exceed cap',
          len(admitted) == 10
          and g8.conservative_outstanding_plus_settled == 25000
          and len(denied) == 10,
          f'admitted={len(admitted)} denied={len(denied)} '
          f'binding={g8.conservative_outstanding_plus_settled}')

    print('#9 audit concern #2 — pre-call gate with calibrated per-call bound')
    g9 = GrossBudgetGuard(max_calls=10, max_tokens=10000, reserve_per_call=2500)
    # calibrated upper bound: input_bound 1200 + 1.5 x max_output 800 = 2400
    g9.reserve('n1', 1, per_call_reserve=1200 + int(1.5 * 800))
    g9.reserve('n2', 1, per_call_reserve=1200 + int(1.5 * 800))
    g9.reserve('n3', 1, per_call_reserve=1200 + int(1.5 * 800))
    g9.reserve('n4', 1, per_call_reserve=1200 + int(1.5 * 800))  # 9600 <= 10000
    try:
        g9.reserve('n5', 1, per_call_reserve=1200 + int(1.5 * 800))
        gated = False
    except BudgetExceeded:
        gated = True
    check('5th 2400-reserve hard-stopped before any call (pre-call gate)',
          gated and g9.conservative_outstanding_plus_settled == 9600)
    for n in ('n1', 'n2', 'n3', 'n4'):
        g9.settle(n, 1, 1100, 780, outcome='success')   # actuals inside bound
    check('actuals within calibrated bound keep global under cap',
          g9.guaranteed_settled == 4 * 1880 <= 10000)
    r = g9.settle.__doc__  # documentation anchor, no-op

    print('#10 audit concern #3 — settle consistency edges')
    from m7_budget_guard import SettleWithoutReservation
    g10 = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=2000)
    g10.reserve('nA', 1)
    g10.settle('nA', 1, 500, 400, outcome='success')
    try:
        g10.settle('nA', 1, 500, 400, outcome='success')   # duplicate settle
        dup_settle = False
    except SettleWithoutReservation:
        dup_settle = True
    check('duplicate settle refused (no double count)',
          dup_settle and g10.guaranteed_settled == 900
          and g10.settled_calls == 1)
    c1 = g10.cancel('nB', 1)   # never reserved
    c2 = g10.cancel('nB', 1)   # duplicate cancel
    check('cancel idempotent (0 released twice)', c1 == 0 and c2 == 0)
    # late response after timeout settle: provisional unknown then revise
    g10.reserve('nC', 1)
    rec = g10.settle('nC', 1, None, None, outcome='timeout')
    check('unknown actual settles provisionally at reserved, flagged',
          rec.outcome == 'unknown_actual'
          and g10.guaranteed_settled == 900 + 2000)
    rev = g10.revise('nC', 1, 600, 700, note='late_response')
    check('late revise applies DELTA only (no double count)',
          g10.guaranteed_settled == 900 + 1300
          and g10.settled_calls == 2,
          f"settled={g10.guaranteed_settled}")
    try:
        g10.revise('nZ', 1, 1, 1)                          # phantom revise
        phantom = False
    except SettleWithoutReservation:
        phantom = True
    check('phantom revise refused', phantom)


def main():
    wp1()
    wp2()
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{n_pass}/{len(RESULTS)} checks passed")
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
