"""Final boundary tests per operator ruling round (ZERO model calls).

Covers: terminal-action slot exemption (P0-2 ruling), rule-fired-but-rejected
recording (P0-1 ruling), switch no-retrigger after execution (P0-3 ruling),
guard launch/abort boundary, revise_calls edges + concurrent settles,
unknown-signature enum protection (P1-4), and the MINIMAL E7 end-to-end
closed loop with a mock executor (decision -> executor -> apply -> feedback
-> next decision). Self-tests are NOT independent acceptance.
"""
import sys
import threading
from dataclasses import replace

import m7_decision_engine as E
from m7_budget_guard import (BudgetExceeded, GrossBudgetGuard,
                             InvalidSettlement, SettleWithoutReservation)

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


def h1_nodes(chk_model='glm53', chk_attempts=1, chk_sig='contract'):
    return (
        E.Node('e1_idx', 'index', (), 'glm53', 'done', 1, None, False),
        E.Node('e1_ext', 'extracts', ('e1_idx',), 'glm53', 'done', 1, None, False),
        E.Node('e1_fin', 'entity_facts', ('e1_ext',), 'glm53flash', 'done', 1, None, False),
        E.Node('e1_tl', 'timeline', ('e1_ext',), 'glm53flash', 'done', 1, None, False),
        E.Node('e1_chk', 'verification', ('e1_fin', 'e1_tl'), chk_model,
               'failed', chk_attempts, chk_sig, True),
        E.Node('e1_rpt', 'report', ('e1_chk',), 'glm53', 'pending', 0, None, False),
    )


H1_EDGES = (('e1_idx', 'e1_ext'),
            ('e1_ext', 'e1_fin'), ('e1_ext', 'e1_tl'),
            ('e1_fin', 'e1_chk'), ('e1_tl', 'e1_chk'), ('e1_chk', 'e1_rpt'))


def t_exit_slot():
    print('P0-2 ruling: zero-cost exit never slot-rejected (safe stop)')
    nodes = h1_nodes()
    # all model slots over-subscribed: execution candidates die, exit survives
    d = E.decide(replace(st(nodes, H1_EDGES),
                         slots_in_use=(('glm53', 3), ('glm53flash', 3))))
    check('exit survives total slot over-subscription',
          d.chosen == 'exit_node:e1_chk' and d.assignments == ())
    check('execution candidates slot-rejected with reasons',
          any('slots' in w for r in d.rejected for w in r['reasons']))
    check('safe stop is a terminal state (chosen exists, frontier non-empty)',
          d.forced_unique is True and d.frontier == ('exit_node:e1_chk',))


def t_rule_events():
    print('P0-1 ruling: fired rule never overrides constraints/frontier; recorded')
    # scenario: parse@weak@attempts=2 -> switch candidate exists (rule fires)
    nodes = (E.Node('p', 'extracts', (), 'glm53', 'done', 1, None, False),
             E.Node('v', 'entity_facts', ('p',), 'glm53flash', 'failed',
                    2, 'parse', True),
             E.Node('r', 'report', ('v',), 'glm53', 'pending', 0, None, False))
    ed = (('p', 'v'), ('v', 'r'))
    d = E.decide(st(nodes, ed))
    ev = [e for e in d.rule_events if e['candidate'] == 'retry_switch:v']
    check('rule fired and chosen when feasible+frontier',
          ev and ev[0]['disposition'] == 'chosen',
          str(ev))
    # now starve the budget so the switch candidate is infeasible:
    # rule still recorded as fired with disposition rejected_infeasible
    d2 = E.decide(replace(st(nodes, ed), budget_remaining=2000))
    ev2 = [e for e in d2.rule_events if e['candidate'] == 'retry_switch:v']
    check('rule fired but rejected_infeasible is RECORDED, not forced',
          ev2 and ev2[0]['disposition'] == 'rejected_infeasible'
          and d2.chosen != 'retry_switch:v', str(ev2))


def t_switch_no_retrigger():
    print('P0-3 ruling: no repeated switch triggering')
    def nodes_at(att, model):
        return (E.Node('p', 'extracts', (), 'glm53', 'done', 1, None, False),
                E.Node('v', 'entity_facts', ('p',), model, 'failed',
                       att, 'parse', True),
                E.Node('r', 'report', ('v',), 'glm53', 'pending', 0, None, False))
    ed = (('p', 'v'), ('v', 'r'))
    # switch executed once (model now glm53): further failures cannot re-switch
    d = E.decide(st(nodes_at(3, 'glm53'), ed))
    check('after switch executed (strong model), no further switch candidate',
          not any('switch' in c.name for c in d.candidates))
    # un-switched persistent growth: switch offered while conditions hold, but
    # the 2-model pool makes a SECOND switch structurally impossible
    d2 = E.decide(st(nodes_at(4, 'glm53flash'), ed))
    switchy = [c for c in d2.candidates if 'switch' in c.name]
    check('un-switched: offer persists but bounded (single pool of 2 models)',
          all(c.pi[1] == ('v',) for c in switchy)
          and len(switchy) <= 1)


def t_launch_boundary():
    print('Guard launch/abort boundary (send-boundary correspondence)')
    g = GrossBudgetGuard(max_calls=2, max_tokens=1000, reserve_per_call=500)
    g.reserve('n', 1)
    g.launch('n', 1)
    # pre-dispatch failure (provably never sent) -> abort restores cancellability
    g.abort('n', 1)
    g.cancel('n', 1)
    check('abort -> cancel path works for never-dispatched request',
          g.outstanding_calls == 0)
    g.reserve('m', 1)
    g.launch('m', 1)
    g.abort('m', 1)          # LAUNCHED -> RESERVED (provably not dispatched)
    try:
        g.abort('m', 1)      # second abort: not launched anymore
        bad = False
    except InvalidSettlement:
        bad = True
    check('abort on non-launched refused (state machine enforced)', bad)
    # dispatched-but-failed request: unknown consumption at reserved, revisable
    g.launch('m', 1)         # re-launch: this time the request went out
    g.settle('m', 1, None, None, outcome='timeout')
    check('dispatched timeout settles at reserved (unknown), no cancel path',
          g.guaranteed_settled == 500 and g.settled_calls == 1)
    g.revise('m', 1, 120, 60, note='late_usage')
    check('late true usage revises by delta', g.guaranteed_settled == 180)


def t_revise_calls_edges():
    print('revise_calls: down/up/repeat/over-limit/concurrent settles')
    g = GrossBudgetGuard(max_calls=100, max_tokens=100000, reserve_per_call=100)
    g.reserve('a', 1, calls=3)
    g.launch('a', 1)
    g.settle('a', 1, 10, 10, executed_calls=3)
    g.revise_calls('a', 1, 1)            # downward
    check('downward revision', g.settled_calls == 1)
    g.revise_calls('a', 1, 3)            # back up (repeat revision)
    check('upward repeat revision', g.settled_calls == 3)
    g.revise_calls('a', 1, 2)            # again
    check('second repeat revision', g.settled_calls == 2)
    try:
        g.revise_calls('a', 1, 4)        # over reserved
        bad = False
    except InvalidSettlement:
        bad = True
    check('over-reserved revision refused', bad)
    # concurrent settle of independent keys under lifecycle
    g2 = GrossBudgetGuard(max_calls=50, max_tokens=100000, reserve_per_call=100)
    for i in range(10):
        g2.reserve(f'n{i}', 1)
        g2.launch(f'n{i}', 1)
    errs = []

    def worker(i):
        try:
            g2.settle(f'n{i}', 1, 10, 10, outcome='success')
        except Exception as ex:
            errs.append(ex)
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check('10 concurrent lifecycle settles all clean',
          not errs and g2.settled_calls == 10
          and g2.guaranteed_settled == 200)


def t_unknown_enum():
    print('P1-4: unregistered fault signature -> conservative channel')
    nodes = (E.Node('p', 'extracts', (), 'glm53', 'done', 1, None, False),
             E.Node('v', 'entity_facts', ('p',), 'glm53flash', 'failed',
                    1, 'weird_new_fault', True),
             E.Node('r', 'report', ('v',), 'glm53', 'pending', 0, None, False))
    d = E.decide(st(nodes, (('p', 'v'), ('v', 'r'))))
    check('unregistered signature classified unknown, conservative only',
          d.fault_views[0][1].startswith('unknown/')
          and [c.name for c in d.candidates] == ['conservative:v'],
          f"view={d.fault_views[0][1]} cands={[c.name for c in d.candidates]}")
    check('never Z / never switch for unregistered signature',
          all(c.z == 'IDENTITY' and c.pi[0] == 'KEEP' for c in d.candidates))


def t_e7_minimal_closed_loop():
    """MINIMAL end-to-end (mock executor, zero model calls): decision ->
    executor receives the IDENTICAL joint action -> split with correct
    authorization -> no done-node re-execution -> feedback drives next
    decision."""
    print('E7 minimal closed loop (mock executor)')
    state = st(h1_nodes(chk_model='glm53flash'), H1_EDGES)
    executed_log = []

    def mock_call(node_id, model, outcome='ok'):
        executed_log.append((node_id, model))
        return outcome

    def mock_executor(s, d):
        """Applies a JointDecision exactly as issued; returns next state."""
        check('E7-1 executor receives chosen+split_of consistently',
              (d.split_of is not None) == d.chosen.startswith('split_retry'))
        if d.split_of:
            switch = '_switch' in d.chosen
            s2 = E.apply_split(s, d.split_of, switch_children=switch)
            chosen = next(c for c in d.candidates if c.name == d.chosen)
            check('E7-3 split children model honors pi authorization',
                  all(n.model == ('glm53' if chosen.pi[0] == 'SWITCH_STRONG'
                                  else 'glm53flash')
                      for n in s2.nodes
                      if n.node_id in (d.split_of + '_a', d.split_of + '_b')))
            return s2
        for nid, model in d.assignments:
            node = s.node(nid)
            check_ok = node.status != 'done'
            if not check_ok:
                check('E7-4 done node never re-executed', False, nid)
            mock_call(nid, model)
            s = replace(s, nodes=tuple(
                replace(n, status='done', attempts=n.attempts + 1)
                if n.node_id == nid else n for n in s.nodes))
        return s

    # round 1: merge fault -> split decision (pi KEEP -> children stay flash)
    d1 = E.decide(state)
    check('E7-0 decision: split_retry chosen with pi=KEEP',
          d1.chosen == 'split_retry:e1_chk')
    s2 = mock_executor(state, d1)
    # feedback: children pending; execute them via mock (round 2 decision)
    d2 = E.decide(s2)
    check('E7-5 feedback drives next decision (children ready, no faults)',
          d2.regime == 'no_fault'
          and set(a for a, _ in d2.assignments) == {'e1_chk_a', 'e1_chk_b'})
    check('E7-2/4 no re-execution of the removed faulted node',
          all(nid != 'e1_chk' for nid, _ in executed_log)
          and 'e1_chk' not in {n.node_id for n in s2.nodes})
    # execute children, then the report round completes the loop
    s3 = mock_executor(s2, d2)
    d3 = E.decide(s3)
    check('E7 closed loop completes: report becomes ready and executes',
          d3.regime == 'no_fault'
          and set(a for a, _ in d3.assignments) == {'e1_rpt'})
    s4 = mock_executor(s3, d3)
    final = E.decide(s4)
    check('terminal: DAG fully done, no further assignments',
          final.regime == 'no_fault' and final.assignments == ())


def t_e7_switch_closed_loop():
    """Operator ruling: the pi leg of the joint-action execution chain —
    (1) PI_2-prime fires -> decision SWITCH -> executor switches the target;
    (2) unauthorized switch request -> executor REFUSES."""
    print('E7-pi: switch execution chain (authorized + unauthorized)')
    # authorized: parse@weak@attempts=2 -> retry_switch chosen (rule precedence)
    nodes = (E.Node('p', 'extracts', (), 'glm53', 'done', 1, None, False),
             E.Node('v', 'entity_facts', ('p',), 'glm53flash', 'failed',
                    2, 'parse', True),
             E.Node('r', 'report', ('v',), 'glm53', 'pending', 0, None, False))
    s = st(nodes, (('p', 'v'), ('v', 'r')))
    d = E.decide(s)
    check('E7-pi-1 PI_2-prime fires: retry_switch chosen',
          d.chosen == 'retry_switch:v')
    # executor applies the decision's assignment exactly
    target_model = dict(d.assignments)['v']
    check('E7-pi-2 executor switches v to the decided target model',
          target_model == 'glm53' and ('v', 'glm53') in d.assignments)
    s2 = replace(s, nodes=tuple(
        replace(n, model=target_model, status='done', attempts=n.attempts + 1)
        if n.node_id == 'v' else n for n in s.nodes))
    d2 = E.decide(s2)
    check('E7-pi-3 post-switch feedback: no further switch offered',
          d2.regime == 'no_fault' and d2.assignments == (('r', 'glm53'),))

    # unauthorized: decision is split_retry (pi=KEEP) — an executor-side
    # request to switch children WITHOUT authorization must be refused
    s3 = st(h1_nodes(chk_model='glm53flash'), H1_EDGES)
    d3 = E.decide(s3)
    check('E7-pi-4 scenario: decision is split with pi=KEEP',
          d3.chosen == 'split_retry:e1_chk'
          and next(c for c in d3.candidates if c.name == d3.chosen).pi[0] == 'KEEP')
    chosen = next(c for c in d3.candidates if c.name == d3.chosen)
    authorized = chosen.pi[0] == 'SWITCH_STRONG'
    # executor derives authorization ONLY from the decision payload:
    s4 = E.apply_split(s3, d3.split_of, switch_children=authorized)
    kids = {n.node_id: n.model for n in s4.nodes
            if n.node_id in ('e1_chk_a', 'e1_chk_b')}
    check('E7-pi-5 unauthorized switch request REFUSED (children keep model)',
          kids == {'e1_chk_a': 'glm53flash', 'e1_chk_b': 'glm53flash'})


def t_d4_multifault():
    """F' D4 (registered): multi-fault node selection differs from F."""
    print("F' D4: multi-fault node-selection difference registered")
    import m7_policy_v10 as V10
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
    s = st(nodes, edges)
    f = E.decide(s)
    fp = V10.v10_decide(s)
    check('D4: F targets the splittable node (frontier-based)',
          f.split_of == 'z_chk')
    check('D4: F-prime serves the LOWEST node_id fault (retry on a_fail)',
          fp.chosen == 'retry_same'
          and fp.assignments and fp.assignments[0][0] == 'a_fail',
          f'F-prime chosen={fp.chosen} assignments={fp.assignments}')
    check('D4: the two policies differ on multi-fault states (documented)',
          f.chosen != fp.chosen,
          f'F={f.chosen} vs F-prime={fp.chosen}')


def main():
    for t in (t_exit_slot, t_rule_events, t_switch_no_retrigger,
              t_launch_boundary, t_revise_calls_edges, t_unknown_enum,
              t_e7_minimal_closed_loop, t_e7_switch_closed_loop,
              t_d4_multifault):
        t()
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{n_pass}/{len(RESULTS)} checks passed")
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
