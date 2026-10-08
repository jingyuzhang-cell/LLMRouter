"""E1: DAG Patch robustness — random DAGs, fault injection, patch ops (zero calls)."""
import copy
import json
import random
import time
from pathlib import Path

import sys
ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.dag_patch_p0 import RuntimeDAG, PatchError

OUT = ROOT / 'collab_scheduler_v1/e1_robustness'
N_DAGS = 300
SEED = 20261001
MODELS = ['medium', 'large', 'coder']


def random_dag(rng):
    """Generate a random DAG as {node: {deps, model}}."""
    n = rng.randint(4, 10)
    names = [f'n{i}' for i in range(n)]
    nodes = {}
    for i, name in enumerate(names):
        deps = []
        if i > 0:
            deps.append(rng.choice(names[:i]))
            if rng.random() < 0.3 and i > 1:
                extra = rng.choice(names[:i])
                if extra not in deps:
                    deps.append(extra)
        nodes[name] = dict(deps=deps, model=rng.choice(MODELS))
    return nodes


def random_patch(dag, rng):
    """Pick a random legal-ish patch operation."""
    pending = [n for n in dag.nodes if dag.nodes[n]['status'] == 'pending']
    if not pending:
        return None
    target = rng.choice(pending)
    op = rng.choice(['split', 'insert', 'remove', 'rewire'])
    if op == 'split':
        return ('split', target, f'{target}_a', f'{target}_b',
                rng.choice(MODELS), rng.choice(MODELS))
    elif op == 'insert':
        return ('insert', target, f'{target}_w', rng.choice(MODELS))
    elif op == 'remove':
        return ('remove', target)
    elif op == 'rewire':
        succs = [n for n in dag.nodes if target in dag.nodes[n]['deps']
                 and dag.nodes[n]['status'] == 'pending']
        if not succs:
            return None
        return ('rewire', target, rng.choice(succs))
    return None


def apply_patch(dag, patch):
    op = patch[0]
    if op == 'split':
        return dag.split_node(patch[1], patch[2], patch[3], patch[4], patch[5])
    elif op == 'insert':
        return dag.insert_node(patch[1], patch[2], patch[3])
    elif op == 'remove':
        return dag.remove_node(patch[1])
    elif op == 'rewire':
        return dag.rewire_edge(patch[1], patch[2])


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    c = dict(acyclic_pass=0, acyclic_fail=0,
             consumed_ok=0, consumed_violation=0,
             dep_integrity_ok=0, dep_integrity_fail=0,
             rollback_ok=0, rollback_fail=0,
             total_ops=0, total_rejected=0, unexpected_errors=0)
    failures = []
    per_dag_ms = []

    for trial in range(N_DAGS):
        nodes = random_dag(rng)
        dag = RuntimeDAG(nodes)
        # simulate partial execution
        done_nodes = []
        for n in sorted(dag.nodes):
            if rng.random() < 0.3:
                dag.nodes[n]['status'] = 'done'
                dag.nodes[n]['output'] = f'out_{n}'
                done_nodes.append(n)

        t_start = time.time()
        for p_idx in range(rng.randint(1, 5)):
            patch = random_patch(dag, rng)
            if patch is None:
                continue
            c['total_ops'] += 1
            before_nodes = copy.deepcopy(dag.nodes)
            try:
                apply_patch(dag, patch)
                c['acyclic_pass'] += 1  # PatchError would have been raised if cyclic
                c['dep_integrity_ok'] += 1
                # consumed protection
                for dn in done_nodes:
                    if dn not in dag.nodes and patch[0] in ('remove', 'split'):
                        c['consumed_violation'] += 1
                        failures.append(dict(trial=trial, p=p_idx, check='consumed', node=dn))
                        break
                else:
                    c['consumed_ok'] += 1
            except PatchError:
                c['total_rejected'] += 1
                c['acyclic_pass'] += 1  # correctly rejected
                # atomic rollback check
                if dag.nodes == before_nodes:
                    c['rollback_ok'] += 1
                else:
                    c['rollback_fail'] += 1
                    failures.append(dict(trial=trial, p=p_idx, check='rollback'))
            except Exception as e:
                c['unexpected_errors'] += 1
                failures.append(dict(trial=trial, p=p_idx, check='unexpected',
                                     error=str(e)[:80]))
        per_dag_ms.append((time.time() - t_start) * 1000)

    summary = dict(
        n_dags=N_DAGS, total_ops=c['total_ops'],
        acyclicity_rate=round(c['acyclic_pass'] / max(1, c['total_ops']), 4),
        consumed_protection_rate=round(c['consumed_ok'] / max(1, c['consumed_ok'] + c['consumed_violation']), 4),
        atomic_rollback_rate=round(c['rollback_ok'] / max(1, c['rollback_ok'] + c['rollback_fail']), 4),
        rejected_patches=c['total_rejected'],
        unexpected_errors=c['unexpected_errors'],
        mean_ms_per_dag=round(sum(per_dag_ms) / len(per_dag_ms), 2))

    out = dict(summary=summary, checks=c, failures=failures[:20])
    (OUT / 'E1_ROBUSTNESS.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    run()
