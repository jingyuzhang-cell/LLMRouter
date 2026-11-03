"""diag_micro_v1 — authorized micro-diagnostic batch (operator '授权'
2026-10-28, in response to option (a)): <=6 real GLM-Flash calls, ¥0,
fail-stop, outputs saved, tiered contract gate. Purpose: identify the
concrete failure form behind the 140-call batch's ~69% contract-failure
rate. Production prompt path (core_experiment node_with_doc +
RealBackend._build_prompt)."""
import json
import os
import sys
from pathlib import Path

HERE = Path('/root/r3_own_pool/deadline_reward_v1')
sys.path.insert(0, str(HERE))
sys.path.insert(0, '/root/r3_own_pool')

import dag_runtime_v1 as R
from dag_runtime_v1 import DAGRuntime
from runtime_v2_exec import RealBackend, Meter
from runtime_v2_retrieval import LocalCorpusProvider
from runtime_v2_pipeline import materialize_evidence

CAP = 6
OUT = HERE / 'fe_screening_runs/diag_micro_20261028'
OUT.mkdir(parents=True, exist_ok=True)

if os.environ.get('MICRO_DIAG_GO') != '1':
    raise PermissionError('requires MICRO_DIAG_GO=1')
from auth_gate import require as _auth_require
_auth_require('diag_micro_v1')   # structured scope mandatory


def main():
    meter = Meter()
    provider = LocalCorpusProvider()
    backend = RealBackend(meter, provider, cap_calls=CAP, cap_cash=10.0)
    spec = json.loads((HERE / 'fe_screening_runs' / 'planner_v1_20261028'
                       / 'A_信息披露变化_r1_spec.json').read_text())
    rec = {}
    docs = materialize_evidence(spec, provider, rec)
    rt = DAGRuntime(spec, backend, spec['constraints'])
    nodes = {n['id']: n for n in spec['nodes']}
    order = R.topo_order(spec)
    results = []
    for nid in order[:6]:        # n1..n6: extraction root + branches + check
        if meter.calls >= CAP:
            break
        node = dict(nodes[nid])
        if node.get('evidence') and node['evidence'] in docs:
            node['_doc_text'] = docs[node['evidence']]['text'][:4000]
        res = rt.execute_node(node, 'Flash')
        results.append(dict(
            node=nid, role=node['role'],
            produces=node['contract']['produces'],
            status=res.status, model=res.model,
            tokens=res.tokens, lat=res.lat,
            output_head=res.output_text[:400]))
        print(json.dumps(results[-1] | dict(
            output_head=results[-1]['output_head'][:120]),
            ensure_ascii=False), flush=True)
    (OUT / 'MICRO_DIAG_RESULTS.json').write_text(json.dumps(
        dict(calls=meter.calls, cash=meter.cash,
             tokens=meter.tokens, results=results, evidence=rec),
        ensure_ascii=False, indent=1))
    ok = sum(1 for r in results if r['status'] == 'done')
    print(f'FINAL calls={meter.calls} cash={meter.cash} '
          f'contract_ok={ok}/{len(results)}')


if __name__ == '__main__':
    main()
