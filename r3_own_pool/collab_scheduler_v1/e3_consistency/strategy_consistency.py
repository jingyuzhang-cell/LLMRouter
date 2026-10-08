"""E3: Recovery strategy consistency — Static vs Local Reroute vs Dynamic Patch."""
import json
import sys
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/e3_consistency'

from collab_scheduler_v1.dag_patch_p0 import RuntimeDAG

MODELS = ['medium', 'large', 'coder']


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def call(self, key, model, faulted=False):
        self.calls.append(dict(key=key, model=model, faulted=faulted))
        if faulted:
            return dict(answer='GARBAGE')
        return dict(answer='OK')


def make_dag():
    return RuntimeDAG({
        'e1': dict(deps=[], model='large'),
        'e2': dict(deps=[], model='large'),
        'r': dict(deps=['e1', 'e2'], model='medium'),
        'v': dict(deps=['r'], model='coder'),
    })


def run_static(ex, fault_node):
    dag = make_dag()
    executed = []
    for n in sorted(dag.nodes):
        faulted = (n == fault_node)
        ex.call(f'st:{n}', dag.nodes[n]['model'], faulted)
        dag.nodes[n]['status'] = 'done'
        executed.append(n)
    return dict(nodes=sorted(dag.nodes), edges=sorted(dag.E()), executed=executed,
                patches=[], switches=[], n_calls=len(ex.calls))


def run_reroute(ex, fault_node):
    dag = make_dag()
    executed = []
    switches = []
    for n in sorted(dag.nodes):
        faulted = (n == fault_node)
        model = dag.nodes[n]['model']
        ex.call(f'rr:{n}', model, faulted)
        if faulted:
            new_model = 'large' if model != 'large' else 'coder'
            switches.append(dict(node=n, from_m=model, to_m=new_model))
            ex.call(f'rr:{n}:esc', new_model)
        dag.nodes[n]['status'] = 'done'
        executed.append(n)
    return dict(nodes=sorted(dag.nodes), edges=sorted(dag.E()), executed=executed,
                patches=[], switches=switches, n_calls=len(ex.calls))


def run_patch(ex, fault_node):
    dag = make_dag()
    executed = []
    patches = []
    for n in sorted(dag.nodes):
        if n == fault_node:
            try:
                dag.split_node(n, f'{n}_a', f'{n}_b', 'large', 'coder')
                patches.append(dict(op='split', node=n))
            except Exception:
                patches.append(dict(op='split_failed', node=n))
            for half in [f'{n}_a', f'{n}_b']:
                if half in dag.nodes:
                    ex.call(f'dp:{half}', dag.nodes[half]['model'])
                    dag.nodes[half]['status'] = 'done'
                    executed.append(half)
        else:
            ex.call(f'dp:{n}', dag.nodes[n]['model'], n == fault_node)
            dag.nodes[n]['status'] = 'done'
            executed.append(n)
    return dict(nodes=sorted(dag.nodes), edges=sorted(dag.E()), executed=executed,
                patches=patches, switches=[], n_calls=len(ex.calls))


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    results = []
    for fault in ['r', 'v', 'e1']:
        r_s = run_static(FakeExecutor(), fault)
        r_rr = run_reroute(FakeExecutor(), fault)
        r_dp = run_patch(FakeExecutor(), fault)
        for r, name in [(r_s, 'static'), (r_rr, 'reroute'), (r_dp, 'patch')]:
            r['strategy'] = name
            r['fault'] = fault
            results.append(r)
        checks[f'{fault}_static_no_change'] = not r_s['patches'] and not r_s['switches']
        checks[f'{fault}_reroute_has_switch'] = bool(r_rr['switches'])
        checks[f'{fault}_reroute_no_patch'] = not r_rr['patches']
        checks[f'{fault}_patch_changed_graph'] = r_dp['nodes'] != r_s['nodes']
        checks[f'{fault}_paths_differ'] = r_dp['executed'] != r_s['executed'] or \
            r_rr['n_calls'] != r_s['n_calls']

    all_pass = all(checks.values())
    out = dict(all_pass=all_pass, checks=checks, results=results)
    (OUT / 'E3_CONSISTENCY.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(dict(all_pass=all_pass, n_checks=len(checks),
                          passed=sum(checks.values())), indent=1))


if __name__ == '__main__':
    run()
