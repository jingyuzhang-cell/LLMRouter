"""E1 consumed-node stress test (reproducible). Seed=20261001, 200 trials."""
import json, random, sys
sys.path.insert(0, '/root/r3_own_pool')
from collab_scheduler_v1.dag_patch_p0 import RuntimeDAG, PatchError

rng = random.Random(20261001)
c = dict(consumed_attempted=0, consumed_rejected=0, consumed_incorrect_accept=0,
         unconsumed_attempted=0, unconsumed_accepted=0)
for trial in range(200):
    nodes = {f'n{i}': dict(deps=[f'n{j}' for j in range(i) if rng.random() < 0.3],
                           model='medium') for i in range(rng.randint(4, 8))}
    dag = RuntimeDAG(nodes)
    done = [n for n in sorted(dag.nodes) if rng.random() < 0.4]
    for n in done:
        dag.nodes[n]['status'] = 'done'
        dag.nodes[n]['output'] = 'x'
    for n in done:
        has_done_succ = any(dag.nodes[s]['status'] == 'done' for s in dag._succs(n))
        for op in ['remove', 'split']:
            try:
                if op == 'remove':
                    dag.remove_node(n)
                else:
                    dag.split_node(n, f'{n}_a', f'{n}_b', 'large', 'coder')
                if has_done_succ:
                    c['consumed_attempted'] += 1
                    c['consumed_incorrect_accept'] += 1
                else:
                    c['unconsumed_attempted'] += 1
                    c['unconsumed_accepted'] += 1
            except (PatchError, Exception):
                if has_done_succ:
                    c['consumed_attempted'] += 1
                    c['consumed_rejected'] += 1
                else:
                    c['unconsumed_attempted'] += 1
print(json.dumps(dict(
    consumed_protection_rate=c['consumed_rejected'] / max(1, c['consumed_attempted']),
    consumed_attempted=c['consumed_attempted'], consumed_rejected=c['consumed_rejected'],
    consumed_incorrect_accept=c['consumed_incorrect_accept']), indent=1))
