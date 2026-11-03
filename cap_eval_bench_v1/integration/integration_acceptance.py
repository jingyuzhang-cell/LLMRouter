"""Zero-pay three-window integration acceptance harness (all inputs SYNTHETIC).

Gate for ANY paid batch: every registered arm family must pass schema validation,
v1 scoring, v1.1 unified mapping, retrieval reconciliation (incl. deliberate
mismatch detection), isolation gate, and freeze verification. No model calls.
"""
import json
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / 'scoring'))
sys.path.insert(0, str(BENCH / 'evidence'))
import qe_k_scorer as S                      # noqa: E402
import metric_mapping_v1_1 as M              # noqa: E402
import retrieval_api as R                    # noqa: E402

ARMS = ['fixed_graph', 'auto_graph', 'optimized_graph',
        'alloc_homogeneous', 'alloc_router', 'alloc_rule', 'alloc_static_opt',
        'dyn_Static', 'dyn_R_only', 'dyn_pi_only', 'dyn_Joint_R_pi', 'dyn_Joint_Z_R_pi',
        'single_model', 'fixed_homogeneous']
REQUIRED_TRACE_KEYS = {'run_id', 'system_id', 'task_id', 'status', 'nodes', 'wall_s', 'deliverable_ref'}


def synthetic_trace(arm, task_id='T-R1', ret_calls=1, ret_chars=2000):
    return {'run_id': f'ACC-SYNTH-{arm}', 'system_id': 'other_declared', 'task_id': task_id,
            'config_hash': 'acceptance-synthetic', 'status': 'COMPLETE',
            'planning': {'calls': 1, 'latency_s': 1.0, 'usage': {'in': 500, 'out': 200}},
            'retrieval': {'calls': ret_calls, 'chars_injected': ret_chars},
            'nodes': [{'node_id': 'n1', 'kind': 'extraction', 'model': 'M', 'attempt': 1,
                       'usage': {'in': 400, 'out': 150}, 'latency_s': 2.0, 'parse_status': 'OK'}],
            'reuse_events': 0, 'program_ms': 3.0, 'wall_s': 12.0,
            'deliverable_ref': 'synthetic', 'notes': f'SYNTHETIC acceptance arm={arm}'}


def reconcile(run_id, trace):
    """Trace retrieval accounting must match the retrieval audit log for this run."""
    logf = BENCH / 'evidence' / 'retrieval_log.jsonl'
    logged = [json.loads(l) for l in logf.read_text().splitlines() if l.strip()]
    mine = [e for e in logged if e['run_id'] == run_id]
    trace_calls = trace.get('retrieval', {}).get('calls', 0)
    trace_chars = trace.get('retrieval', {}).get('chars_injected', 0)
    log_calls = len(mine)
    log_chars = sum(e['chars_injected'] for e in mine)
    return trace_calls == log_calls and trace_chars == log_chars


def main():
    results = {'synthetic_only': True, 'arms': {}, 'checks': {}}
    deliverable = {'report': 'SYNTHETIC acceptance', 'unknown_marks': []}
    # give each arm a real retrieval call; build the trace FROM the logged values
    ret = {}
    for arm in ARMS:
        _, used = R.retrieve('T-R1', f'ACC-SYNTH-{arm}', ['约谈', '暂停'], 1500)
        ret[arm] = used
    for arm in ARMS:
        tr = synthetic_trace(arm, ret_calls=1, ret_chars=ret[arm])
        ok_keys = REQUIRED_TRACE_KEYS <= set(tr)
        v1 = S.score_run(tr, deliverable)
        u = M.score_unified(tr, deliverable)
        ok_map = (set(u) >= {'Q', 'E_evidence', 'K', 'C', 'L', 'Reliability'}
                  and u['C']['total_tokens'] == v1['E']['C_total_tokens'])
        ok_rec = reconcile(f'ACC-SYNTH-{arm}', tr)
        results['arms'][arm] = {'schema': ok_keys, 'v1_scored': bool(v1['Q']['Q'] >= 0),
                                'unified_mapped': ok_map, 'reconciled': ok_rec}
    # deliberate mismatch must be detected
    bad = synthetic_trace('fixed_graph'); bad['retrieval'] = {'calls': 9, 'chars_injected': 9999}
    results['checks']['mismatch_detected'] = not reconcile('ACC-SYNTH-fixed_graph', bad)
    # isolation gate + freeze verification via the frozen test suite
    g = subprocess.run(['python3', str(BENCH / 'isolation' / 'gate.py'), 'selftest'],
                       capture_output=True, text=True)
    t = subprocess.run(['python3', str(BENCH / 'tests' / 'test_bench.py')],
                       capture_output=True, text=True)
    results['checks']['isolation_selftest'] = g.returncode == 0
    results['checks']['frozen_suite'] = '0 failed' in t.stdout
    verdict = (all(all(v.values()) for v in results['arms'].values())
               and all(results['checks'].values()))
    results['verdict'] = 'ACCEPT' if verdict else 'REJECT'
    (BENCH / 'integration' / 'acceptance_report.json').write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(json.dumps({'verdict': results['verdict'],
                      'arms_ok': f"{sum(all(v.values()) for v in results['arms'].values())}/{len(ARMS)}",
                      'checks': results['checks']}, ensure_ascii=False))
    return 0 if verdict else 1


if __name__ == '__main__':
    sys.exit(main())
