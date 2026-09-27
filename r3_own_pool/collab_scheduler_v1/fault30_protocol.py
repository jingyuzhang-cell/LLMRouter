"""fault30 frozen protocol: config table + fault model + zero-call planner.

Single source of truth for the s_fault30 stage of the reference cube
(FAULT30_POLICY.json). The planner enumerates every (seed, config, task)
execution and classifies it WITHOUT any model call:

  INJECTED   persistent-fault triple (clean-ref cost, never cached)
  CACHED     (model, sha(prompt)) already executed in a seeded ledger
  PENDING    would be cached, but cube_clean has not produced it yet
  NEW        real model call required at fault30 time
  RUNTIME    call whose existence depends on a runtime answer (recovery
             stages after an effective reroute); counted separately with a
             structural expectation under documented assumption A1

NONE arms are fully decidable from artifacts (no detection, no recovery):
their NEW-call forecast is EXACT. LOCAL_REROUTE arms additionally fire on
naturally failed nodes (ungated detection), so their totals carry the
RUNTIME bucket.

Run:  python3 -m collab_scheduler_v1.fault30_protocol
"""
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
FZ = ROOT / 'static_dag_v0/frozen200'
BENCH = ROOT / 'static_dag_v0/adaptive_benchmark'
CUBE = ROOT / 'collab_scheduler_v1/cube_clean'
OUT = ROOT / 'collab_scheduler_v1/fault30_prep'

SEEDS = (20260923, 20260924, 20260925)
RATE = 0.3
X_MAP = {
    'BALANCED': {'e': 'medium', 'r': 'large', 'v': 'medium'},
    'HETEROGENEOUS': {'e': 'large', 'r': 'medium', 'v': 'coder'},
    'QUALITY': {'e': 'large', 'r': 'large', 'v': 'large'},
}
FAMS = ('BALANCED', 'HETEROGENEOUS', 'QUALITY')
SER_TOPOS = ('SER', 'SERV')
PAR_TOPOS = ('PARALLELER', 'DYNAMICDAG')
# execution order: NONE arms populate the cache first, recovery arms last
CONFIGS = ([f'{t}__{f}__NONE__FRESH' for t in ('SER', 'SERV', 'PARALLELER') for f in FAMS]
           + [f'DYNAMICDAG__{f}__NONE__FRESH' for f in FAMS]
           + [f'DYNAMICDAG__{f}__LOCAL_REROUTE__FRESH' for f in FAMS])


def config_parts(cid):
    topo, fam, z, _ = cid.split('__')
    return topo, fam, z


def planned_models(cid):
    topo, fam, z = config_parts(cid)
    xm = X_MAP[fam]
    if topo in SER_TOPOS:
        nodes = {'e': xm['e'], 'r': xm['r']}
    else:
        nodes = {'e1': xm['e'], 'e2': xm['e'], 'r': xm['r']}
    if topo in ('SERV', 'DYNAMICDAG'):
        nodes['v'] = xm['v']
    return topo, fam, z, nodes


def build_faults(seed, rate, tasks, pools):
    """Bit-identical to frozen200_run.build_faults (draw alignment verified
    in FROZEN200_FAULT_PROVENANCE.json via v-flip concentration)."""
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


def map_fault_node(drawn_node, topo):
    """F30 node mapping: e1/e2 -> branch (parallel) or single e (serial);
    v -> latent on topologies without a v node."""
    if drawn_node in ('e1', 'e2'):
        return drawn_node if topo in PAR_TOPOS else 'e'
    if drawn_node == 'v' and topo not in ('SERV', 'DYNAMICDAG'):
        return None
    return drawn_node


class Ledger:
    """Read-only view of executed prompts + answers (zero calls)."""

    def __init__(self):
        sys.path.insert(0, str(ROOT))
        from static_dag_v0 import tool_aware_v1 as v
        from static_dag_v0.multidag_dynamic import VPROMPT, parse_facts_safe
        self.v = v
        self.VPROMPT = VPROMPT
        self.parse_facts_safe = parse_facts_safe
        self.by_key = {}
        for l in (CUBE / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            self.by_key.setdefault(r['key'], r)
        self.executed = {}
        for l in (CUBE / 'REQUESTS.jsonl').read_text().splitlines():
            q = json.loads(l)
            self.executed.setdefault(q['prompt_sha256'], q['key'])
        self.fz_by_key = {}
        for l in (FZ / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            self.fz_by_key.setdefault(r['key'], r)
        for folder, pfield in ((FZ, 'prompt'), ):
            rp, qp = folder / 'RESPONSES.jsonl', folder / 'REQUESTS.jsonl'
            if qp.exists() and rp.exists():
                resp = {json.loads(l)['key']: json.loads(l) for l in rp.read_text().splitlines()}
                for l in qp.read_text().splitlines():
                    q = json.loads(l)
                    h = hashlib.sha256(q[pfield].encode()).hexdigest() if pfield == 'prompt' \
                        else q['prompt_sha256']
                    if q['key'] in resp and resp[q['key']].get('model') == q['model']:
                        r = resp[q['key']]['response']
                        if r.get('status') == 'delivered' and not r.get('injected_fault'):
                            self.executed.setdefault(h, q['key'])

    # ---- prompt builders (mirror cube_clean_run exactly) ----
    def eprompt(self, task, ctx):
        return self.v.eprompt(dict(question=task['question'], context=ctx))

    def sprompt(self, task, facts_dict):
        return self.v.sprompt(dict(question=task['question']), facts_dict)

    def vprompt(self, task, facts_list, expr):
        return self.VPROMPT.format(q=task['question'], facts=json.dumps(facts_list), expr=expr)

    # ---- clean-cube accessors ----
    def clean_key(self, topo, fam, node, uid):
        pfx = 'SER' if topo in SER_TOPOS else 'PAR'
        if node == 'e':
            node = 'e'
        if topo == 'SERV' and node == 'v':
            return f'cube:SERV:{fam}:v:{uid}'
        if topo == 'DYNAMICDAG' and node == 'v':
            return f'cube:DYNAMICDAG:{fam}:v:{uid}'
        return f'cube:{pfx}:{fam}:{node}:{uid}'

    def answer(self, key):
        rec = self.by_key.get(key) or self.fz_by_key.get(key)
        return rec['response'].get('answer') if rec else None

    def answer_for_prompt(self, prompt):
        h = hashlib.sha256(prompt.encode()).hexdigest()
        key = self.executed.get(h)
        return self.answer(key) if key else None

    def clean_facts(self, topo, fam, node, uid, task):
        key = self.clean_key(topo, fam, node, uid)
        a = self.answer(key)
        if a is None:
            return None  # PENDING
        f, _ = self.parse_facts_safe(a)
        return f

    def clean_expr(self, topo, fam, uid, task, merged_facts):
        key = self.clean_key(topo, fam, 'r', uid)
        a = self.answer(key)
        if a is None:
            return None
        try:
            from static_dag_v0.multidag_dynamic import value_of
            val, err = value_of(a, merged_facts)
            return 'UNPARSEABLE' if err else self.v.decode(a)['expression']
        except Exception:
            return 'UNPARSEABLE'

    def classify(self, model, prompt, virtual=None):
        """CACHED if executed in a seeded ledger or already simulated in this
        dry-run (virtual set); else NEW, and the sha is added to virtual so
        later configs dedup against it exactly as the executor's own cache
        would. RUNTIME calls cannot be dedup-simulated (answer unknown)."""
        h = hashlib.sha256(prompt.encode()).hexdigest()
        if h in self.executed or (virtual is not None and h in virtual):
            return 'CACHED'
        if virtual is not None:
            virtual.add(h)
        return 'NEW'


def plan_none(cid, seed, faults, led, task, uid, virtual):
    """Exact plan for a Z=NONE config (no detection, no recovery)."""
    topo, fam, z, nodes = planned_models(cid)
    drawn = faults.get(uid)
    active = None
    if drawn:
        mapped = map_fault_node(drawn[0], topo)
        if mapped and mapped in nodes:
            active = (mapped, drawn[1])
    steps = []
    fault_facts = {'facts': []}

    def e_step(node, ctx):
        if active and active[0] == node:
            steps.append(dict(node=node, model=nodes[node], cls='INJECTED'))
            return fault_facts, True
        f = led.clean_facts(topo, fam, node, uid, task)
        if f is None:
            steps.append(dict(node=node, model=nodes[node], cls='PENDING'))
            return None, False
        steps.append(dict(node=node, model=nodes[node], cls='CACHED'))
        return f, False

    if topo in SER_TOPOS:
        f_e, _ = e_step('e', task['ctx_table'] + '\n' + task['ctx_text'])
    else:
        f1, _ = e_step('e1', task['ctx_table'])
        f2, ch2 = e_step('e2', task['ctx_text'])
        f_e = None if f1 is None or f2 is None else {'facts': f1['facts'] + f2['facts']}
    # r
    r_fault = active and active[0] == 'r'
    if f_e is None:
        steps.append(dict(node='r', model=nodes['r'], cls='PENDING_DEP'))
    elif r_fault:
        steps.append(dict(node='r', model=nodes['r'], cls='INJECTED'))
    else:
        p = led.sprompt(task, f_e)
        cls = led.classify(nodes['r'], p, virtual)
        steps.append(dict(node='r', model=nodes['r'], cls=cls))
    # v
    if 'v' in nodes:
        v_fault = active and active[0] == 'v'
        if v_fault:
            steps.append(dict(node='v', model=nodes['v'], cls='INJECTED'))
        elif f_e is None:
            steps.append(dict(node='v', model=nodes['v'], cls='PENDING_DEP'))
        else:
            expr = led.clean_expr(topo, fam, uid, task, f_e)
            if expr is None:
                steps.append(dict(node='v', model=nodes['v'], cls='PENDING_DEP'))
            else:
                p = led.vprompt(task, f_e['facts'], expr)
                steps.append(dict(node='v', model=nodes['v'], cls=led.classify(nodes['v'], p, virtual)))
    return steps


def plan_reroute(cid, seed, faults, led, task, uid, memory, virtual):
    """Plan a DYNAMICDAG LOCAL_REROUTE config. Stages after an effective
    reroute depend on runtime answers -> RUNTIME bucket (assumption A1:
    an effective reroute returns parseable, non-empty facts / parseable
    value; natural rates taken from the legacy ledger where decidable)."""
    topo, fam, z, nodes = planned_models(cid)
    drawn = faults.get(uid)
    active = None
    if drawn:
        mapped = map_fault_node(drawn[0], topo)
        if mapped and mapped in nodes:
            active = (mapped, drawn[1])
    steps = []
    fault_facts = {'facts': []}

    # planned e1/e2 with detection bookkeeping
    e_state = {}
    for node, ctx in (('e1', task['ctx_table']), ('e2', task['ctx_text'])):
        if active and active[0] == node:
            steps.append(dict(node=node, model=nodes[node], cls='INJECTED', stage='planned'))
            e_state[node] = (fault_facts, True, 'fault')
        else:
            f = led.clean_facts(topo, fam, node, uid, task)
            if f is None:
                steps.append(dict(node=node, model=nodes[node], cls='PENDING', stage='planned'))
                e_state[node] = (None, False, 'pending')
            else:
                steps.append(dict(node=node, model=nodes[node], cls='CACHED', stage='planned'))
                e_state[node] = (f, False, 'empty' if not f['facts'] else 'ok')

    # stage 1: e recovery (memory rule) for detected empty/faulted branches
    e_changed = False
    for node in ('e1', 'e2'):
        f, injected, status = e_state[node]
        if status in ('pending',):
            continue
        if status == 'ok':
            continue
        target = 'coder' if memory['first'] else 'medium'
        memory['first'] = False
        if injected and nodes[node] == target:
            steps.append(dict(node=node, model=target, cls='INJECTED_PERSIST', stage='e-reroute'))
            continue  # ineffective: fault persists, state unchanged
        p = led.eprompt(task, task['ctx_table'] if node == 'e1' else task['ctx_text'])
        cls = led.classify(target, p, virtual)
        steps.append(dict(node=node, model=target, cls=cls, stage='e-reroute'))
        if cls == 'CACHED':
            f_rec, _ = led.parse_facts_safe(led.answer_for_prompt(p) or '')
            e_changed = e_changed or bool(f_rec['facts'])  # decidable
        else:
            e_changed = True  # A1: effective new reroute changes facts

    # planned r on current (possibly corrupted) facts
    f1, f2 = e_state['e1'][0], e_state['e2'][0]
    merged = None if f1 is None or f2 is None else {'facts': f1['facts'] + f2['facts']}
    r_fault = active and active[0] == 'r'
    r_new = False
    if merged is None:
        steps.append(dict(node='r', model=nodes['r'], cls='PENDING_DEP', stage='planned'))
    elif r_fault:
        steps.append(dict(node='r', model=nodes['r'], cls='INJECTED', stage='planned'))
    else:
        cls = led.classify(nodes['r'], led.sprompt(task, merged), virtual)
        r_new = cls == 'NEW'
        steps.append(dict(node='r', model=nodes['r'], cls=cls, stage='planned'))

    # stage 1b: r refresh after e change (prompt decidable unless a recovery
    # answer is still runtime-unknown)
    if e_changed:
        if any(s.get('stage') == 'e-reroute' and s['cls'] == 'NEW'
               for s in steps) or r_new:
            steps.append(dict(node='r', model=nodes['r'], cls='RUNTIME', stage='r-refresh'))
        else:
            f1r, f2r = e_state['e1'][0], e_state['e2'][0]
            # recompute merged with the recovered facts where decidable
            rec = {}
            for s in steps:
                if s.get('stage') == 'e-reroute' and s['cls'] == 'CACHED':
                    pp = led.eprompt(task, task['ctx_table'] if s['node'] == 'e1' else task['ctx_text'])
                    fr, _ = led.parse_facts_safe(led.answer_for_prompt(pp) or '')
                    rec[s['node']] = fr
            m = {'facts': rec.get('e1', f1r if f1r else {'facts': []})['facts']
                 + rec.get('e2', f2r if f2r else {'facts': []})['facts']}
            steps.append(dict(node='r', model=nodes['r'],
                              cls=led.classify(nodes['r'], led.sprompt(task, m), virtual),
                              stage='r-refresh'))
    # stage 2: r escalation on unparseable r (decidable only for cached r)
    if not r_fault and merged is not None:
        expr = led.clean_expr(topo, fam, uid, task, merged)
        if expr == 'UNPARSEABLE':
            if nodes['r'] == 'large':
                steps.append(dict(node='r', model='large', cls='RUNTIME', stage='r-esc',
                                  note='natural r failure; large==planned only if faulted'))
            else:
                steps.append(dict(node='r', model='large', cls=led.classify(
                    'large', led.sprompt(task, merged), virtual), stage='r-esc'))
    # stage 3/4: v refresh + escalation
    if 'v' in nodes:
        v_fault = active and active[0] == 'v'
        if v_fault:
            steps.append(dict(node='v', model=nodes['v'], cls='INJECTED', stage='planned'))
            if nodes['v'] != 'large':
                steps.append(dict(node='v', model='large', cls='RUNTIME', stage='v-esc'))
        else:
            steps.append(dict(node='v', model=nodes['v'], cls='RUNTIME' if (e_changed or r_new)
                              else 'PENDING_DEP', stage='planned-or-refresh'))
    return steps


def run():
    sys.path.insert(0, str(ROOT))
    tasks = json.loads((FZ / 'FROZEN200_POLICY.json').read_text())['tasks']
    pools = json.loads((BENCH / 'FAULT_POOLS.json').read_text())
    led = Ledger()
    PROMPT_VERSION_SHA = dict(
        eprompt=hashlib.sha256(led.v.eprompt(dict(question='q', context='c')).encode()).hexdigest(),
        sprompt=hashlib.sha256(led.v.sprompt(dict(question='q'), {'facts': []}).encode()).hexdigest(),
        VPROMPT=hashlib.sha256(led.VPROMPT.encode()).hexdigest())

    out = dict(prompt_version='vp1', prompt_version_sha=PROMPT_VERSION_SHA,
               assumption_A1='effective reroute returns parseable non-empty facts; '
                             'RUNTIME bucket counts calls whose existence depends on it',
               seeds={}, totals={})
    tot = {}
    virtual = set()  # simulates the executor's own accumulating prompt cache
    for seed in SEEDS:
        faults = build_faults(seed, RATE, tasks, pools)
        seed_out = {}
        for cid in CONFIGS:
            topo, fam, z, nodes = planned_models(cid)
            memory = {'first': True}
            agg = {}
            for t in tasks:
                uid = t['uid']
                steps = plan_none(cid, seed, faults, led, t, uid, virtual) if z == 'NONE' \
                    else plan_reroute(cid, seed, faults, led, t, uid, memory, virtual)
                for s in steps:
                    agg[s['cls']] = agg.get(s['cls'], 0) + 1
            seed_out[cid] = agg
            for k, n in agg.items():
                tot[k] = tot.get(k, 0) + n
        out['seeds'][str(seed)] = seed_out
        prev = dict(out.get('seeds', {}).get(str(SEEDS[0]), {}))  # placeholder
    # per-seed class totals (summed over configs) for printing
    per_seed = {}
    for seed in SEEDS:
        d = {}
        for agg in out['seeds'][str(seed)].values():
            for k, n in agg.items():
                d[k] = d.get(k, 0) + n
        per_seed[str(seed)] = d
    out['per_seed_totals'] = per_seed
    for seed, d in per_seed.items():
        print(f'seed {seed}: ' + json.dumps(d), flush=True)
    out['totals'] = tot
    out['new_call_forecast'] = dict(
        exact_NEW=tot.get('NEW', 0),
        runtime_expected=tot.get('RUNTIME', 0),
        pending_clean=tot.get('PENDING', 0) + tot.get('PENDING_DEP', 0),
        note='PENDING* buckets collapse to CACHED once cube_clean finishes; '
             'rerun this dry-run after clean completes for the exact budget')
    (OUT / 'FAULT30_DRYRUN.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(out['new_call_forecast'], indent=1))


if __name__ == '__main__':
    run()
