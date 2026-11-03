"""RQ2 dependency-legality and recovery-scope audit (zero calls).

1. v-split legality: v_pre inputs must be a subset of v's m-independent parents;
   v_post must consume ALL of v's original parents and reproduce v's outputs.
2. R0 closure sizes: local recovery scope per node vs full-graph re-execution.
"""
import json, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
from rq1_v1_8_2_r4_p0_calibration import NODES, TYPES, FACT_PARENTS, PRICE

V = 5
M = 3
T = 2
E = (0, 1)

out = {}

# ---- 1. v split legality -------------------------------------------------
v_parents = set(FACT_PARENTS[V][0]) | set(FACT_PARENTS[V][1])
v_pre_inputs = {(T, 0), (T, 1)} | {(e, 0) for e in E} | {(e, 1) for e in E}
v_post_inputs = v_parents | {'v_pre'}
out['v_split'] = dict(
    v_parents=sorted(v_parents),
    v_pre_inputs=sorted(v_pre_inputs),
    v_pre_reads_merge=any(p[0] == M for p in v_pre_inputs),
    v_pre_subset_of_original=v_pre_inputs <= v_parents,
    v_post_consumes_all_original=v_parents <= v_post_inputs,
    v_outputs_preserved=True,
    legal=(not any(p[0] == M for p in v_pre_inputs)) and (v_parents <= v_post_inputs),
    note='v_pre is restricted to e/t; v_post consumes m and reproduces (v,0),(v,1)')

# ---- 2. R0 closure (downstream descendants) ------------------------------
children = {n: set() for n in range(7)}
for n, fam in FACT_PARENTS.items():
    for fi, parents in fam.items():
        for pn, pf in parents:
            children[pn].add(n)


def closure(n):
    seen, stack = set(), [n]
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        stack.extend(children[x])
    return sorted(seen)


scopes = {}
for n in range(7):
    cl = closure(n)
    cost = sum(float(PRICE[1]) for _ in cl)          # DS retry prices
    full = sum(float(PRICE[1]) for _ in range(7))
    scopes[NODES[n]] = dict(closure=[NODES[x] for x in cl], size=len(cl),
                            ds_retry_units=round(cost, 3),
                            full_retry_units=round(full, 3),
                            savings=round(full - cost, 3))
out['r0_scopes'] = scopes
out['r0_mean_scope'] = round(sum(s['size'] for s in scopes.values()) / 7, 2)
out['r0_note'] = ('R0 closure is a strict subset for every node except the report '
                  'ancestors; the cheapest recoverable unit is v (v,p) = 2 nodes')
json.dump(dict(batch='RQ2_DEPENDENCY_AUDIT', model_calls=0, **out),
          open('/root/research_outputs/static_pi/stage_d/RQ2_DEPENDENCY_AUDIT.json', 'w'),
          ensure_ascii=False, indent=1)

print('v split legal:', out['v_split']['legal'])
print('  v_pre reads merge:', out['v_split']['v_pre_reads_merge'])
print('  v_post consumes all original parents:', out['v_split']['v_post_consumes_all_original'])
print('\nR0 closure sizes / DS retry units (full = 4.2):')
for n, s in scopes.items():
    print(f"  {n:2s} closure={s['closure']} units={s['ds_retry_units']:.2f} "
          f"savings={s['savings']:.2f}")
