#!/usr/bin/env python3
"""V3-VALIDATION: zero-call test suite for the DA-JS v3 controller.

Scenarios built from REAL batch evidence (QCL_TABLE_V3, E03 doc-id incident,
persistent/transient fault cells). Checks: policy selection, boundary
conditions, dependency legality, budget protection, E dual-gate, posterior
evolution, audit completeness. No API calls.
"""
import json
from da_js_v3 import (State, Node, BetaPosterior, Policy, decide,
                      e_trigger_gate, e_adoption_gate, update_after_action,
                      q_hat_none)

PASS = FAIL = 0


def check(name, cond, detail=''):
    global PASS, FAIL
    tag = 'PASS' if cond else 'FAIL'
    PASS += cond
    FAIL += not cond
    print(f'[{tag}] {name}{"  <- " + detail if detail and not cond else ""}')


def healthy_state(D=2400, calls=90, task='E04_r1', zx=True):
    return State(task=task, task_profile=dict(zx_comparable=zx),
                 G={'ext_doc1': Node('ext_doc1', 'extract', 'deepseek'),
                    'store': Node('store', 'store', 'code'),
                    'verify': Node('verify', 'verify', 'qwen'),
                    'report': Node('report', 'report', 'qwen')},
                 H={},
                 faulted=None,
                 B=dict(calls=calls, tokens=500000, yuan=3.0),
                 D=D,
                 M=dict(genuinely_deficient_branches=[]))


def faulted_state(hint='unknown', alpha=1, beta=1, D=2400, calls=90):
    s = healthy_state(D=D, calls=calls)
    s.faulted = ('report', hint)
    s.G['report'].status = 'faulted'
    s.H[('report', 'qwen')] = BetaPosterior(alpha, beta)
    return s


def main():
    bq = q_hat_none('E04_r1')

    # 1 healthy + ample resources -> proactive Zx
    d = decide(healthy_state())
    check('healthy+ample -> Zx (proactive upgrade)', d['selected'] == 'Zx',
          str(d['selected']))
    zx_cand = next(c for c in d['candidates'] if c['action'] == 'Zx')
    check('Zx Q_hat = baseline + v3.2 conservative dQ (0.091)',
          abs(zx_cand['Q'] - (bq + 0.091)) < 1e-9 and 'v3.2 formula' in zx_cand['basis'])

    # 2 deadline boundary: 5-doc Zx conservative 453s vs D=300 -> vetoed
    s5d = healthy_state(D=300)
    s5d.task_profile['docs_n'] = 5
    d = decide(s5d)
    check('healthy 5-doc + D=300 -> Zx vetoed (scaled latency 453s) -> NONE',
          d['selected'] == 'NONE', str(d['selected']))
    check('veto reason recorded (deadline)',
          any('deadline' in c.get('veto', '') for c in d['candidates']))
    # 2b ceiling gate: saturated transport -> Zx withheld
    sc = healthy_state()
    sc.task_profile['transport_saturated'] = True
    d = decide(sc)
    check('ceiling gate: saturated task -> Zx withheld, NONE selected',
          d['selected'] == 'NONE' and
          any(c['action'] == 'Zx' and 'ceiling' in c.get('veto', '') for c in d['candidates']),
          str(d['selected']))

    # 3 budget boundary: B=5 calls -> Zx vetoed
    d = decide(healthy_state(calls=5))
    check('healthy+B=5c -> Zx vetoed -> NONE', d['selected'] == 'NONE')

    # 4 budget exhausted -> HALT protection
    s = healthy_state(calls=0)
    s.B['tokens'] = 0
    d = decide(s)
    check('B=0 -> NONE survives (zero-cost) or HALT', d['selected'] in ('NONE', 'HALT'))

    # 5 v3.1 conditional boundary: transient/unknown -> R probe FIRST
    d = decide(faulted_state(hint='transient', alpha=1, beta=1))
    check('transient hint -> R probe first', d['selected'] == 'R', str(d['selected']))
    d = decide(faulted_state(hint='unknown', alpha=1, beta=1))
    check('unknown p_t=0.5 -> R probe first', d['selected'] == 'R', str(d['selected']))
    s5 = faulted_state(hint='transient', alpha=1, beta=1)
    s5.G['report'].agents = ('qwen',)   # pool restriction: no alternative
    d = decide(s5)
    check('pool-restricted transient -> R (sole legal recovery)',
          d['selected'] == 'R', str(d['selected']))

    # 6 persistent-likely posterior (p<1/3) -> pi direct, R not selected
    d = decide(faulted_state(hint='persistent', alpha=1, beta=3))
    check('p_t=0.25 -> pi direct (skip doomed R)', d['selected'] == 'pi', str(d['selected']))

    # 7 feedback: R fails (unknown class) -> posterior drops -> escalation to pi
    s = faulted_state(hint='unknown', alpha=2, beta=1)   # p=0.67 -> R first
    d1 = decide(s)
    check('p_t=0.67 unknown -> R first', d1['selected'] == 'R', str(d1['selected']))
    s = update_after_action(s, 'R', dict(restored=False))
    p_after = s.H[('report', 'qwen')].p_transient()
    d2 = decide(s)
    check(f'R failed -> posterior {p_after:.2f} -> escalate to pi', d2['selected'] == 'pi',
          str(d2['selected']))
    # 7b pool-restricted R failure -> honest re-decision (no pi available)
    s = faulted_state(hint='transient', alpha=2, beta=1)
    s.G['report'].agents = ('qwen',)
    s = update_after_action(s, 'R', dict(restored=False))
    d2b = decide(s)
    check('pool-restricted R failed -> honest re-decision (R/HALT/NONE)',
          d2b['selected'] in ('R', 'HALT', 'NONE'), str(d2b['selected']))

    # 8 R succeeds -> posterior rises, fault clears
    s = faulted_state(hint='unknown')
    s = update_after_action(s, 'R', dict(restored=True))
    check('R ok -> fault cleared, healthy again', s.faulted is None)

    # 8b Zx gate-1: non-comparable task structure -> Zx withheld -> NONE
    d = decide(healthy_state(task='SINGLE_DOC_TASK', zx=False))
    check('zx gate-1: non-comparable task -> no Zx, NONE selected',
          d['selected'] == 'NONE' and
          any(c['action'] == 'Zx' and 'gate-1' in c.get('veto', '') for c in d['candidates']),
          str(d['selected']))

    # 9 E trigger gate: doc-id-only anomaly is NOT a trigger (E03 incident)
    bm_artifact = {'D1': dict(n=23, prov=0.0, corrected_prov=1.0)}   # raw prov 0, corrected 1.0
    check('doc-id artifact does NOT trigger E',
          e_trigger_gate(bm_artifact) == [])
    bm_real = {'D1': dict(n=8, corrected_prov=0.9)}                  # genuinely thin
    check('genuinely thin branch DOES trigger E', e_trigger_gate(bm_real) == ['D1'])

    # 10 E adoption gate: empty reroll rejected; thin reroll rejected
    ok, why = e_adoption_gate([dict(v='a') for _ in range(20)], [])
    check('adoption gate rejects empty reroll', not ok, why)
    ok, why = e_adoption_gate([dict(v='a') for _ in range(20)], [dict(v='b')] * 3)
    check('adoption gate rejects much-thinner reroll', not ok, why)
    ok, why = e_adoption_gate([dict(v='a') for _ in range(20)], [dict(v='b')] * 18)
    check('adoption gate accepts healthy reroll', ok, why)

    # 11 E candidate withholds positive expectation (discipline #2)
    s = healthy_state()
    s.M = dict(genuinely_deficient_branches=['ext_doc1'])
    pol = Policy()
    cands = pol.generate(s, bq)
    e_c = next(c for c in cands if c.action == 'E')
    check('E Q_hat = baseline (no unverified positive)',
          abs(e_c.Q_hat - bq) < 1e-9 and 'withheld' in e_c.basis)

    # 12 audit completeness: every candidate carries basis; vetoes carry reasons
    d = decide(faulted_state(hint='persistent', alpha=1, beta=3))
    check('audit has all candidates with basis',
          all('basis' in c for c in d['candidates']) and len(d['candidates']) >= 2)

    # 13 dependency legality: pi target agent differs from current
    d = decide(faulted_state(hint='persistent', alpha=1, beta=3))
    pi_c = next(c for c in d['candidates'] if c['action'] == 'pi')
    check('pi plan reassigns to a DIFFERENT agent (audit carries plan)',
          pi_c['plan']['to'] == 'deepseek')

    print(f'\n{PASS}/{PASS + FAIL} passed')
    return FAIL == 0


if __name__ == '__main__':
    raise SystemExit(0 if main() else 1)
