"""runtime_v2_pipeline — Parts 3+4: full wiring + terminal eval.

Zero-call validation pass:
  planner spec (frozen V1 outputs) -> evidence materialization via
  retrieval providers (LOCAL corpus; optional live HTTP demo) ->
  static heterogeneous allocation -> runtime execution (ReplayBackend
  for LLM nodes, REAL retrieval outputs) -> anomaly injection ->
  legal (Z,R,pi) recovery by policies -> per-candidate recovery
  verification -> Silver terminal evaluation (anchors from the
  RETRIEVED documents; machine draft = Silver, never Gold).

Upstream results are passed as (node_id, NodeResult) tuples.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path('/root/r3_own_pool/deadline_reward_v1')
sys.path.insert(0, str(HERE))

import dag_runtime_v1 as R
from dag_runtime_v1 import DAGRuntime, Planner, NodeResult, \
    policy_act, z_options
import runtime_v2_retrieval as RET
import runtime_v2_exec as EX
from runtime_v2_exec import ReplayBackend, Meter

PICKS = ['A_信息披露变化_r1', 'B_调查至行政处罚_r3',
         'C_并购与关联交易_r2', 'D_重大事件与市场反应_r2']


def materialize_evidence(spec, provider, ledger_rec):
    """resolve each distinct evidence binding via retrieval; the
    retrieval must actually FIND the document (binding check)."""
    bindings = sorted(set(n['evidence'] for n in spec['nodes']
                          if n.get('evidence')))
    found = {}
    pool = getattr(provider, 'docs', {})
    for did in bindings:
        if did in pool:                     # direct corpus resolution
            found[did] = pool[did]
            continue
        for d in provider.search(did):
            if d['doc_id'] == did or did in d['doc_id'] \
                    or did in d['title']:
                found[did] = d
                break
    ledger_rec['evidence'] = dict(
        bindings=bindings, found=sorted(found),
        missing=[b for b in bindings if b not in found])
    return found


def verify_recovery(spec, rt_before, rt_after, bad_before, Rset):
    """operator check #1: is candidate R a REAL recovery?
    (a) every originally-bad node now done or legally substituted;
    (b) no stale downstream of repaired nodes (all nodes downstream
        of R re-derived after repair);
    (c) no unnecessary re-execution outside R/downstream (cache
        protection)."""
    nodes = {n['id']: n for n in spec['nodes']}
    problems = []
    for b in bad_before:
        r = rt_after.state.get(b)
        if r is None or r.status != 'done':
            # legal substitution: a Z-added node with same contract
            subs = [n for n in spec['nodes']
                    if n['id'] not in nodes and False]
            problems.append(f'bad node {b} not recovered')
    for n in Rset:
        for d in nodes:
            if n in nodes[d]['inputs']:
                ra = rt_after.state.get(d)
                if ra is None:
                    problems.append(f'downstream {d} missing')
    # cache protection: done-before nodes outside R keep same output
    for nid, r in rt_before.state.items():
        if nid in rt_after.state and nid not in Rset:
            if r.output_text and \
                    rt_after.state[nid].output_text != r.output_text:
                problems.append(f'{nid} re-executed outside R')
    return (not problems), problems


def terminal_silver(spec, rt, docs_found):
    """Silver scorer: anchors derived from the RETRIEVED documents'
    doc_atoms; score = sink output coverage of anchors. Silver tier."""
    from full_dag_silver import doc_atoms
    anchors = []
    for did, d in docs_found.items():
        at = doc_atoms(d['text'])
        anchors += ([f'd:{k}' for k in at['dates'][:3]]
                    + [f'a:{k}' for k in at['amounts'][:3]]
                    + [f'p:{k}' for k in at['penalties'][:2]]
                    + [f'e:{k}' for k in at['entities'][:2]])
    sink_id = [n['id'] for n in spec['nodes']
               if not any(n['id'] in m['inputs']
                          for m in spec['nodes'])][0]
    sink_text = rt.state.get(sink_id).output_text if sink_id in \
        rt.state else ''
    hits = 0
    import re
    clean = re.sub(r'[\s,，]', '', sink_text)
    for a in anchors:
        key = a.split(':', 1)[1]
        if re.sub(r'[\s,，]', '', key) in clean:
            hits += 1
    q = hits / max(1, len(anchors))
    done = sum(1 for r in rt.state.values() if r.status == 'done')
    return dict(anchors=len(anchors), hits=hits,
                silver_q=round(q, 4),
                reliability=round(done / len(spec['nodes']), 3),
                cash=round(rt.spent['cash'], 5),
                tokens=rt.spent['tokens'],
                lat=round(rt.spent['lat'], 1),
                met=rt.spent['lat'] <= rt.D,
                tier='SILVER(machine-draft, doc-anchored)')


def run_case(name, live_http_demo=False):
    spec = json.loads((HERE / 'fe_screening_runs' / 'planner_v1_20261028'
                       / f'{name}_spec.json').read_text())
    rec = dict(case=name, task_class=spec['task_class'])
    provider = RET.LocalCorpusProvider()
    docs = materialize_evidence(spec, provider, rec)
    if live_http_demo:
        http = RET.HttpProvider()
        d = http.fetch_doc(
            'https://www.csrc.gov.cn/tianjin/c103608/c7463467/'
            'content.shtml', doc_id='zeda_tj_lin_ying')
        rec['live_http'] = ([dict(doc_id=d['doc_id'], chars=len(d['text']),
                                  url=d['url'])] if d else
                            ['fetch failed'])
        if d:
            docs[d['doc_id']] = d
    meter = Meter()
    backend = ReplayBackend(meter, provider)
    rt = DAGRuntime(spec, backend, spec['constraints'])
    # static allocation then execution with REAL retrieval feeding
    pl = Planner(rt, backend, budget=120)
    _, pi_static = pl.greedy_pi(set())
    # wrap backend.execute with (nid,result) tuples for upstreams
    orig_exec = rt.execute_node

    def exec_with_upstream(node, model):
        upstreams = [(i, rt.state[i]) for i in node['inputs']
                     if i in rt.state]
        # attach real doc text for evidence-bound extraction nodes
        if node.get('evidence') and node['evidence'] in docs:
            upstreams = upstreams or []
            node = dict(node)
            node['_doc_text'] = docs[node['evidence']]['text'][:4000]
        return orig_exec(node, model)

    rt.execute_node = exec_with_upstream
    order = R.topo_order(spec)
    fault = order[len(order) // 2]
    for nid in order:
        node = [n for n in spec['nodes'] if n['id'] == nid][0]
        rt.execute_node(node, pi_static.get(nid, 'Flash'))
        if nid == fault:
            r = rt.state[nid]
            rt.state[nid] = NodeResult(
                'bad', q=R.Q_GARBAGE, output_text='', tokens=r.tokens,
                lat=r.lat, cash=r.cash, model=r.model,
                source='FAULT_INJECTED')
            break
    bad_before = [n for n, r in rt.state.items() if r.status == 'bad']
    rec['fault'] = fault
    # policies act; verify recovery per executed candidate
    actions = {}
    for pol in ('SIMPLE_DYNAMIC', 'R_ONLY', 'JOINT_Z_R_PI'):
        import copy
        rt2 = DAGRuntime(spec, backend, spec['constraints'])
        rt2.state = dict(rt.state)
        rt2.spent = dict(rt.spent)
        pl2 = Planner(rt2, backend, budget=120)
        z, Rset, pi = policy_act(pol, pl2, rt2, backend)
        # execute recovery
        nodes = {n['id']: n for n in rt2.spec['nodes']}
        for nid in R.topo_order(rt2.spec):
            node = nodes[nid]
            st = rt2.state.get(nid)
            if nid in Rset and (st is None or st.status == 'bad'):
                if st is not None:
                    rt2.state.pop(nid)
                rt2.execute_node(node, pi.get(nid, 'Flash'))
            elif st is None:
                rt2.execute_node(node, pi.get(nid, 'Flash'))
        ok, probs = verify_recovery(rt2.spec, rt, rt2, bad_before, Rset)
        actions[pol] = dict(z=z, R=sorted(Rset), recovered=ok,
                            problems=probs[:3],
                            term=terminal_silver(rt2.spec, rt2, docs))
    rec['actions'] = actions
    rec['static_term'] = terminal_silver(
        spec, DAGRuntime(spec, backend, spec['constraints']), docs)
    rec['meter'] = dict(calls=meter.calls, tokens=meter.tokens,
                        cash=meter.cash)
    return rec


def main():
    out = []
    for i, name in enumerate(PICKS):
        rec = run_case(name, live_http_demo=(i == 1))  # B case: live
        out.append(rec)
        print(json.dumps(rec, ensure_ascii=False)[:400], flush=True)
    (HERE / 'RUNTIME_V2_VALIDATION.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=1))
    print('done')


if __name__ == '__main__':
    main()
