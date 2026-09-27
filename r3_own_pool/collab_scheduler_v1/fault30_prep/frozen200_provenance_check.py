"""Zero-call provenance audit of the frozen200 fault arms (2026-09-27).

Question: can FROZEN200_RESULTS.json's f30 arms be reproduced by the repo's
frozen200_run.py logic, and do its per-task records show genuine fault
propagation?

Findings (all recomputed from artifacts, zero model calls):
  P1. Static fault arm: every e1/e2/r-faulted task is BYTE-IDENTICAL to clean
      (ok and used) in all 3 seeds — 0/54, 0/41, 0/45 changed. Only v-faulted
      tasks flip ok (3/15, 5/11, 6/15) plus non-faulted tasks in later seeds
      (0, 2, 8) — the latter grows with run order, i.e. cross-seed state
      leakage in the original in-process run.
  P2. The ledger backs this: REQUESTS.jsonl contains ZERO downstream
      re-executions under plain keys (fz:e1/e2/r/v/single all exactly 200 =
      the clean pass). All 465 fault-phase real calls carry recovery keys
      (:fb 216, :fb-d 95, :esc 154) — attributable to the dynamic arms.
  P3. Under the repo's frozen200_run.run_arm logic, an injected e-fault
      parses to empty facts, CHANGES the downstream r prompt, and must either
      hit the prompt cache or be executed for real. We reconstruct those
      fault-side r prompts from the same fault draws (draw alignment verified
      by the v-flip concentration on v-faulted tasks) and count how many
      exist in any ledger / cache directory: seed-23 has 21/32 absent
      everywhere. Hence the recorded static fault arms cannot have been
      produced by the current repo code path; e/r injections were no-ops in
      the recorded results.
  P4. Consequences: f30_static (Q .2933) has tainted provenance — excluded as
      an anchor for fault30. f30_dynamic (Q .4033) made real recovery calls
      and is kept as a WEAK anchor. f30_single is bookkeeping-only by design
      (fault marked failed, cost doubled, call served from cache). The
      s_fault30 front {Single, Dynamic} claim is unaffected (static is
      dominated either way); the static point itself must be re-measured by
      the cube fault30 run under real propagation.

Run: python3 -m collab_scheduler_v1.fault30_prep.frozen200_provenance_check
"""
import glob
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
FZ = ROOT / 'static_dag_v0/frozen200'
BENCH = ROOT / 'static_dag_v0/adaptive_benchmark'
OUT = ROOT / 'collab_scheduler_v1/fault30_prep'
SEEDS = (20260923, 20260924, 20260925)
RATE = 0.3


def build_faults(seed, rate, tasks, pools):
    """Bit-identical re-implementation of frozen200_run.build_faults."""
    rng = random.Random(seed)
    n_fault = int(len(tasks) * rate)
    faulted = rng.sample([t['uid'] for t in tasks], n_fault)
    faults = {}
    for u in faulted:
        node = rng.choice(['e1', 'e2', 'r', 'v'])
        if node in ('e1', 'e2'):
            failing = pools['e'][rng.randrange(len(pools['e']))]
        elif node == 'r':
            failing = pools['r'][rng.randrange(len(pools['r']))]
        else:
            failing = pools['v'][rng.randrange(len(pools['v']))]
        faults[u] = (node, failing)
    return faults


def run():
    sys.path.insert(0, str(ROOT))
    from static_dag_v0 import tool_aware_v1 as v
    from static_dag_v0.multidag_dynamic import parse_facts_safe

    tasks = json.loads((FZ / 'FROZEN200_POLICY.json').read_text())['tasks']
    tmap = {t['uid']: t for t in tasks}
    pools = json.loads((BENCH / 'FAULT_POOLS.json').read_text())
    results = json.loads((FZ / 'FROZEN200_RESULTS.json').read_text())['results']
    clean = results['clean|static']

    ans = {}
    for l in (FZ / 'RESPONSES.jsonl').read_text().splitlines():
        ans.setdefault(json.loads(l)['key'], json.loads(l)['response']['answer'])

    # ---- P1: per-node change census clean vs f30_static ----
    census = {}
    for seed in SEEDS:
        faults = build_faults(seed, RATE, tasks, pools)
        c = {}
        for u in clean:
            node = faults.get(u, (None,))[0] or 'none'
            f = results[f'f30_s{seed}|static'][u]
            changed = (clean[u]['ok'] != f['ok']) or abs(clean[u]['used'] - f['used']) > 1e-9
            c.setdefault(node, [0, 0])[0 if changed else 1] += 1
        census[str(seed)] = {k: tuple(x) for k, x in sorted(c.items())}

    # ---- P2: ledger request census by key kind ----
    req = {}
    for l in (FZ / 'REQUESTS.jsonl').read_text().splitlines():
        p = json.loads(l)['key'].split(':')
        if p[0] != 'fz':
            continue
        kind = p[3] if len(p) > 4 else 'plain'
        req[f'{p[1]}:{kind}'] = req.get(f'{p[1]}:{kind}', 0) + 1

    # ---- P3: fault-side r prompts vs every executed prompt anywhere ----
    executed = {}
    cache_dirs = [str(FZ)] + sorted(glob.glob(str(BENCH / 'fault_p*'))) + \
        [str(BENCH / 'fault_pool'), str(BENCH / 'exact_pareto')]
    for d in cache_dirs:
        p = Path(d) / 'REQUESTS.jsonl'
        if not p.exists():
            continue
        for l in p.read_text().splitlines():
            q = json.loads(l)
            executed[hashlib.sha256(q['prompt'].encode()).hexdigest()] = d

    prompt_census = {}
    for seed in SEEDS:
        faults = build_faults(seed, RATE, tasks, pools)
        hit = miss = 0
        miss_shas = []
        for u, (node, failing) in faults.items():
            if node not in ('e1', 'e2'):
                continue
            t = tmap[u]
            other = 'e2' if node == 'e1' else 'e1'
            f_other, _ = parse_facts_safe(ans[f'fz:{other}:{u}'])
            f_fault, _ = parse_facts_safe(failing)
            f_clean, _ = parse_facts_safe(ans[f'fz:{node}:{u}'])
            pairs = (f_fault, f_clean) if node == 'e1' else (f_other, f_other)
            m_fault = {'facts': (pairs[0]['facts'] if node == 'e1' else f_other['facts'])
                       + (pairs[0]['facts'] if node == 'e2' else f_other['facts'])}
            m_clean = {'facts': (f_clean['facts'] if node == 'e1' else f_other['facts'])
                       + (f_clean['facts'] if node == 'e2' else f_other['facts'])}
            pf = v.sprompt(dict(question=t['question']), m_fault)
            pc = v.sprompt(dict(question=t['question']), m_clean)
            if pf == pc:
                continue  # fault is a prompt-level no-op for this task
            if hashlib.sha256(pf.encode()).hexdigest() in executed:
                hit += 1
            else:
                miss += 1
                miss_shas.append(u)
        prompt_census[str(seed)] = dict(changed_prompt=hit + miss,
                                        found_somewhere=hit, found_nowhere=miss,
                                        nowhere_examples=miss_shas[:3])

    out = dict(
        question='can FROZEN200_RESULTS.json f30 arms be reproduced by repo code?',
        verdict='NO for the static arm: e/r injections are recorded as no-ops; '
                'downstream re-executions required by the code path exist in no ledger',
        P1_static_change_census_changed_same=census,
        P2_request_census=req,
        P3_fault_side_r_prompt_lookup=prompt_census,
        P4_anchor_policy=dict(
            f30_single='bookkeeping fault by design (marked failed, cost x2, cached call) — usable',
            f30_static='TAINTED — do not use as fault30 anchor; re-measure under real propagation',
            f30_dynamic='weak anchor — real recovery calls exist in the ledger',
            front_claim='s_fault30 front {Single, Dynamic} unaffected (static dominated either way)'),
        zero_model_calls=True)
    (OUT / 'FROZEN200_FAULT_PROVENANCE.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    run()
