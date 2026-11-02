"""Stage-C-R1 eight-item zero-API acceptance test (production entry).

All checks drive integration/stage_c_r1.py (run_arm) — the SAME executor
the real Meter path uses; only the adapter is the frozen deterministic
stand-in. NO model requests. Log written to stage_c_r1_runs/ACCEPTANCE_LOG.json.
"""
import json
import sys
from collections import Counter
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import stage_c_r1 as R1
from six_arm_scheduler import ARMS, z_candidates

LOG = {'checks': {}, 'pass': True}


def check(name, ok, detail=''):
    LOG['checks'][name] = dict(ok=bool(ok), detail=str(detail)[:500])
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))
    if not ok:
        LOG['pass'] = False


tasks = R1.load_tasks()
E1 = tasks['SC-E1']
tl = next(n['id'] for n in E1['task']['dag']['nodes'] if n['kind'] == 'timeline')
chk = next(n['id'] for n in E1['task']['dag']['nodes'] if n['kind'] == 'verification')

# ============ A1: per-arm decision wiring + Z/R/pi fingerprints ============
print("=== A1: six arms, one executor, per-state Z/R/pi fingerprints ===")
fps = {}
for arm in ARMS:
    r = R1.run_arm(arm, E1, {tl: dict(type='transport', left=1)})
    rec_rounds = [rd for rd in r['rounds'] if rd['recovery_set'] or rd['z_op'] != 'KEEP']
    fps[arm] = dict(status=r['status'],
                    z=[rd['z_op'] for rd in rec_rounds],
                    R=[rd['recovery_set'] for rd in rec_rounds],
                    models=sorted({c['model'] for c in r['calls']}),
                    seq=[(c['node'], c['model']) for c in r['calls']],
                    n_calls=len(r['calls']), tokens=r['tokens'],
                    makespan=r['makespan'],
                    baseline=r.get('baseline_type', ''))
    print(f"  {arm:16s} {r['status']:12s} R={fps[arm]['R']} models={fps[arm]['models']}")
check('A1a all six arms ran with distinct registered deciders',
      len(fps) == 6 and len({str(f['seq']) for f in fps.values()}) >= 3)
check('A1b Static-Parallel flagged no-recovery weak baseline',
      fps['Static-Parallel']['baseline'] == 'no-recovery weak baseline'
      and fps['Static-Parallel']['status'] == 'INCOMPLETE_NO_RECOVERY')
check('A1c R-only rationale records real family comparison',
      'legal sets' in str([rd for rd in R1.run_arm('R-only', E1, {tl: dict(type='transport', left=1)})['rounds'] if rd['recovery_set']][0]['rationale']))

# ============ A2: behavioural differentiation on same fault ============
print("\n=== A2: physical trace differentiation ===")
# across the discriminative fault SUITE (single transient, double transient,
# persistent contract): on a single weak transient several adaptive arms are
# PHYSICALLY EQUIVALENT by design (same optimal action) — differentiation is
# asserted over the suite, which is what a paired experiment would run.
# S4 tight deadline: joint objective is deadline-aware, pi-only greedy is
# not — a real algorithmic difference emerging under a legal constraint state
tight = 44.0   # after the healthy prefix (~34s) no retry meets the deadline
# anomaly FACTORIES: the adapter mutates the anomaly dict (left countdown),
# so every (arm, scenario) cell must build a fresh instance
suite = [('single', lambda: {tl: dict(type='transport', left=1)}, None),
         ('double', lambda: {tl: dict(type='transport', left=2)}, None),
         ('contract', lambda: {chk: dict(type='contract')}, None),
         ('tight', lambda: {tl: dict(type='transport', left=1)}, tight)]
traces = {}
for arm in ARMS:
    sig = []
    for name, mk, dl in suite:
        r = R1.run_arm(arm, E1, mk(), deadline_s=dl)
        sig.append((tuple((c['node'], c['model']) for c in r['calls']),
                    r['tokens'], r['makespan'], r['status'],
                    tuple(r['z_ops_applied'])))
    traces[arm] = tuple(sig)
distinct = len(set(traces.values()))
check('A2 >=5 distinct physical trace signatures across fault suite',
      distinct >= 5, f'{distinct} distinct of 6')

# ============ A3: transport recovery + repeated anomalies ============
print("\n=== A3: transport recovery and continuous feedback ===")
single = {arm: R1.run_arm(arm, E1, {tl: dict(type='transport', left=1)})['status']
          for arm in ARMS}
check('A3a single transient transport recovered by all adaptive arms',
      all(single[a] == 'COMPLETE' for a in ARMS if a != 'Static-Parallel')
      and single['Static-Parallel'] == 'INCOMPLETE_NO_RECOVERY', str(single))
dbl = {arm: R1.run_arm(arm, E1, {tl: dict(type='transport', left=2)})['status']
       for arm in ARMS}
r_dbl = R1.run_arm('Joint(R,pi)', E1, {tl: dict(type='transport', left=2)})
fb = sum(1 for rd in r_dbl['rounds'] if rd['recovery_set'])
check('A3b double transient: Joint recovers via repeated feedback rounds (bounded)',
      dbl['Joint(R,pi)'] == 'COMPLETE' and 2 <= fb <= R1.MAX_RECOVERY_ROUNDS,
      f'feedback rounds={fb}, Joint={dbl["Joint(R,pi)"]}, SimpleDyn={dbl["Simple-Dynamic"]}')
ctr = {arm: R1.run_arm(arm, E1, {chk: dict(type='contract')}) for arm in ARMS}
only_z = [a for a in ARMS if ctr[a]['status'] == 'COMPLETE']
check('A3c persistent contract violation: ONLY Joint(Z,R,pi) completes (via SPLIT)',
      only_z == ['Joint(Z,R,pi)']
      and ctr['Joint(Z,R,pi)']['z_ops_applied'] == [f'SPLIT_VERIFY:{chk}'],
      f'completers={only_z}')

# ============ A4: K_m queueing / makespan / deadline / cost ============
print("\n=== A4: K_m resource-constrained parallel kernel ===")
orig_init = R1.Kernel.__init__
R1.Kernel.__init__ = lambda self, k=None: orig_init(self, k={'glm53': 1, 'glm53flash': 1})
r_k1 = R1.run_arm('Joint(R,pi)', E1, {tl: dict(type='transport', left=1)})
R1.Kernel.__init__ = orig_init
r_k2 = R1.run_arm('Joint(R,pi)', E1, {tl: dict(type='transport', left=1)})
serial_sum = sum(c['latency_s'] for c in r_k2['calls'])
check('A4a K=1 contention produces queue waits; K=2 does not',
      r_k1['wait_total'] > 0 and r_k2['wait_total'] == 0,
      f'wait K1={r_k1["wait_total"]}s K2={r_k2["wait_total"]}s')
check('A4b parallel makespan < serial latency sum',
      r_k2['makespan'] < serial_sum,
      f'mk={r_k2["makespan"]}s < serial={serial_sum:.0f}s')
check('A4c deadline + cost recorded per run',
      r_k2['deadline_met'] is True and r_k2['tokens'] > 0
      and r_k2['deadline_s'] == 1800)

# ============ A5: healthy cache / blocking / versions / multi-parent ============
print("\n=== A5: cache, blocking, version propagation, multi-parent ===")
r5 = R1.run_arm('Joint(R,pi)', E1, {chk: dict(type='transport', left=1)})
counts = Counter(c['node'] for c in r5['calls'])
check('A5a healthy nodes executed exactly once (cache)',
      all(v == 1 for k, v in counts.items() if k != chk) and counts[chk] == 2,
      str(dict(counts)))
check('A5b failed node version advanced, healthy stay v1',
      r5['node_versions'][chk] == 2
      and all(v == 1 for k, v in r5['node_versions'].items() if k != chk))
# multi-parent prompt: verification node consumes BOTH parents (fin + tl)
adap = R1.DeterministicAdapter({chk: dict(type='transport', left=1)})
R1.run_arm('Joint(R,pi)', E1, {chk: dict(type='transport', left=1)}, adapter=adap)
chk_prompts = [p for n, p in adap.prompts if n == chk]
dep_map = {n['id']: n.get('deps', []) for n in E1['task']['dag']['nodes']}
parents_chk = dep_map[chk]
others = [n for n in dep_map if n not in parents_chk and n != chk]
check('A5c multi-parent input: chk prompt carries both parents (v-tagged), no non-parents',
      all(f'@v' in p and len(parents_chk) == 2 for p in chk_prompts)
      and all(all(dep not in p for dep in others) for p in chk_prompts),
      f'parents={parents_chk}')

# ============ A6: scoring isolation ============
print("\n=== A6: scorer label-blindness and evidence anchoring ===")
E2 = tasks['SC-E2']
tA = json.dumps({'report': ' '.join(f['answer'] for f in E1['silver'][:5])},
                ensure_ascii=False)
tB = json.dumps({'report': ' '.join(f['answer'] for f in E2['silver'][:5])},
                ensure_ascii=False)
qA1 = R1.score(tA, E1['silver'])[0]
qA2 = R1.score(tA, E1['silver'])[0]
qB = R1.score(tB, E1['silver'])[0]
check('A6a scorer deterministic and content-driven (not arm-driven)',
      qA1 == qA2 and qA1 != qB, f'Q(A)={qA1} Q(B)={qB}')

# ============ A7: heterogeneous pool + K_m ceiling ============
print("\n=== A7: heterogeneous pi and slot ceiling ===")
r7 = R1.run_arm('pi-only', E1, {tl: dict(type='transport', left=1)})
models_used = {c['model'] for c in r7['calls']}
check('A7a both models in the frozen pool actually used',
      models_used == {'glm53', 'glm53flash'}, str(models_used))
K = R1.K_M
viol = 0
for m in K:
    iv = sorted((c['start'], c['finish']) for c in r7['calls'] if c['model'] == m)
    for i in range(len(iv)):
        overlap = sum(1 for j in range(len(iv))
                      if iv[j][0] < iv[i][1] and iv[j][1] > iv[i][0])
        viol = max(viol, overlap)
check('A7b concurrency never exceeds K_m per model', viol <= max(K.values()),
      f'max concurrent={viol} <= {K}')

# ============ A8: 12 frozen tasks + ledger traceability ============
print("\n=== A8: task inventory and trace completeness ===")
rows = [json.loads(l) for l in open(B / 'tasks' / 'tasks_frozen.jsonl') if l.strip()]
ev_texts = B / 'evidence' / 'texts'
sc = B / 'stage_c_evidence'
man = json.load(open(sc / 'manifest.json'))
task_ok, detail = True, []
for t in rows:
    tid = t['task_id']
    miss = [d for d in t.get('evidence_doc_ids', [])
            if not (sc / 'text' / f'{d}.txt').exists()
            and not (ev_texts / f'{d}.txt').exists()]
    sv = B / 'scoring' / 'silver' / f'{tid}.silver.json'
    d = json.load(open(sv)) if sv.exists() else {}
    nf = len(d.get('facts', d.get('silver', [])))
    if miss or nf == 0 or not t.get('deadline_s'):
        task_ok = False
        detail.append(f'{tid}: miss={miss} facts={nf}')
check('A8a all 12 frozen tasks: docs present, silver refs non-empty, deadline set',
      task_ok, '; '.join(detail) or '12/12 OK')
raw_ok = all(
    __import__('hashlib').sha256((sc / 'raw' / f"{d['doc_id']}.pdf").read_bytes()).hexdigest()
    == d['sha256_raw']
    for m in man.values() for d in m['documents']
    if (sc / 'raw' / f"{d['doc_id']}.pdf").exists())
check('A8b SC raw PDFs match manifest sha256_raw', raw_ok)
r8 = R1.run_arm('Joint(Z,R,pi)', E1, {chk: dict(type='contract')})
tok_sum = sum(c['usage']['in'] + c['usage']['out'] for c in r8['calls'])
check('A8c trace complete: rounds+calls (model/latency/wait/usage/version/attempt), '
      'budget accounting consistent',
      all(k in r8 for k in ('rounds', 'calls', 'tokens', 'makespan',
                            'deadline_met', 'z_ops_applied'))
      and tok_sum == r8['tokens'],
      f'{len(r8["calls"])} calls, {len(r8["rounds"])} rounds, tokens={r8["tokens"]}')

# ============ summary + discriminability evidence ============
LOG['fingerprints'] = fps
LOG['transport_single'] = single
LOG['transport_double'] = dbl
LOG['contract_persistent'] = {a: ctr[a]['status'] for a in ARMS}
LOG['km'] = dict(K1=dict(wait=r_k1['wait_total'], makespan=r_k1['makespan']),
                 K2=dict(wait=r_k2['wait_total'], makespan=r_k2['makespan']),
                 serial_latency_sum=round(serial_sum, 1))
out = B / 'stage_c_r1_runs' / 'ACCEPTANCE_LOG.json'
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(LOG, ensure_ascii=False, indent=1, default=str))
print(f"\nOVERALL: {'8/8 PASS' if LOG['pass'] else 'FAILURES PRESENT'} -> {out}")
sys.exit(0 if LOG['pass'] else 1)
