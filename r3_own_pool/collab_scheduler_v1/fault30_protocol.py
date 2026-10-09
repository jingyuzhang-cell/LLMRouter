"""fault30 frozen protocol: config table + fault model + zero-call planner.

Single source of truth for the s_fault30 stage of the reference cube
(FAULT30_POLICY.json). The planner enumerates every (seed, config, task)
execution and classifies it WITHOUT any model call:

  INJECTED        persistent-fault triple (clean-ref cost, never cached)
  CACHED          (model, sha(prompt)) already executed in a seeded ledger or
                  already simulated earlier in this dry-run (virtual set)
  NEW             real model call required at fault30 time
  RUNTIME         call whose existence depends on a runtime answer (recovery
                  stages after an effective reroute); counted separately under
                  documented assumption A1
  PENDING*        would be cached but cube_clean has not produced it yet

NONE arms are fully decidable from artifacts (no detection, no recovery):
their NEW-call forecast is EXACT. LOCAL_REROUTE arms additionally fire on
naturally failed nodes (ungated detection), hence the RUNTIME bucket.

Clean-cube answers/costs resolve through cube_analyze's alias-aware ledger
(the runner served some keys from its by_mp cache without writing them;
alias identity is (model, sha(prompt)) in execution order).

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
    # Joint-search extended families (asymmetric e1/e2 supported)
    'CHEAP': {'e1': 'medium', 'e2': 'medium', 'r': 'medium', 'v': 'medium'},
    'TYPE_PRIOR': {'e1': 'large', 'e2': 'medium', 'r': 'coder', 'v': 'large'},
    'CODER_HEAVY': {'e1': 'coder', 'e2': 'coder', 'r': 'medium', 'v': 'coder'},
    'MIXED_EXTRACT': {'e1': 'large', 'e2': 'coder', 'r': 'medium', 'v': 'coder'},
    'REV_EXTRACT': {'e1': 'coder', 'e2': 'large', 'r': 'medium', 'v': 'large'},
    'ASYM_EXT_LARGE': {'e1': 'coder', 'e2': 'large', 'r': 'medium', 'v': 'coder'},
    'CODER_REASON': {'e1': 'large', 'e2': 'large', 'r': 'coder', 'v': 'coder'},
    'CHEAP_R_CODER': {'e1': 'medium', 'e2': 'medium', 'r': 'coder', 'v': 'coder'},
    'VERIFY_LARGE': {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'large'},
    'VERIFY_MEDIUM': {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'medium'},
    'CHEAP_V_LARGE': {'e1': 'medium', 'e2': 'medium', 'r': 'medium', 'v': 'large'},
    'LARGE_REASONER': {'e1': 'medium', 'e2': 'medium', 'r': 'large', 'v': 'coder'},
    'MED_COD_LAR_COD': {'e1': 'medium', 'e2': 'coder', 'r': 'large', 'v': 'coder'},
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
        nodes = {'e': xm.get('e', xm.get('e1')), 'r': xm['r']}
    else:
        nodes = {'e1': xm.get('e1', xm.get('e')), 'e2': xm.get('e2', xm.get('e')),
                 'r': xm['r']}
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
    """Read-only artifact view: alias-aware clean answers/costs + executed
    (model, sha(prompt)) index. Zero model calls."""

    def __init__(self):
        sys.path.insert(0, str(ROOT))
        from collab_scheduler_v1 import cube_analyze
        from static_dag_v0 import tool_aware_v1 as v
        from static_dag_v0.multidag_dynamic import VPROMPT, parse_facts_safe
        self.v = v
        self.VPROMPT = VPROMPT
        self.parse_facts_safe = parse_facts_safe
        self._resolve, self._cost, self._lat = cube_analyze.load_ledgers()[:3]
        # executed index, keyed (model, prompt_sha) like the runner's by_mp
        self.executed = {}
        for l in (CUBE / 'REQUESTS.jsonl').read_text().splitlines():
            q = json.loads(l)
            self.executed.setdefault((q['model'], q['prompt_sha256']), q['key'])
        resp = {json.loads(l)['key']: json.loads(l)
                for l in (FZ / 'RESPONSES.jsonl').read_text().splitlines()}
        for l in (FZ / 'REQUESTS.jsonl').read_text().splitlines():
            q = json.loads(l)
            r = resp.get(q['key'])
            if r is None or r.get('model') != q['model']:
                continue
            response = r['response']
            if response.get('status') != 'delivered' or response.get('injected_fault'):
                continue
            h = hashlib.sha256(q['prompt'].encode()).hexdigest()
            self.executed.setdefault((q['model'], h), q['key'])

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
        if node == 'v' and topo in ('SERV', 'DYNAMICDAG'):
            return f'cube:{topo}:{fam}:v:{uid}'
        return f'cube:{pfx}:{fam}:{node}:{uid}'

    def answer(self, key):
        return self._resolve(key)

    def clean_facts(self, topo, fam, node, uid, task):
        a = self.answer(self.clean_key(topo, fam, node, uid))
        if a is None:
            return None  # PENDING
        f, _ = self.parse_facts_safe(a)
        return f

    def clean_expr(self, topo, fam, uid, task, merged_facts):
        a = self.answer(self.clean_key(topo, fam, 'r', uid))
        if a is None:
            return None
        try:
            return self.v.decode(a)['expression']  # runner phase-V semantics: decode-only
        except Exception:
            return 'UNPARSEABLE'

    def classify(self, model, prompt, virtual=None):
        """CACHED if executed or already simulated in this dry-run; else NEW,
        with the (model, sha) added to virtual so later configs dedup against
        it exactly as the executor's own cache would."""
        h = hashlib.sha256(prompt.encode()).hexdigest()
        if (model, h) in self.executed or (virtual is not None and (model, h) in virtual):
            return 'CACHED'
        if virtual is not None:
            virtual.add((model, h))
        return 'NEW'

    def answer_for_prompt(self, model, prompt):
        h = hashlib.sha256(prompt.encode()).hexdigest()
        key = self.executed.get((model, h))
        return self.answer(key) if key else None


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
        f2, _ = e_step('e2', task['ctx_text'])
        f_e = None if f1 is None or f2 is None else {'facts': f1['facts'] + f2['facts']}
    r_fault = active and active[0] == 'r'
    if f_e is None:
        steps.append(dict(node='r', model=nodes['r'], cls='PENDING_DEP'))
    elif r_fault:
        steps.append(dict(node='r', model=nodes['r'], cls='INJECTED'))
    else:
        p = led.sprompt(task, f_e)
        steps.append(dict(node='r', model=nodes['r'], cls=led.classify(nodes['r'], p, virtual)))
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
                steps.append(dict(node='v', model=nodes['v'],
                                  cls=led.classify(nodes['v'], p, virtual)))
    return steps


def plan_reroute(cid, seed, faults, led, task, uid, memory, virtual):
    """Plan a DYNAMICDAG LOCAL_REROUTE config. Stages after an effective
    reroute depend on runtime answers -> RUNTIME bucket (assumption A1:
    an effective NEW reroute returns parseable, non-empty facts; cached
    reroute answers decide their branch exactly from the ledger)."""
    topo, fam, z, nodes = planned_models(cid)
    drawn = faults.get(uid)
    active = None
    if drawn:
        mapped = map_fault_node(drawn[0], topo)
        if mapped and mapped in nodes:
            active = (mapped, drawn[1])
    steps = []
    fault_facts = {'facts': []}

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
    e_new_recovery = False
    for node in ('e1', 'e2'):
        f, injected, status = e_state[node]
        if status in ('pending', 'ok'):
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
            f_rec, _ = led.parse_facts_safe(led.answer_for_prompt(target, p) or '')
            e_changed = e_changed or bool(f_rec['facts'])  # decidable
        else:
            e_changed = True
            e_new_recovery = True  # A1

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

    # stage 1b: r refresh after e change
    if e_changed:
        if e_new_recovery or r_new:
            steps.append(dict(node='r', model=nodes['r'], cls='RUNTIME', stage='r-refresh'))
        else:
            rec = {}
            for s in steps:
                if s.get('stage') == 'e-reroute' and s['cls'] == 'CACHED':
                    pp = led.eprompt(task, task['ctx_table'] if s['node'] == 'e1'
                                     else task['ctx_text'])
                    fr, _ = led.parse_facts_safe(led.answer_for_prompt(s['model'], pp) or '')
                    rec[s['node']] = fr
            m = {'facts': rec.get('e1', f1 if f1 else {'facts': []})['facts']
                 + rec.get('e2', f2 if f2 else {'facts': []})['facts']}
            steps.append(dict(node='r', model=nodes['r'],
                              cls=led.classify(nodes['r'], led.sprompt(task, m), virtual),
                              stage='r-refresh'))
    # stage 2: r escalation on unparseable r (decidable only for cached r)
    if not r_fault and merged is not None:
        expr = led.clean_expr(topo, fam, uid, task, merged)
        if expr == 'UNPARSEABLE':
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
            steps.append(dict(node='v', model=nodes['v'],
                              cls='RUNTIME' if (e_changed or r_new) else 'CACHED',
                              stage='planned-or-refresh'))
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
               assumption_A1='effective NEW reroute returns parseable non-empty facts; '
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
    out['totals'] = tot
    out['new_call_forecast'] = dict(
        exact_NEW=tot.get('NEW', 0),
        runtime_expected=tot.get('RUNTIME', 0),
        pending_clean=tot.get('PENDING', 0) + tot.get('PENDING_DEP', 0),
        note='PENDING* buckets collapse to CACHED once cube_clean finishes; '
             'rerun this dry-run after clean completes for the exact budget')
    per_seed = {}
    for seed in SEEDS:
        d = {}
        for agg in out['seeds'][str(seed)].values():
            for k, n in agg.items():
                d[k] = d.get(k, 0) + n
        per_seed[str(seed)] = d
    out['per_seed_totals'] = per_seed
    (OUT / 'FAULT30_DRYRUN.json').write_text(json.dumps(out, indent=1))
    for seed, d in per_seed.items():
        print(f'seed {seed}: ' + json.dumps(d), flush=True)
    print(json.dumps(out['new_call_forecast'], indent=1))


if __name__ == '__main__':
    run()
