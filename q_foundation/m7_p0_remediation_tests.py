"""P0 remediation adversarial tests (ZERO model calls).

Every test targets ONE original defect from the operator's audit (B1-B5,
E1-E7) with the adversarial input that originally exposed it. Self-tests are
necessary but NOT sufficient — the operator's independent re-audit remains
the acceptance gate (per the unified remediation principle).

Run: python3 m7_p0_remediation_tests.py   (exit 0 iff all pass)
"""
import sys
import threading
from dataclasses import replace

import m7_decision_engine as E
from m7_budget_guard import (AlreadySettled, BudgetExceeded,
                             DuplicateReservation, GrossBudgetGuard,
                             InvalidReservation, InvalidSettlement,
                             SettleWithoutReservation)

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


def st(nodes, edges, budget=100000, deadline=600., slots=(('glm53', 2), ('glm53flash', 2)),
       in_use=()):
    return E.EngineState('SIM', 1, tuple(nodes), tuple(edges), budget, deadline,
                         tuple(slots), tuple(in_use), PERSISTENCE, PROFILE)


def h1_nodes(chk_status='failed', chk_attempts=1, chk_sig='contract', chk_seen=True,
             chk_model='glm53', tl_status='done'):
    return (
        E.Node('e1_idx', 'index', (), 'glm53', 'done', 1, None, False),
        E.Node('e1_ext_pen', 'extracts', ('e1_idx',), 'glm53', 'done', 1, None, False),
        E.Node('e1_ext_proc', 'extracts', ('e1_idx',), 'glm53', 'done', 1, None, False),
        E.Node('e1_fin', 'entity_facts', ('e1_ext_pen',), 'glm53flash', 'done', 1, None, False),
        E.Node('e1_tl', 'timeline', ('e1_ext_proc',), 'glm53flash', tl_status, 1, None, False),
        E.Node('e1_chk', 'verification', ('e1_fin', 'e1_tl'), chk_model,
               chk_status, chk_attempts, chk_sig, chk_seen),
        E.Node('e1_rpt', 'report', ('e1_chk',), 'glm53', 'pending', 0, None, False),
    )


H1_EDGES = (('e1_idx', 'e1_ext_pen'), ('e1_idx', 'e1_ext_proc'),
            ('e1_ext_pen', 'e1_fin'), ('e1_ext_proc', 'e1_tl'),
            ('e1_fin', 'e1_chk'), ('e1_tl', 'e1_chk'), ('e1_chk', 'e1_rpt'))


# ------------------------------------------------------------ Guard B1-B5 --

def t_b1():
    print('B1: settled key re-reserve refused')
    g = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=1000)
    g.reserve('n', 1)
    g.launch('n', 1)
    g.settle('n', 1, 400, 300)
    try:
        g.reserve('n', 1)
        ok = False
    except AlreadySettled:
        ok = True
    check('B1 re-reserve after settle raises AlreadySettled',
          ok and g.settled_calls == 1 and g.settled_actual == 700)
    check('B1 denial journaled',
          any(j['op'] == 'reserve_denied_settled' for j in g.journal))


def t_b2():
    print('B2: negative/zero reservations rejected')
    g = GrossBudgetGuard(max_calls=10, max_tokens=5000, reserve_per_call=2500)
    cases = [dict(per_call_reserve=-100), dict(per_call_reserve=0),
             dict(calls=0), dict(calls=-3)]
    ok = True
    for kw in cases:
        try:
            g.reserve('n1', 1, **kw)
            ok = False
        except InvalidReservation:
            pass
    check('B2 negative/zero unit and calls all raise InvalidReservation', ok)
    check('B2 binding unchanged (no negative quota)',
          g.conservative_outstanding_plus_settled == 0
          and any(j['op'] == 'reserve_invalid' for j in g.journal))
    # positive floor still works
    g.reserve('n2', 1, per_call_reserve=100)
    check('B2 valid small reservation still admitted',
          g.outstanding_tokens == 100)


def t_b3():
    print('B3: reserved call COUNT tracked and reconciled')
    g = GrossBudgetGuard(max_calls=5, max_tokens=100000, reserve_per_call=1000)
    g.reserve('n', 1, calls=3)
    check('B3 outstanding calls counted pre-settle', g.outstanding_calls == 3)
    # a second reservation must see only 2 call slots left
    try:
        g.reserve('m', 1, calls=3)
        blocked = False
    except BudgetExceeded:
        blocked = True
    check('B3 call-cap enforced against outstanding CALLS (pre-execution)',
          blocked and g.settled_calls == 0)
    g.launch('n', 1)
    g.settle('n', 1, 500, 400)
    check('B3 settle accounts reserved calls (3, not 1)',
          g.settled_calls == 3 and g.guaranteed_settled == 900)
    # explicit executed subset is journaled with the discrepancy
    g.reserve('p', 1, calls=2)
    g.launch('p', 1)
    g.settle('p', 1, 100, 100, executed_calls=1)
    check('B3 executed-subset discrepancy journaled',
          g.settled_calls == 4
          and any(j.get('reserved_calls') == 2 and j.get('executed_calls') == 1
                  for j in g.journal))


def t_b4():
    print('B4: partial unknown never clobbers known values')
    g = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=1000)
    g.reserve('n', 1)
    g.launch('n', 1)
    rec = g.settle('n', 1, actual_in=None, actual_out=1800)
    check('B4 known output 1800 preserved; overrun detected',
          rec.actual_out == 1800 and rec.overrun
          and rec.provisional_parts == ('in',)
          and g.guaranteed_settled == 1800)
    g2 = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=2000)
    g2.reserve('m', 1)
    g2.launch('m', 1)
    rec2 = g2.settle('m', 1, actual_in=600, actual_out=None)
    check('B4 known input kept, unknown side provisional within reserved',
          rec2.actual_in == 600 and rec2.provisional_parts == ('out',)
          and g2.guaranteed_settled == 2000 and not rec2.overrun)
    g2.revise('m', 1, 600, 500, note='late_out')
    check('B4 provisional revised to truth by delta',
          g2.guaranteed_settled == 1100)


def t_b5():
    print('B5: negative actuals rejected (settle and revise)')
    g = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=1000)
    g.reserve('n', 1)
    try:
        g.launch('n', 1)
        g.settle('n', 1, -500, -300)
        ok1 = False
    except InvalidSettlement:
        ok1 = True
    check('B5 negative settle refused, reservation restored',
          ok1 and ('n', 1) in g.outstanding
          and g.guaranteed_settled == 0)
    g.settle('n', 1, 500, 300)   # reservation stayed LAUNCHED through the refusal
    try:
        g.revise('n', 1, -100, 0)
        ok2 = False
    except InvalidSettlement:
        ok2 = True
    check('B5 negative revise target refused', ok2)
    # legitimate downward correction still allowed (negative DELTA is fine)
    g.revise('n', 1, 400, 200, note='overcount_correction')
    check('B5 downward correction via revise still works',
          g.guaranteed_settled == 600)


def t_bcombo():
    print('B-combo: overrun settle then continued gating on TRUE cumulative')
    g = GrossBudgetGuard(max_calls=10, max_tokens=5000, reserve_per_call=1000)
    g.reserve('a', 1)
    g.launch('a', 1)
    g.settle('a', 1, 2000, 1500, outcome='success')     # 3500 actual > 1000 reserved
    try:
        g.reserve('b', 1, per_call_reserve=2000)        # 3500+2000 > 5000
        gated = False
    except BudgetExceeded:
        gated = True
    check('post-overrun reservation gated on TRUE cumulative actuals',
          gated and g.guaranteed_settled == 3500)
    # threads x settled keys: no resurrection under concurrency
    gg = GrossBudgetGuard(max_calls=100, max_tokens=100000, reserve_per_call=100)
    gg.reserve('k', 1)
    gg.launch('k', 1)
    gg.settle('k', 1, 10, 10)
    errs = []

    def worker():
        try:
            gg.reserve('k', 1)
        except AlreadySettled:
            errs.append('settled')
        except Exception as ex:
            errs.append(f'other:{ex!r}')
    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check('concurrent re-reserve of settled key: all rejected, none admitted',
          len(errs) == 8 and all(e == 'settled' for e in errs)
          and gg.settled_calls == 1)


# ------------------------------------------------------------ Engine E1-E7 --

def t_e1():
    print('E1: no-fault path is constraint-gated')
    nodes = tuple(replace(n, status='done') if n.node_id in
                  ('e1_chk', 'e1_tl') else n for n in h1_nodes())
    s_ok = st(nodes, H1_EDGES)
    d = E.decide(s_ok)
    check('E1 healthy state executes ready set normally',
          d.chosen == 'normal_execution' and d.assignments == (('e1_rpt', 'glm53'),))
    d0 = E.decide(replace(s_ok, budget_remaining=0))
    check('E1 zero budget blocks normal execution with audit trail',
          d0.chosen is None and d0.assignments == ()
          and any('budget' in w for w in d0.rejected[0]['reasons']))
    dd = E.decide(replace(s_ok, deadline_remaining_s=0.))
    check('E1 zero deadline blocks normal execution',
          dd.chosen is None and dd.assignments == ()
          and any('deadline' in w for w in dd.rejected[0]['reasons']))
    ds = E.decide(replace(s_ok, slots_in_use=(('glm53', 2), ('glm53flash', 2))))
    check('E1 zero free slots block normal execution',
          ds.chosen is None and ds.assignments == ()
          and any('slots' in w for w in ds.rejected[0]['reasons']))


def t_e2():
    print('E2: slot check compares PLANNED demand vs free slots')
    # total glm53 slots 1, none in use; split candidate needs 2 glm53 children
    nodes = h1_nodes(chk_model='glm53')
    s = st(nodes, H1_EDGES, slots=(('glm53', 1), ('glm53flash', 2)))
    d = E.decide(s)
    reasons = [w for r in d.rejected for w in r['reasons']]
    check('E2 split rejected when children demand exceeds free slots',
          any('planned 2 > free 1' in w for w in reasons),
          '; '.join(reasons[:2]))
    # one slot in use, one ready glm53 node -> normal path must also block
    nodes2 = tuple(replace(n, status='done') if n.node_id in
                   ('e1_chk', 'e1_tl') else n for n in h1_nodes())
    s2 = st(nodes2, H1_EDGES, slots=(('glm53', 1),), in_use=(('glm53', 1),))
    d2 = E.decide(s2)
    check('E2 normal path blocked when ready demand exceeds free slot',
          d2.chosen is None and any('planned 1 > free 0' in w
                                    for w in d2.rejected[0]['reasons']))


def t_e3():
    print('E3: split_of follows the CHOSEN candidate (multi-fault P0)')
    # a_fail (unknown signature, lowest id) + z_chk (merge fault, splittable)
    nodes = (
        E.Node('a_fail', 'timeline', ('p_x',), 'glm53', 'failed', 1, None, False),
        E.Node('p_x', 'extracts', (), 'glm53', 'done', 1, None, False),
        E.Node('p_y', 'entity_facts', (), 'glm53', 'done', 1, None, False),
        E.Node('z_chk', 'verification', ('p_x', 'p_y'), 'glm53', 'failed', 1,
               'contract', True),
        E.Node('z_rpt', 'report', ('z_chk',), 'glm53', 'pending', 0, None, False),
    )
    edges = (('p_x', 'a_fail'), ('p_x', 'z_chk'), ('p_y', 'z_chk'),
             ('z_chk', 'z_rpt'))
    d = E.decide(st(nodes, edges))
    check('E3 chosen candidate is split on z_chk (not the lowest-id fault)',
          d.chosen == 'split_retry:z_chk')
    check('E3 split_of == z_chk (was faulted[0]=a_fail before fix)',
          d.split_of == 'z_chk')
    s2 = E.apply_split(st(nodes, edges), 'z_chk')
    check('E3 split executes on the correct node',
          any(n.node_id == 'z_chk_a' for n in s2.nodes)
          and not any(n.node_id == 'z_chk' for n in s2.nodes))


def t_e4():
    print('E4: apply_split structural integrity (in-edges, parent union, strict acyclic)')
    nodes = (
        E.Node('p1', 'entity_facts', (), 'glm53', 'done', 1, None, False),
        E.Node('p2', 'timeline', (), 'glm53flash', 'done', 1, None, False),
        E.Node('p3', 'extracts', (), 'glm53', 'done', 1, None, False),
        E.Node('chk', 'verification', ('p1', 'p2'), 'glm53', 'failed', 1,
               'contract', True),
        E.Node('report', 'report', ('chk', 'p3'), 'glm53', 'pending', 0, None, False),
    )
    edges = (('p1', 'chk'), ('p2', 'chk'), ('p3', 'report'), ('chk', 'report'))
    s2 = E.apply_split(st(nodes, edges), 'chk')
    ids = {n.node_id for n in s2.nodes}
    check('E4 no dangling in-edges to removed node',
          all(a in ids and b in ids for a, b in s2.edges)
          and not any(b == 'chk' for a, b in s2.edges))
    rpt = next(n for n in s2.nodes if n.node_id == 'report')
    check('E4 independent parent p3 PRESERVED (union, not overwrite)',
          rpt.parents == ('chk_a', 'chk_b', 'p3'))
    E._assert_structure(s2)
    check('E4 parents/edges consistency assertion passes', True)
    # strict _acyclic: a dangling edge must now FAIL (was silently ignored)
    bad_nodes = (E.Node('a', 'extracts', (), 'glm53', 'done', 1, None, False),)
    bad_edges = (('a', 'ghost'),)
    check('E4 _acyclic rejects dangling edges',
          not E._acyclic(st(bad_nodes, bad_edges)))


def t_baudit2():
    """Round-2 audit findings: executed_calls range/type, strict integer
    ledger params, headroom/reserve calibration consistency."""
    print('B3+: executed_calls validation (negative/over/non-int/bool/zero)')
    g = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=1000)
    g.reserve('n', 1, calls=3)
    bad = [-1, 4, 1.5, True, '2', 0]
    ok = True
    g.launch('n', 1)     # launch once; refused settles keep it LAUNCHED
    for ec in bad:
        try:
            g.settle('n', 1, 100, 100, executed_calls=ec)
            ok = False
        except InvalidSettlement:
            pass
    check('B3+ all invalid executed_calls refused (incl. ZERO)',
          ok and ('n', 1) in g.outstanding and g.settled_calls == 0)

    print('B3++ operator repro: zero-call settle must NOT free call quota')
    g0 = GrossBudgetGuard(max_calls=1, max_tokens=100, reserve_per_call=10)
    g0.reserve('n1', 1)
    try:
        g0.launch('n1', 1)
        g0.settle('n1', 1, actual_in=5, actual_out=5, executed_calls=0)
        refused = False
    except InvalidSettlement:
        refused = True
    check('B3++ zero-call settle refused despite token consumption',
          refused and ('n1', 1) in g0.outstanding)
    try:
        g0.reserve('n2', 1)
        blocked = False
    except BudgetExceeded:
        blocked = True
    check('B3++ call cap still binds after refused zero-call settle',
          blocked and g0.settled_calls == 0)
    # the reservation is LAUNCHED (request in flight): the only honest exit
    # is settling with >=1 call — lifecycle forbids cancel-after-launch
    g0.settle('n1', 1, 5, 5)          # 1 call, 10 tokens (truth)
    try:
        g0.reserve('n2', 1)           # call cap 1 now truly consumed
        blocked2 = False
    except BudgetExceeded:
        blocked2 = True
    check('B3++ honest settle consumes the call slot (cap binds)',
          blocked2 and g0.settled_calls == 1)
    # cancel remains sanctioned ONLY for never-launched reservations
    g1 = GrossBudgetGuard(max_calls=1, max_tokens=100, reserve_per_call=10)
    g1.reserve('q', 1)
    g1.cancel('q', 1)                 # never launched -> releasable
    check('B3++ cancel() sanctioned for a never-launched reservation',
          g1.reserve('q2', 1) == 10)

    print('B2+: strict integer params (floats and bools never enter ledger)')
    g2 = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=1000)
    for kw in (dict(calls=1.5), dict(calls=True), dict(per_call_reserve=100.5),
               dict(per_call_reserve=True), dict(calls=0)):
        try:
            g2.reserve('x', 1, **kw)
            bad_ok = False
            break
        except (InvalidReservation,):
            bad_ok = True
    else:
        bad_ok = True
    check('B2+ reserve rejects float/bool/nonpositive params', bad_ok)
    g2.reserve('y', 1)
    g2.launch('y', 1)
    for args in ((100.5, 0), (True, 0)):
        try:
            g2.settle('y', 1, *args)
            fl = False
            break
        except InvalidSettlement:
            fl = True
    else:
        fl = True
    check('B2+ settle rejects float/bool actuals, reservation restored',
          fl and ('y', 1) in g2.outstanding and g2.guaranteed_settled == 0)
    g2.settle('y', 1, 100, 50)   # still LAUNCHED through the refusals
    try:
        g2.revise('y', 1, 100.5, 50)
        rv = False
    except InvalidSettlement:
        rv = True
    check('B2+ revise rejects float targets', rv)

    print('headroom/reserve calibration consistency')
    g3 = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=1000)
    consistent = True
    for kw in (dict(calls=-1), dict(calls=1.5), dict(per_call_reserve=-100),
               dict(per_call_reserve=50.5)):
        try:
            g3.headroom(**kw)
            consistent = False
        except InvalidReservation:
            pass
    check('headroom applies the SAME param gate as reserve', consistent)
    fits, tok, cal = g3.headroom(calls=2, per_call_reserve=500)
    check('headroom valid query consistent with reserve arithmetic',
          fits and tok == 100000 and cal == 10)


def t_e5():
    print('E5: transient retry budget exhausts (attempts semantics defined)')
    # attempts = executions already happened; cap=2 retries after first failure
    def nodes_at(att):
        return (E.Node('p', 'extracts', (), 'glm53', 'done', 1, None, False),
                E.Node('v', 'entity_facts', ('p',), 'glm53flash', 'failed',
                       att, 'transport', True),
                E.Node('r', 'report', ('v',), 'glm53', 'pending', 0, None, False))
    ed = (('p', 'v'), ('v', 'r'))
    d1 = E.decide(st(nodes_at(1), ed))
    check('E5 attempts=1 -> retry candidate present (remaining=2)',
          any(c.name == 'retry_same:v' for c in d1.candidates))
    d2 = E.decide(st(nodes_at(2), ed))
    check('E5 attempts=2 -> remaining=1',
          any(c.name == 'retry_same:v' for c in d2.candidates)
          and next(c for c in d2.candidates if c.name == 'retry_same:v').reserve_calls == 1)
    d3 = E.decide(st(nodes_at(3), ed))
    check('E5 attempts=3 -> NO retry candidate (exit only)',
          not any(c.name.startswith('retry') for c in d3.candidates)
          and [c.name for c in d3.candidates] == ['exit_node:v'])
    d4 = E.decide(st(nodes_at(4), ed))
    check('E5 attempts=4 (over cap) -> same exhausted behaviour, no negative',
          [c.name for c in d4.candidates] == ['exit_node:v'])


def t_e6():
    print('E6: quality and reliability are separate axes')
    a = E.Candidate('a', 'IDENTITY', ('RETRY_SAME', ('v',)), ('SWITCH_STRONG', ('v',)),
                    p_recover=0.76, dq_hat=0.17, dc_hat=1000, dl_hat=10.0,
                    reserve_calls=1)
    b = E.Candidate('b', 'IDENTITY', ('RETRY_SAME', ('v',)), ('KEEP', ()),
                    p_recover=0.76, dq_hat=None, dc_hat=900, dl_hat=9.0,
                    reserve_calls=1)
    check('E6 dq=None vs dq=0.17 incomparable -> no dominance either way',
          not E._cand_dominates(a, b) and not E._cand_dominates(b, a))
    c = E.Candidate('c', 'IDENTITY', ('RETRY_SAME', ('v',)), ('KEEP', ()),
                    p_recover=0.5, dq_hat=None, dc_hat=900, dl_hat=9.0,
                    reserve_calls=1)
    d = E.Candidate('d', 'IDENTITY', ('RETRY_SAME', ('v',)), ('KEEP', ()),
                    p_recover=0.9, dq_hat=None, dc_hat=900, dl_hat=9.0,
                    reserve_calls=1)
    check('E6 both-dq-None: reliability axis still yields dominance',
          E._cand_dominates(d, c) and not E._cand_dominates(c, d))
    e = E.Candidate('e', 'IDENTITY', ('RETRY_SAME', ('v',)), ('KEEP', ()),
                    p_recover=0.76, dq_hat=None, dc_hat=900, dl_hat=9.0,
                    reserve_calls=1)
    f = E.Candidate('f', 'IDENTITY', ('RETRY_SAME', ('v',)), ('KEEP', ()),
                    p_recover=0.76, dq_hat=None, dc_hat=950, dl_hat=9.5,
                    reserve_calls=1)
    check('E6 equal reliability, cheaper dominates (cost axis intact)',
          E._cand_dominates(e, f))

    print('E6+: selection NEVER ranks a None dq (no numeric slot for missing)')
    # structural: the selection key in decide() source contains no dq_hat
    import inspect
    src = inspect.getsource(E.decide)
    key_line = [l for l in src.splitlines() if 'key=lambda' in l]
    check('E6+ selection key structurally excludes dq_hat',
          key_line and all('dq_hat' not in l for l in key_line),
          key_line[0].strip() if key_line else 'no key line')
    # behavioural: equal-reliability tie resolves by COST even when only one
    # candidate carries a (single-cell) quality estimate
    nodes = (E.Node('p', 'extracts', (), 'glm53', 'done', 1, None, False),
             E.Node('v', 'entity_facts', ('p',), 'glm53flash', 'failed',
                    2, 'parse', True),
             E.Node('r', 'report', ('v',), 'glm53', 'pending', 0, None, False))
    d2 = E.decide(st(nodes, (('p', 'v'), ('v', 'r'))))
    by_name = {c.name: c for c in d2.candidates}
    check('E6+ scenario: switch candidate carries dq, keep does not',
          by_name['retry_switch:v'].dq_hat is not None
          and by_name['retry_same:v'].dq_hat is None)
    check('E6+/P0-1 no assumed switch cost gain: dc_hat equal',
          by_name['retry_switch:v'].dc_hat == by_name['retry_same:v'].dc_hat)
    check('E6+/P0-1 full tie resolved by RULE precedence (PI_2-prime fired)',
          d2.chosen == 'retry_switch:v')
    check('E6+/P0-1 unapplied prior annotated on switch candidate',
          any(k == 'switch_cost_effect' and 'NOT applied' in v
              for k, v in by_name['retry_switch:v'].cal))


def t_e7():
    print('E7: split never implicitly switches models')
    nodes = h1_nodes(chk_model='glm53flash')   # weak model on the faulted node
    s = st(nodes, H1_EDGES)
    d = E.decide(s)
    check('E7 scenario setup: split chosen with pi=KEEP',
          d.chosen == 'split_retry:e1_chk')
    s2 = E.apply_split(s, 'e1_chk')            # default: no authorization
    kids = {n.node_id: n.model for n in s2.nodes
            if n.node_id in ('e1_chk_a', 'e1_chk_b')}
    check('E7 children KEEP the faulted node model (glm53flash)',
          kids == {'e1_chk_a': 'glm53flash', 'e1_chk_b': 'glm53flash'})
    s3 = E.apply_split(s, 'e1_chk', switch_children=True)   # explicit authorization
    kids3 = {n.node_id: n.model for n in s3.nodes
             if n.node_id in ('e1_chk_a', 'e1_chk_b')}
    check('E7 explicit authorization switches children to strong model',
          kids3 == {'e1_chk_a': 'glm53', 'e1_chk_b': 'glm53'})


def t_p0_final():
    """Final-round P0s: engine P0-2 (frontier-constrained selection, empty
    front), P0-3 (ladder_switch reachability), guard lifecycle (cancel vs
    launched), revise_calls, constructor validation, cancel journal calls."""
    print('P0-2: selection restricted to the Pareto FRONTIER')
    # scenario: h1 merge fault -> kept = {exit, ladder, split}; front should
    # contain all three (priced recovery); chosen must be a FRONT member
    nodes = h1_nodes()
    s = st(nodes, H1_EDGES)
    d = E.decide(s)
    check('P0-2 chosen candidate is a frontier member',
          d.chosen in d.frontier, f'chosen={d.chosen} front={d.frontier}')
    # dominated-choosable counter-example: craft kept where max-key would
    # pick a dominated candidate if selection were over kept
    a = E.Candidate('c_exit', 'IDENTITY', ('EARLY_EXIT', ('v',)), ('KEEP', ()),
                    p_recover=0.0, dq_hat=None, dc_hat=0, dl_hat=0.0,
                    reserve_calls=0)
    b = E.Candidate('b_dom', 'IDENTITY', ('EARLY_EXIT', ('v',)), ('KEEP', ()),
                    p_recover=0.0, dq_hat=None, dc_hat=100, dl_hat=5.0,
                    reserve_calls=1)          # strictly dominated by c_exit
    front = E.pareto_frontier([a, b])
    check('P0-2 dominated candidate excluded from frontier',
          [c.name for c in front] == ['c_exit'])
    # OPERATOR RULING (supersedes this test's old premise): the zero-cost
    # exit is a TERMINAL action that consumes no model slots — it can no
    # longer be rejected by slot over-subscription, so a faulted state always
    # has a feasible safe stop and the front is never empty by constraints.
    # The empty-front branch is defensive-only; assert the new semantics:
    d2 = E.decide(replace(st(nodes, H1_EDGES),
                          slots_in_use=(('glm53', 3), ('glm53flash', 3))))
    check('P0-2 slot-starved state falls back to the terminal safe stop',
          d2.chosen == 'exit_node:e1_chk' and d2.frontier == ('exit_node:e1_chk',)
          and d2.forced_unique is True,
          f'chosen={d2.chosen} front={d2.frontier}')
    # defensive branch still correct for a genuinely empty frontier
    check('P0-2 empty frontier is defensive-only (forced_unique stays False)',
          E.detect_regime([], []) == 'empty'
          and (not E.pareto_frontier([])))

    print('P0-3: ladder_switch reachable exactly at attempts>=2 (persistent+weak+gap)')
    def pers_nodes(att, model):
        return (E.Node('p', 'extracts', (), 'glm53', 'done', 1, None, False),
                E.Node('v', 'entity_facts', ('p',), model, 'failed',
                       att, 'contract', True),
                E.Node('r', 'report', ('v',), 'glm53', 'pending', 0, None, False))
    ed = (('p', 'v'), ('v', 'r'))
    d1 = E.decide(st(pers_nodes(1, 'glm53flash'), ed))
    check('P0-3 attempts=1: ladder_exit present, NO switch candidate',
          any(c.name == 'ladder_exit:v' for c in d1.candidates)
          and not any('switch' in c.name for c in d1.candidates))
    d2 = E.decide(st(pers_nodes(2, 'glm53flash'), ed))
    check('P0-3 attempts=2: ladder_switch GENERATED (path reachable)',
          any(c.name == 'ladder_switch:v' for c in d2.candidates))
    check('P0-3 attempts=2: no further same-config ladder',
          not any(c.name == 'ladder_exit:v' for c in d2.candidates))
    check('P0-3 switch fires per PI_2-prime ladder (p tie -> parsimony vs exit)',
          d2.chosen == 'ladder_switch:v')
    d3 = E.decide(st(pers_nodes(2, 'glm53'), ed))   # strong model: no switch
    check('P0-3 strong model at attempts=2: exit only',
          [c.name for c in d3.candidates] == ['exit_node:v'])

    print('Guard final-P0: lifecycle and revise_calls')
    g = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=1000)
    g.reserve('n', 1)
    g.launch('n', 1)
    try:
        g.cancel('n', 1)
        ok_cancel = False
    except InvalidSettlement:
        ok_cancel = True
    check('lifecycle: cancel refused after LAUNCH (must settle)',
          ok_cancel and g.outstanding_calls == 1)
    g2 = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=1000)
    g2.reserve('m', 1)
    try:
        g2.settle('m', 1, 100, 100)   # deliberately NOT launched
        ok_settle = False
    except SettleWithoutReservation:
        ok_settle = True
    check('lifecycle: settle refused without LAUNCH (use cancel)',
          ok_settle and ('m', 1) in g2.outstanding)
    g2.cancel('m', 1)
    check('lifecycle: cancel of un-launched reservation still works',
          g2.outstanding_calls == 0
          and any(j.get('released_calls') == 1 for j in g2.journal))
    g3 = GrossBudgetGuard(max_calls=10, max_tokens=100000, reserve_per_call=1000)
    g3.reserve('k', 1, calls=2)
    g3.launch('k', 1)
    g3.settle('k', 1, 100, 100, executed_calls=1)
    d = g3.revise_calls('k', 1, 2)
    check('revise_calls: delta applied to settled_calls',
          d == 1 and g3.settled_calls == 2)
    try:
        g3.revise_calls('k', 1, 3)
        bad = False
    except InvalidSettlement:
        bad = True
    check('revise_calls: bounds [1, reserved] enforced', bad)
    for kw in (dict(max_calls=0, max_tokens=100),
               dict(max_calls=1.5, max_tokens=100),
               dict(max_calls=5, max_tokens=-5),
               dict(max_calls=5, max_tokens=True),
               dict(max_calls=5, max_tokens=100, reserve_per_call=0)):
        try:
            GrossBudgetGuard(**kw)
            ctor = False
            break
        except InvalidReservation:
            ctor = True
    else:
        ctor = True
    check('constructor: invalid caps rejected at construction', ctor)


def main():
    for t in (t_b1, t_b2, t_b3, t_b4, t_b5, t_bcombo, t_baudit2,
              t_e1, t_e2, t_e3, t_e4, t_e5, t_e6, t_e7, t_p0_final):
        t()
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{n_pass}/{len(RESULTS)} checks passed")
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
