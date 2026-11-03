"""core_experiment_v1 — THE one core experiment driver (frozen).
Implements UNIFIED_INTEGRATION_PREP exactly. Modes:

  DRY_RUN=1  (zero-call): ReplayBackend; validates orchestration,
             gates, candidate construction, recovery execution,
             scoring and ledgering — protects the authorized budget
             from script crashes. NOT a benefit result.
  CORE_EXP_GO=1 + DRY_RUN unset: RealBackend (GLM-Flash), caps:
             <=100 request attempts, Flash-only (DS needs separate
             amendment), fail-stop, no retry. REQUIRES the operator's
             separate numeric authorization (not yet given).

Design per prep: 3 tasks (A/B/D planner specs) x same-anomaly-state
pairing x 6 policies (Static/SimpleDyn/Ronly/Pionly/JointRpi/
JointZRpi with IDENTITY in-enumeration + z_ops_v2 candidates incl.
SUBSTITUTE_EV under the evidence-unavailability scenario on task B).
Q-hat/Q wall: decisions read PROFILE only; terminal scored by the
frozen doc-anchored Silver scorer AFTER execution.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path('/root/r3_own_pool/deadline_reward_v1')
sys.path.insert(0, str(HERE))
sys.path.insert(0, '/root/r3_own_pool')

import dag_runtime_v1 as R
from dag_runtime_v1 import DAGRuntime, Planner, NodeResult
from runtime_v2_exec import ReplayBackend, RealBackend, Meter
from runtime_v2_retrieval import LocalCorpusProvider
from runtime_v2_pipeline import (materialize_evidence, verify_recovery,
                                 terminal_silver)
from stage_c_v1 import legal_R_candidates, make_state
from z_ops_v2 import z_options_v2

TASKS = ['A_信息披露变化_r1', 'D_重大事件与市场反应_r2',
         'YUANDAO']
YUANDAO_QUESTION = ('复盘元道通信(301139)欺诈发行案：2019-2021年虚增营业'
                    '收入的逐年金额、非法所募资金与最终罚款金额、责任主体'
                    '及其角色、从立案到行政处罚决定的时间线，核验关键事实'
                    '与处罚决定书一致。')
YUANDAO_DOCS = {                # frozen pool doc_ids (load_docs 'ydt')
    'D1_E03-yuandao_2026-05-08': 'ydt_d1',
    'D3_E03-yuandao_2026-08-29': 'ydt_d3'}
POLICIES = ['STATIC', 'SIMPLE_DYN', 'R_ONLY', 'PI_ONLY', 'JOINT_R_PI',
            'JOINT_Z_R_PI']
CAP_CALLS = 130
DRY = os.environ.get('DRY_RUN') == '1'
OUT = HERE / ('fe_screening_runs/core_exp_v1_dryrun'
              if DRY else 'fe_screening_runs/core_exp_v1')


def greedy_pi_for(rt, Rset, budget):
    todo = [n for n in R.topo_order(rt.spec)
            if n not in rt.state or n in Rset]
    pi = {n: 'Flash' for n in todo}
    pl = Planner(rt, rt.adapter, budget=budget)
    _orig_pred = pl.pred_q

    def pred_q_aware(node, model):
        if node.get('evidence_unavailable'):
            return R.Q_GARBAGE      # doc missing => predicted garbage
        return _orig_pred(node, model)
    pl.pred_q = pred_q_aware
    cur = pl.evaluate(set(Rset), pi)
    ev = pl.evals
    improved = True
    while improved and ev < budget:
        improved = False
        for n in todo:
            bm, bv = pi[n], cur
            for m in ('DS', 'Qwen'):
                pi2 = dict(pi)
                pi2[n] = m
                v = pl.evaluate(set(Rset), pi2)
                ev += 1
                if v > bv + 1e-12:
                    bm, bv = m, v
            if bm != pi[n]:
                pi[n] = bm
                cur = bv
                improved = True
    return cur, pi, ev


def act(policy, rt, ctx=None):
    """completion-constrained R + TERMINATE + full pi; Z options for
    the two Joint policies with IDENTITY always in enumeration."""
    cands, bad = legal_R_candidates(rt.spec, rt.state)
    nodes = {n['id']: n for n in rt.spec['nodes']}
    w = 1.0 / len(nodes)
    q_term = sum(w * rt.state[n].q for n in rt.state)
    best = dict(z='IDENTITY', R=None, pi={}, terminate=True,
                v=q_term - 0.5 * rt.spent['tokens'] / 60000.0
                - max(0.0, rt.spent['lat'] - rt.D) / rt.D)
    if not bad:
        v, pi, ev = greedy_pi_for(rt, set(), 40)
        if v > best['v']:
            best = dict(z='IDENTITY', R=[], pi=pi, terminate=False,
                        v=v)
        return best
    pool = [('IDENTITY', rt.spec)]
    if policy == 'JOINT_Z_R_PI':
        pool += [(zn, zs) for zn, zs in z_options_v2(rt.spec, ctx)
                 if zn != 'IDENTITY']
    for zname, zspec in pool:
        trial = DAGRuntime(zspec, rt.adapter, dict(D=rt.D,
                                                   Ccap=rt.Ccap))
        trial.state = dict(rt.state)
        trial.spent = dict(rt.spent)
        for Rset in legal_R_candidates(zspec, rt.state)[0]:
            if policy == 'STATIC':
                v, pi, ev = greedy_pi_for(trial, Rset, 1)
            elif policy in ('SIMPLE_DYN', 'R_ONLY'):
                v, pi, ev = greedy_pi_for(trial, Rset, 1)
            else:
                v, pi, ev = greedy_pi_for(trial, Rset, 80)
            if v > best['v'] + 1e-12:
                best = dict(z=zname, R=sorted(Rset), pi=pi,
                            terminate=False, v=v)
    return best


def load_spec(name, backend, meter):
    if name != 'YUANDAO':
        return json.loads(
            (HERE / 'fe_screening_runs' / 'planner_v1_20261028' /
             f'{name}_spec.json').read_text())
    if DRY:
        # placeholder for ORCHESTRATION validation only — clearly NOT
        # a planner product; the real run plans first (1 Flash call)
        return dict(
            task_id='YUANDAO_PLACEHOLDER_DRY_ONLY',
            task_class='欺诈发行复盘(占位,非规划器产物)',
            evidence=['ydt_d1', 'ydt_d3'],
            constraints=dict(D=140.0, Ccap=0.02),
            nodes=[
                dict(id='ext1', role='extraction', inputs=[],
                     contract=dict(produces=['facts1']),
                     evidence='ydt_d1'),
                dict(id='ext2', role='extraction', inputs=[],
                     contract=dict(produces=['facts2']),
                     evidence='ydt_d3'),
                dict(id='mrg', role='merge', inputs=['ext1', 'ext2'],
                     contract=dict(produces=['merged'],
                                   requires=['facts1', 'facts2'])),
                dict(id='tl', role='timeline', inputs=['mrg'],
                     contract=dict(produces=['dates'],
                                   requires=['merged'])),
                dict(id='xc', role='cross_check', inputs=['tl'],
                     contract=dict(produces=['checked'],
                                   requires=['dates'])),
                dict(id='sink', role='synthesis', inputs=['xc'],
                     contract=dict(produces=['report'],
                                   requires=['checked']))])
    # real run: 1 planner call inside the batch (counted, Flash ¥0)
    # HARD GATE (added after accidental import-triggered call on
    # 2026-10-28: 1 GLM-Flash call, ¥0, disclosed): the real planning
    # path can never execute without the batch env gate.
    if os.environ.get('CORE_EXP_GO') != '1':
        raise PermissionError('load_spec real path requires '
                              'CORE_EXP_GO=1')
    import dag_planner_v1 as P
    prompt = P.PROMPT.format(
        question=YUANDAO_QUESTION,
        sources=json.dumps(
            [dict(doc_id=v, title=k, event='元道通信(301139)欺诈发行案')
             for k, v in YUANDAO_DOCS.items()], ensure_ascii=False),
        D=140, Ccap=0.02, roles=P.ROLES_DOC)
    from r2fix_runner import call_ds, load_env_creds
    o = call_ds(prompt, load_env_creds(), max_out_tokens=3072)
    meter.calls += 1                      # batch-counted (envelope)
    meter.tokens += o['tokens_in'] + o['tokens_out']
    meter.cash += float(o.get('cash_cny', 0.0) or 0.0)
    meter.ledger(dict(backend='real_planner', node='YUANDAO:plan',
                      contract_ok=True,
                      tokens=o['tokens_in'] + o['tokens_out'],
                      lat=round(o['latency_s'], 2), cash=0.0))
    spec, why = P.parse_spec(o['answer'])
    ok, reasons = R.check_legality(spec)
    if not ok:
        raise RuntimeError(f'yuandao planner spec illegal: {reasons}')
    return spec


def run_task(name, backend, provider, docs_all, ledger, meter):
    spec = load_spec(name, backend, meter)
    rec = dict(task=name)
    docs = materialize_evidence(spec, provider, rec)

    def node_with_doc(node):
        n2 = dict(node)
        if node.get('evidence') and node['evidence'] in docs:
            n2['_doc_text'] = docs[node['evidence']]['text'][:4000]
        return n2

    order = R.topo_order(spec)
    ctx = None
    ev_failed = None
    if name == 'YUANDAO':
        # P2 scenario: D1 (early announcement) retrieval fails at
        # runtime; legal alternative = D3 final penalty decision
        # (majority 0.90 + zero genuine item loss, verified frozen)
        ev_failed = 'ydt_d1'
        provider.docs.pop(ev_failed, None)
        docs.pop(ev_failed, None)
        ctx = dict(failed_doc=ev_failed,
                   alt_candidates=['ydt_d3'],
                   corpus=dict(docs_all))
        for n in spec['nodes']:
            if n.get('evidence') == ev_failed:
                n['evidence_unavailable'] = True
        rec['evidence_failure_injected'] = ev_failed
    elif name.startswith('B') and 'zeda_tj_lin_ying' in docs_all:
        # evidence-unavailability scenario: retrieval of the bound
        # doc fails AT RUNTIME when its node wants it -> that node
        # fails; decision layer knows (retrieval ledger)
        ev_failed = 'zeda_csrc_penalty_2024_kangda'
        provider.docs.pop(ev_failed, None)
        docs.pop(ev_failed, None)
        ctx = dict(failed_doc=ev_failed,
                   alt_candidates=['zeda_csrc_penalty_2023_29',
                                   'zeda_tj_lin_ying'],
                   corpus=dict(docs_all))
        for n in spec['nodes']:
            if n.get('evidence') == ev_failed:
                n['evidence_unavailable'] = True
        rec['evidence_failure_injected'] = ev_failed
    # fault position: the evidence-starved node itself (B), else mid
    if ev_failed:
        fault = [n['id'] for n in spec['nodes']
                 if n.get('evidence') == ev_failed][0]
    else:
        fault = order[len(order) // 2]
    rt = DAGRuntime(spec, backend, spec['constraints'])
    for nid in order:
        node = [n for n in spec['nodes'] if n['id'] == nid][0]
        rt.execute_node(node_with_doc(node), 'Flash')
        if nid == fault:
            r = rt.state[nid]
            rt.state[nid] = NodeResult(
                'bad', q=R.Q_GARBAGE, output_text='', tokens=r.tokens,
                lat=r.lat, cash=r.cash, model=r.model,
                source=('EVIDENCE_UNAVAILABLE' if ev_failed
                        else 'FAULT_INJECTED'))
            break
    bad_before = [n for n, r in rt.state.items() if r.status == 'bad']
    rec['fault'] = bad_before
    rows = []
    for pol in POLICIES:
        rt2 = DAGRuntime(spec, backend, spec['constraints'])
        rt2.state = dict(rt.state)
        rt2.spent = dict(rt.spent)
        a = act(pol, rt2, ctx)
        z, Rset, pi = a['z'], set(a['R'] or []), a['pi']
        if pol == 'STATIC':
            z, Rset = 'IDENTITY', set()      # no replan by definition
        if z != 'IDENTITY':
            zmap = dict(z_options_v2(rt2.spec, ctx))
            okz, whyz = rt2.apply_z(zmap[z])
            if not okz:
                rows.append(dict(policy=pol, z_apply_failed=whyz))
                continue
        nodes = {n['id']: n for n in rt2.spec['nodes']}
        if not a['terminate']:
            for nid in R.topo_order(rt2.spec):
                node = nodes[nid]
                st = rt2.state.get(nid)
                if nid in Rset and (st is None or st.status == 'bad'):
                    if st is not None:
                        rt2.state.pop(nid)
                    rt2.execute_node(node_with_doc(node), 'Flash')
                elif st is None:
                    rt2.execute_node(node_with_doc(node), 'Flash')
        ok, probs = verify_recovery(rt2.spec, rt, rt2, bad_before, Rset)
        rows.append(dict(
            policy=pol, z=z, terminate=a['terminate'],
            R=sorted(Rset), recovered=ok, problems=probs[:3],
            term=terminal_silver(rt2.spec, rt2, docs)))
        ledger.write(json.dumps(rows[-1] | dict(task=name),
                                ensure_ascii=False) + '\n')
        ledger.flush()
    rec['policies'] = rows
    rec['calls'] = meter.calls
    return rec


def main():
    t0 = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    meter = Meter()
    provider = LocalCorpusProvider()
    if DRY:
        backend = ReplayBackend(meter, provider)
    else:
        if os.environ.get('CORE_EXP_GO') != '1':
            raise PermissionError('requires CORE_EXP_GO=1')
        from auth_gate import effective_caps
        CAPS = effective_caps('core_exp_v1', CAP_CALLS, 10_000_000)
        backend = RealBackend(meter, provider,
                              cap_calls=CAPS['max_calls'],
                              cap_cash=10.0)
    docs_all = dict(provider.docs)
    ledger = open(OUT / 'CORE_LEDGER.jsonl', 'w')
    records = []
    status = 'COMPLETE'
    try:
        for name in TASKS:
            if not DRY and meter.calls >= CAPS['max_calls']:
                raise RuntimeError('cap')
            records.append(run_task(name, backend, provider, docs_all,
                                    ledger, meter))
            print(f'[{name}] calls={meter.calls}', flush=True)
    except BaseException as e:
        status = f'INCOMPLETE: {e!r}'
    summary = dict(mode='DRY_RUN' if DRY else 'REAL', status=status,
                   calls=meter.calls, cash=round(meter.cash, 5),
                   tokens=meter.tokens,
                   wall_s=round(time.monotonic() - t0, 1),
                   records=records)
    (OUT / 'CORE_EXP_RESULTS.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1))
    print('FINAL', status, 'calls=', meter.calls)


if __name__ == '__main__':
    main()
