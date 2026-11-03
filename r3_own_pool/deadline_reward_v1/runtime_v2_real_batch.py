"""runtime_v2_real_batch — ONE frozen batch: real node execution for
the 4 Planner dev cases (operator authorized 2026-10-28: <=80
request attempts; ¥0.30 PROPOSED estimated-cost stop threshold, not
a hard cash cap; Flash-only this batch => actual cash ¥0; no retry;
all failures preserved; Silver-only scoring; 60-90-call algorithm
comparison stays HOLD).

Per case: fresh runtime -> evidence materialization (corpus + docs)
-> static allocation (predicted, 0 calls) -> REAL execution of all
nodes (retrieval via providers, LLM nodes via GLM-Flash) -> one
transport-level garbage fault injected after the mid node completes
-> SIMPLE_DYNAMIC recovery WITH task-completion constraint (R =
closure, re-executed really) -> verify_recovery (repair + cache
protection) -> Silver terminal scoring (anchors from retrieved docs).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path('/root/r3_own_pool/deadline_reward_v1')
sys.path.insert(0, str(HERE))
sys.path.insert(0, '/root/r3_own_pool')

import dag_runtime_v1 as R
from dag_runtime_v1 import DAGRuntime, Planner, NodeResult
import runtime_v2_retrieval as RET
from runtime_v2_exec import RealBackend, Meter
from runtime_v2_pipeline import (materialize_evidence, verify_recovery,
                                 terminal_silver)

PICKS = ['A_信息披露变化_r1', 'B_调查至行政处罚_r3',
         'C_并购与关联交易_r2', 'D_重大事件与市场反应_r2']
CAP_CALLS = 80
EST_STOP = 0.30          # proposed estimated-cost stop threshold
OUT = HERE / 'fe_screening_runs' / 'runtime_v2_real_20261028'
OUT.mkdir(parents=True, exist_ok=True)


def est_next_cost(model):
    return 0.0 if model == 'Flash' else 0.012   # frozen rates


def main():
    t0 = time.monotonic()
    meter = Meter()
    provider = RET.LocalCorpusProvider()
    backend = RealBackend(meter, provider, cap_calls=CAP_CALLS,
                          cap_cash=10.0)   # cash never trips (Flash)
    records = []
    ledger = open(OUT / 'BATCH_LEDGER.jsonl', 'w')
    status = 'COMPLETE'
    try:
        for name in PICKS:
            spec = json.loads(
                (HERE / 'fe_screening_runs' / 'planner_v1_20261028' /
                 f'{name}_spec.json').read_text())
            rec = dict(case=name, task_class=spec['task_class'],
                       t_start=round(time.monotonic() - t0, 1))
            docs = materialize_evidence(spec, provider, rec)
            rt = DAGRuntime(spec, backend, spec['constraints'])
            pl = Planner(rt, backend, budget=120)
            _, pi_alloc = pl.greedy_pi(set())        # 0 real calls
            # this ¥0 batch is Flash-only: keep the computed static
            # allocation on record but clamp execution to Flash
            pi_static = {n: 'Flash' for n in pi_alloc}
            rec['static_alloc_clamped'] = dict(pi_alloc)
            order = R.topo_order(spec)
            fault = order[len(order) // 2]
            rec['fault_injected_at'] = fault
            natural = []
            # ---- real execution to fault point ----
            for nid in order:
                node = [n for n in spec['nodes'] if n['id'] == nid][0]
                if meter.calls >= CAP_CALLS:
                    raise RuntimeError('batch call cap')
                if meter.cash + est_next_cost(
                        pi_static.get(nid, 'Flash')) > EST_STOP:
                    raise RuntimeError('est-cost stop threshold')
                node2 = dict(node)
                if node.get('evidence') and node['evidence'] in docs:
                    node2['_doc_text'] = docs[
                        node['evidence']]['text'][:4000]
                res = rt.execute_node(node2,
                                      pi_static.get(nid, 'Flash'))
                if res.status == 'bad':
                    natural.append(nid)
                if nid == fault:
                    r = rt.state[nid]
                    rt.state[nid] = NodeResult(
                        'bad', q=R.Q_GARBAGE, output_text='',
                        tokens=r.tokens, lat=r.lat, cash=r.cash,
                        model=r.model, source='FAULT_INJECTED')
                    break
            rec['natural_contract_failures'] = natural
            bad_before = sorted(n for n, r in rt.state.items()
                                if r.status == 'bad')
            # ---- recovery: SIMPLE_DYNAMIC + completion constraint ----
            import copy
            rt2 = DAGRuntime(spec, backend, spec['constraints'])
            rt2.state = dict(rt.state)
            rt2.spent = dict(rt.spent)
            Rset = set()
            nodes = {n['id']: n for n in spec['nodes']}
            for b in bad_before:
                Rset |= R.closure_of(spec, b)
            for nid in R.topo_order(spec):
                if meter.calls >= CAP_CALLS:
                    raise RuntimeError('batch call cap')
                node = nodes[nid]
                st = rt2.state.get(nid)
                if nid in Rset and (st is None or st.status == 'bad'):
                    if st is not None:
                        rt2.state.pop(nid)
                    node2 = dict(node)
                    if node.get('evidence') and \
                            node['evidence'] in docs:
                        node2['_doc_text'] = docs[
                            node['evidence']]['text'][:4000]
                    rt2.execute_node(node2, pi_static.get(nid, 'Flash'))
                elif st is None:
                    node2 = dict(node)
                    if node.get('evidence') and \
                            node['evidence'] in docs:
                        node2['_doc_text'] = docs[
                            node['evidence']]['text'][:4000]
                    rt2.execute_node(node2,
                                     pi_static.get(nid, 'Flash'))
            ok, probs = verify_recovery(spec, rt, rt2, bad_before, Rset)
            rec.update(recovered=ok, problems=probs[:4],
                       R=sorted(Rset),
                       term=terminal_silver(rt2.spec, rt2, docs),
                       calls_used=meter.calls,
                       real_sources={n: r.source
                                     for n, r in rt2.state.items()})
            # preserve all raw outputs
            (OUT / f'{name}_outputs.json').write_text(json.dumps(
                {n: dict(source=r.source, status=r.status,
                         model=r.model, tokens=r.tokens,
                         text=r.output_text[:2500])
                 for n, r in rt2.state.items()},
                ensure_ascii=False, indent=1))
            records.append(rec)
            ledger.write(json.dumps(rec, ensure_ascii=False) + '\n')
            ledger.flush()
            print(json.dumps(
                dict(case=name, recovered=ok,
                     silver=rec['term']['silver_q'],
                     anchors=rec['term']['anchors'],
                     rel=rec['term']['reliability'],
                     calls=meter.calls), ensure_ascii=False),
                flush=True)
    except BaseException as e:
        status = f'INCOMPLETE: {e!r}'
        print(status, 'calls=', meter.calls, 'cash=', meter.cash)
    mny = round(meter.cash, 5)
    summary = dict(status=status, calls=meter.calls, cash=mny,
                   tokens=meter.tokens,
                   wall_s=round(time.monotonic() - t0, 1),
                   records=records)
    (OUT / 'RUNTIME_V2_REAL_RESULTS.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1))
    print(f'FINAL: {status} calls={meter.calls} cash={mny} '
          f'tokens={meter.tokens}')


if __name__ == '__main__':
    main()
