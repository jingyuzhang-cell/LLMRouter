"""Live E2E component ablation: Feedback / +gated-reroute / +decompose.

Zero new calls: rebuilds pre-decompose outcomes from the persisted call cache
and the live traces. Level 1 = Feedback arm (memory + verifier-triggered
fallback). Level 2 = Full arm minus decompose (type-gated reroute only): for
tasks where decompose fired, recompute the pre-decompose value from the cached
fallback response. Level 3 = Full arm as executed (decompose included).
"""
import argparse
import json

import numpy as np

from . import core
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

OUT = core.ROOT / 'static_dag_v0/live_e2e'
SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def run():
    traces = [json.loads(l) for l in (OUT / 'TRACES.jsonl').open()]
    cache = {}
    for line in (OUT / 'CALL_CACHE.jsonl').open():
        row = json.loads(line)
        k = tuple(row['key'].split('/')) if '/' in row['key'] else row['key']
        cache[k] = row['response']
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    tasks = {t['uid']: t for t in json.loads((SRC / 'TASKS.json').read_text())}
    node_by_id = {n['node_id']: n for n in nodes_all}

    level2 = []
    decompose_stats = dict(fired=0, rescued=0, harmed=0)
    for t in traces:
        full = t['arms']['Full']
        if not full.get('decompose'):
            level2.append(full['task_success'])
            continue
        decompose_stats['fired'] += 1
        # rebuild pre-decompose value from the cached fallback response
        r_node = next(n for n in nodes_all if n['task_uid'] == t['task_uid'] and n['node_type'] == 'reasoning')
        m_final = full['model']
        key = (r_node['node_id'], m_final, 'live')
        r = cache.get(key)
        pre_val = None
        if r is not None:
            # input facts: live-extracted if parsed else gold
            fb_trace = t['arms'].get('Feedback', {})
            facts = None
            m_ext_key = [k for k in cache if k[0].startswith(t['task_uid']) and k[0].endswith('ex0')]
            # reconstruct facts from the Full arm's own extraction call
            ext_node = next((n for n in nodes_all if n['task_uid'] == t['task_uid']
                             and n['node_type'] == 'extraction'), None)
            if ext_node is not None:
                ext_resp = None
                for k, resp in cache.items():
                    if k[0] == ext_node['node_id']:
                        ext_resp = resp
                        break
                if ext_resp is not None:
                    try:
                        facts = v.parse_facts(ext_resp['answer'])
                    except Exception:
                        facts = None
            rinput = facts if facts else r_node['gold_facts']
            try:
                expr = v.decode(r['answer'])['expression']
                pre_val = exec_calc(expr, rinput)
            except Exception:
                pre_val = None
        pre_ok = close(pre_val, tasks[t['task_uid']]['answer'])
        post_ok = full['task_success']
        if post_ok and not pre_ok:
            decompose_stats['rescued'] += 1
        if pre_ok and not post_ok:
            decompose_stats['harmed'] += 1
        level2.append(pre_ok)

    fb = [t['arms']['Feedback']['task_success'] for t in traces]
    full = [t['arms']['Full']['task_success'] for t in traces]
    static = [t['arms']['Static']['task_success'] for t in traces]
    result = dict(
        n=len(traces),
        levels=dict(
            Static=float(np.mean(static)),
            Feedback_memory_plus_fallback=float(np.mean(fb)),
            Full_minus_decompose_gated_reroute_only=float(np.mean(level2)),
            Full_all_components=float(np.mean(full))),
        decompose=dict(**decompose_stats,
                       note='rescued/harmed counted against pre-decompose rebuild from cache'),
        increments=dict(
            feedback_vs_static=100 * (np.mean(fb) - np.mean(static)),
            gating_vs_feedback=100 * (np.mean(level2) - np.mean(fb)),
            decompose_vs_gating=100 * (np.mean(full) - np.mean(level2))))
    core.write(OUT / 'COMPONENT_ABLATION.json', result)
    print(json.dumps(result, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
