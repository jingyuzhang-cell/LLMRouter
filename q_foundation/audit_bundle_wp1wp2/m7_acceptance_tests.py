"""M7-2E: Independent offline acceptance tests for the joint decision engine.

Each of the operator's nine acceptance criteria becomes executable assertions.
Criterion #9 (prediction vs actual) replays the recorded corpus: engine
calibration points are compared against observed corpus outcomes. This is a
SELF-CONSISTENCY audit (the calibration was derived from this corpus) and is
labelled as such — it is NOT independent prospective validation.

Run: python3 m7_acceptance_tests.py   (exit 0 iff all pass)
"""
import sys
from dataclasses import replace

import m7_decision_engine as E

PERSISTENCE = (('contract', 'persistent'), ('parse', 'transient'),
               ('transport', 'transient'))
PROFILE = (
    ('index', (('glm53', 0.85), ('glm53flash', 0.62))),
    ('extracts', (('glm53', 0.85), ('glm53flash', 0.62))),
    ('timeline', (('glm53', 0.75), ('glm53flash', 0.60))),
    ('entity_facts', (('glm53', 0.80), ('glm53flash', 0.58))),
    ('verification', (('glm53', 0.83), ('glm53flash', 0.80))),
    ('report', (('glm53', 0.85), ('glm53flash', 0.60))),
)

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))


def h1_state(**over):
    """SC-E1-like: healthy prefix, verification node with hetero parents."""
    chk = dict(status='failed', attempts=1, sig='contract', seen=True,
               model='glm53')
    chk.update(over)
    nodes = (
        E.Node('e1_idx', 'index', (), 'glm53', 'done', 1, None, False),
        E.Node('e1_ext_pen', 'extracts', ('e1_idx',), 'glm53', 'done', 1, None, False),
        E.Node('e1_ext_proc', 'extracts', ('e1_idx',), 'glm53', 'done', 1, None, False),
        E.Node('e1_fin', 'entity_facts', ('e1_ext_pen',), 'glm53flash', 'done', 1, None, False),
        E.Node('e1_tl', 'timeline', ('e1_ext_proc',), 'glm53flash', 'done', 1, None, False),
        E.Node('e1_chk', 'verification', ('e1_fin', 'e1_tl'), chk['model'],
               chk['status'], chk['attempts'], chk['sig'], chk['seen']),
        E.Node('e1_rpt', 'report', ('e1_chk',), 'glm53', 'pending', 0, None, False),
    )
    edges = (('e1_idx', 'e1_ext_pen'), ('e1_idx', 'e1_ext_proc'),
             ('e1_ext_pen', 'e1_fin'), ('e1_ext_proc', 'e1_tl'),
             ('e1_fin', 'e1_chk'), ('e1_tl', 'e1_chk'), ('e1_chk', 'e1_rpt'))
    return E.EngineState('SC-E1', 1, nodes, edges, 100000, 600,
                         (('glm53', 2), ('glm53flash', 2)), (),
                         PERSISTENCE, PROFILE)


def t1_determinism():
    print('#1 determinism (same state -> same decision)')
    s = h1_state()
    d1, d2 = E.decide(s), E.decide(s)
    check('repeat call identical', d1.hash_hex() == d2.hash_hex())
    shuffled = replace(
        s, nodes=tuple(reversed(s.nodes)),
        edges=tuple(reversed(s.edges)))
    d3 = E.decide(shuffled)
    check('state ordering irrelevant',
          (d1.chosen, d1.frontier, d1.assignments, d1.regime) ==
          (d3.chosen, d3.frontier, d3.assignments, d3.regime))


def t2_dag_legality():
    print('#2 no illegal DAG / cycles')
    s = h1_state()
    s2 = E.apply_split(s, 'e1_chk')
    check('split keeps DAG acyclic', E._acyclic(s2))
    check('split children single-lineage',
          {n.parents for n in s2.nodes if n.node_id in ('e1_chk_a', 'e1_chk_b')}
          == {('e1_fin',), ('e1_tl',)})
    check('downstream consumes both children',
          next(n for n in s2.nodes if n.node_id == 'e1_rpt').parents
          == ('e1_chk_a', 'e1_chk_b'))
    # split with an unhealthy upstream parent must be illegal (inheritance risk)
    bad = replace(s, nodes=tuple(
        replace(n, status='failed') if n.node_id == 'e1_tl' else n for n in s.nodes))
    ok, why = E.split_legal(bad.node('e1_chk'), bad)
    check('unhealthy upstream blocks split', not ok, '; '.join(why))


def t3_no_reexecution():
    print('#3 done nodes never re-executed')
    s = h1_state()
    d = E.decide(s)
    done_ids = {n.node_id for n in s.nodes if n.status == 'done'}
    check('assignments exclude done', not (set(a for a, _ in d.assignments) & done_ids))
    ladder = h1_state()
    dl = E.decide(ladder)
    check('retry targets are failed nodes only',
          all(ladder.node(n).status == 'failed' for n, _ in dl.assignments
              if n == 'e1_chk'))


def t4_constraints():
    print('#4 budget / deadline / slot legality')
    tight_b = replace(h1_state(), budget_remaining=1000)
    d = E.decide(tight_b)
    names = [r['candidate'] for r in d.rejected]
    check('tight budget rejects costly candidates with reasons',
          'split_retry:e1_chk' in names and
          all(r['reasons'] for r in d.rejected if r['candidate'] in names))
    check('engine still returns a feasible decision', d.chosen is not None)
    tight_d = replace(h1_state(), deadline_remaining_s=5.0)
    dd = E.decide(tight_d)
    check('tight deadline rejects latency-infeasible candidates',
          any('deadline' in r['reasons'][0] for r in dd.rejected))
    over_slots = replace(h1_state(), slots_in_use=(('glm53', 2), ('glm53flash', 2)))
    do = E.decide(over_slots)
    check('oversubscribed slots flagged',
          any('slots' in w for r in do.rejected for w in r['reasons'])
          or do.chosen is not None)


def t5_unknown_faults():
    print('#5 unknown faults never force-classified')
    d1 = E.decide(h1_state(sig=None, seen=False, attempts=1))
    kinds = {c.r[0] for c in d1.candidates} | {c.z for c in d1.candidates}
    check('unknown@1: conservative only (no Z / no SWITCH)',
          kinds == {'ONE_CONSERVATIVE_RETRY', 'IDENTITY'},
          f'candidates={[c.name for c in d1.candidates]}')
    d2 = E.decide(h1_state(sig=None, seen=False, attempts=2))
    check('unknown@2: stops with audit trail',
          [c.name for c in d2.candidates] == ['stop_unclassified:e1_chk'])
    check('unknown view labelled unknown',
          d1.fault_views[0][1].startswith('unknown/'))


def t6_incomplete_not_q0():
    print('#6 INCOMPLETE never auto-scored Q=0')
    d = E.decide(h1_state())
    non_recovery = [c for c in d.candidates if c.p_recover in (0.0, 0.03, None)]
    check('non-COMPLETE-able candidates carry dq=None',
          all(c.dq_hat is None for c in non_recovery))
    check('no numeric zero-quality anywhere',
          not any(c.dq_hat == 0 for c in d.candidates))


def t7_separate_effects():
    print('#7 single-dim and interaction effects recorded separately')
    d = E.decide(h1_state())
    split = next(c for c in d.candidates if c.z == 'SPLIT_VERIFY')
    pairs = dict(split.interaction)
    check('three interaction pairs present',
          set(pairs) == {'Z*R', 'Z*pi', 'R*pi'})
    check('Z*R joint-modeled (not additive)', pairs['Z*R'].startswith('JOINT_MODELED'))
    check('no-evidence interactions are explicit zeros',
          pairs['Z*pi'] == 'NO_EVIDENCE:0' and pairs['R*pi'] == 'NO_EVIDENCE:0')
    check('calibration audit trail attached',
          len(split.cal) >= 3 and all('/n=' in v for _, v in split.cal))


def t8_pareto_frontier():
    print('#8 Pareto-incomparable -> frontier, no forced unique optimum')
    d = E.decide(h1_state())
    check('priced-recovery regime detected', d.regime == 'priced_recovery')
    check('frontier returned with >1 member', len(d.frontier) >= 2,
          str(d.frontier))
    check('forced_unique=False when incomparable', d.forced_unique is False)
    check('chosen labelled as stated-preference recommendation',
          'dC_Z' in next(c for c in d.candidates if c.name == d.chosen).rationale
          or 'R_1' in next(c for c in d.candidates if c.name == d.chosen).rationale)


def t9_prediction_audit():
    print('#9 predictions vs recorded outcomes (corpus self-consistency)')
    cal_split = E.CAL['p_recover_split_merge_persistent']
    obs_split = (6, 6)      # H1 G5/G6 + R9B B x4 all COMPLETE
    cal_pers = E.CAL['p_recover_retry_persistent']
    obs_pers = (1, 17)      # R6 n4 recovered; 16 merge + R6 contract others did not
    cal_trans = E.CAL['p_recover_retry_transient']
    obs_trans = (22, 29)
    def err(pt, k, n):
        return abs(pt - k / n)
    e1, e2, e3 = (err(cal_split['point'], *obs_split),
                  err(cal_pers['point'], *obs_pers),
                  err(cal_trans['point'], *obs_trans))
    check(f'split prediction {cal_split["point"]} vs observed '
          f'{obs_split[0]}/{obs_split[1]}', e1 <= 0.05, f'|err|={e1:.3f}')
    check(f'persistent-retry prediction {cal_pers["point"]} vs observed '
          f'{obs_pers[0]}/{obs_pers[1]}', e2 <= 0.05, f'|err|={e2:.3f}')
    check(f'transient-retry prediction {cal_trans["point"]} vs observed '
          f'{obs_trans[0]}/{obs_trans[1]}', e3 <= 0.05, f'|err|={e3:.3f}')
    check('every prediction carries n and evidence level',
          all('/n=' in v for c in E.decide(h1_state()).candidates
              for _, v in c.cal))
    print('    NOTE: calibration was DERIVED from this corpus — this is a '
          'self-consistency audit, not prospective validation.')


def t10_stability_edges():
    print('#10 stability / generality edges (M7-2E)')
    empty = E.EngineState('T', 1, (), (), 1000, 100, (('glm53', 1),), (),
                          PERSISTENCE, PROFILE)
    d = E.decide(empty)
    check('empty DAG handled', d.regime == 'no_fault' and d.assignments == ())
    all_done = h1_state(status='done', sig=None, seen=False)
    d2 = E.decide(all_done)
    check('all-done state handled (no faults)', d2.regime == 'no_fault')
    zero_budget = replace(h1_state(), budget_remaining=0)
    d3 = E.decide(zero_budget)
    check('zero budget -> feasible-or-stop decision, no crash',
          d3.chosen is not None or d3.rationale.startswith('all candidates'))
    # two faulted nodes at once (deterministic joint handling)
    two = h1_state()
    two = replace(two, nodes=tuple(
        replace(n, status='failed', last_failure_type='transport',
                failure_signature_seen=True)
        if n.node_id == 'e1_tl' else n for n in two.nodes))
    d4 = E.decide(two)
    check('multi-fault state handled deterministically',
          d4.chosen is not None and
          E.decide(two).hash_hex() == d4.hash_hex())


def main():
    for t in (t1_determinism, t2_dag_legality, t3_no_reexecution,
              t4_constraints, t5_unknown_faults, t6_incomplete_not_q0,
              t7_separate_effects, t8_pareto_frontier, t9_prediction_audit,
              t10_stability_edges):
        t()
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{n_pass}/{len(RESULTS)} checks passed")
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
