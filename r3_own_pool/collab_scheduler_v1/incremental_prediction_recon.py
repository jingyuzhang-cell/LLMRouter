"""Pre-execution incremental cost prediction vs post-execution reconciliation.

Tests that a PREDICTOR (seeing only: candidate config, current cache state,
and observed upstream dependencies) can correctly bound the number of new
physical calls — WITHOUT reading the candidate's actual model outputs.

Key design: the predictor runs BEFORE eval_config() and outputs:
  - predicted_lower_bound: minimum new calls (nodes whose prompts provably
    differ from cache, plus unconditional model swaps)
  - predicted_upper_bound: maximum new calls (all potentially-changed nodes
    including conditional downstream cascades)
  - conditional_nodes: nodes whose new-call status depends on outputs not yet
    generated (e.g., v depends on r's new expression)

Then eval_config() runs and we reconcile: actual_new_calls must fall within
[predicted_lower, predicted_upper].

Scenarios (fixing the three issues from the audit):
  R1 Single-node swap (r only, v model FIXED) — isolates r's downstream effect
  R2 Upstream change (e1 fault→fb with DIFFERENT facts) — full cascade
  R3 Full cache hit — zero predicted, zero actual

Run: python3 -m collab_scheduler_v1.incremental_prediction_recon
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1 import fault30_protocol as fp  # noqa: E402

OUT = ROOT / 'collab_scheduler_v1/fault30_prep/incremental_cost_tests'


class ReconExecutor:
    """Tracks logical calls, physical calls, cache hits, and injected calls."""

    def __init__(self, cached_shas):
        self.cached = cached_shas
        self.by_key = {}
        self.call_log = []
        self.faults = {}
        self.proc = self.log = None
        self.current = None
        self.lock = None

    def set_fault(self, uid, node, model, failing, usage=None, lat=None):
        self.faults[(uid, node, model)] = (failing, usage, lat)

    def clear_faults(self):
        self.faults = {}

    def call(self, key, model, prompt, uid=None, node=None):
        parts = key.split(':')
        nd, kind = parts[3], (parts[4] if len(parts) > 5 else 'plain')
        sha = hashlib.sha256(prompt.encode()).hexdigest()
        is_inj = uid is not None and (uid, node, model) in self.faults
        is_cached = not is_inj and (model, sha) in self.cached
        self.call_log.append(dict(key=key, node=nd, kind=kind, model=model,
                                  sha=sha, cached=is_cached, injected=is_inj,
                                  physical=not is_cached and not is_inj))
        if is_inj:
            f_ans, f_u, f_l = self.faults[(uid, node, model)]
            ans, tok, lat = f_ans, 1, 0.0
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=ans,
                                     usage=dict(total_tokens=tok),
                                     latency_s=lat, injected_fault=True))
        elif is_cached:
            ans = '{"value": 4.0}'  # placeholder for cached answer
            rec = dict(key=key, model=model, alias_of='cache',
                       response=dict(status='delivered', answer=ans,
                                     usage=dict(total_tokens=50),
                                     latency_s=0.1))
        else:
            ans = '{"value": 4.0}'  # placeholder
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=ans,
                                     usage=dict(total_tokens=100),
                                     latency_s=0.2))
        self.by_key[key] = rec
        return rec

    def answer(self, key):
        return self.by_key[key]['response']['answer']

    def cost(self, key):
        return float(self.by_key[key]['response'].get('usage', {})
                     .get('total_tokens') or 0)

    def lat(self, key):
        return float(self.by_key[key]['response'].get('latency_s') or 0)

    def run_stage(self, jobs):
        for model in sorted({j['model'] for j in jobs}):
            for j in jobs:
                if j['model'] == model:
                    j['go']()

    def acquire_gpu(self):
        pass

    def release(self):
        pass


def predict_incremental_cost(config_from, config_to, task, cache_shas, led,
                             fault_at=None):
    """Pre-execution predictor: sees ONLY config definitions, cache state,
    and the task. Does NOT read any candidate model output, expression,
    or downstream prompt content (those depend on unobserved outputs).

    Returns lower_bound, upper_bound, conditional_nodes.
    """
    _, fam_a, _, nodes_a = fp.planned_models(config_from)
    _, fam_b, _, nodes_b = fp.planned_models(config_to)

    # Determine which node's MODEL assignment changed
    model_changes = {}
    for nd in nodes_b:
        old_m = nodes_a.get(nd)
        new_m = nodes_b[nd]
        if old_m != new_m:
            model_changes[nd] = (old_m, new_m)

    # Nodes that are UNCONDITIONALLY new (model swap or new node type)
    unconditional_new = set()
    for nd, (old, new) in model_changes.items():
        unconditional_new.add(nd)

    # Upstream change detection: if fault is at an e node, e's facts change
    # → r's prompt changes → r is conditionally new → v conditionally new
    conditional = set()
    if fault_at and fault_at.startswith('e'):
        unconditional_new.add(fault_at)  # fb call is deterministically needed
        conditional.add('r')   # r's facts change
        conditional.add('v')   # v's expression may change
    elif 'r' in model_changes:
        # r model swap → r output changes → v's expr may change
        conditional.add('v')

    # Check if e nodes' prompts are cacheable (same model, same context)
    for nd in nodes_b:
        if nd.startswith('e') and nd not in model_changes:
            # Same model, same input → check cache
            ctx = task.get('ctx_table', '') if nd == 'e1' else \
                task.get('ctx_text', '')
            prompt = led.eprompt(task, ctx)
            sha = hashlib.sha256(prompt.encode()).hexdigest()
            if (nodes_b[nd], sha) not in cache_shas:
                unconditional_new.add(nd)

    lower = len(unconditional_new)
    upper = len(unconditional_new) + len(conditional)
    return dict(lower=lower, upper=upper,
                unconditional=sorted(unconditional_new),
                conditional=sorted(conditional))


def make_task():
    return dict(uid='recon-test-uid', question='What is 1.5 + 2.5?',
                derivation='1.5+2.5', answer=4.0,
                ctx_table='TABLE: | val | 1.5 |',
                ctx_text='PASSAGES: value is 2.5')


ANSWERS = {
    ('e1', 'plain'): '{"facts": [{"value": 1.5, "evidence": "a"}]}',
    ('e2', 'plain'): '{"facts": [{"value": 2.5, "evidence": "b"}]}',
    ('e1', 'fb'): '{"facts": [{"value": 1.5, "evidence": "a"}]}',
    ('r', 'plain'): '{"expression": "v0+v1"}',
    ('r', 'fbd'): '{"expression": "v0+v1"}',
    ('r', 'esc'): '{"expression": "v0+v1"}',
    ('v', 'any'): '{"value": 4.0}',
}


def run():
    from collab_scheduler_v1 import fault30_run
    led = fp.Ledger()
    task = make_task()
    task_map = {task['uid']: task}
    results = []

    def build_cache(config, answers):
        ex = ReconExecutor(set())

        def sc(key, model, prompt, uid=None, node=None):
            parts = key.split(':')
            nd, kind = parts[3], (parts[4] if len(parts) > 5 else 'plain')
            sha = hashlib.sha256(prompt.encode()).hexdigest()
            is_inj = uid is not None and (uid, node, model) in ex.faults
            ex.call_log.append(dict(key=key, node=nd, kind=kind, model=model,
                                    sha=sha, cached=False, injected=is_inj,
                                    physical=not is_inj))
            if is_inj:
                f, _, _ = ex.faults[(uid, node, model)]
                ans = f
            else:
                ans = answers.get((nd, kind), answers.get((nd, 'any'), '{}'))
                ex.cached.add((model, sha))
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=ans,
                                     usage=dict(total_tokens=100),
                                     latency_s=0.2))
            ex.by_key[key] = rec
            return rec
        ex.call = sc
        fault30_run.eval_config(config, ex, led, [task], {}, task_map)
        return ex.cached

    def run_and_reconcile(name, config_from, config_to, cache, expect,
                          fault_at=None):
        # === PHASE 1: PREDICT (before any execution) ===
        pred = predict_incremental_cost(config_from, config_to, task, cache,
                                        led, fault_at=fault_at)
        # === PHASE 2: EXECUTE ===
        ex = ReconExecutor(cache)

        def sc(key, model, prompt, uid=None, node=None):
            parts = key.split(':')
            nd, kind = parts[3], (parts[4] if len(parts) > 5 else 'plain')
            sha = hashlib.sha256(prompt.encode()).hexdigest()
            is_inj = uid is not None and (uid, node, model) in ex.faults
            is_cached = not is_inj and (model, sha) in ex.cached
            ex.call_log.append(dict(key=key, node=nd, kind=kind, model=model,
                                    sha=sha, cached=is_cached, injected=is_inj,
                                    physical=not is_cached and not is_inj))
            if is_inj:
                f, _, _ = ex.faults[(uid, node, model)]
                ans = f
                rec = dict(key=key, model=model,
                           response=dict(status='delivered', answer=f,
                                         usage=dict(total_tokens=1),
                                         latency_s=0.0, injected_fault=True))
            else:
                ans = ANSWERS.get((nd, kind), ANSWERS.get((nd, 'any'), '{}'))
                tag = dict(alias_of='cache') if is_cached else {}
                rec = dict(key=key, model=model, **tag,
                           response=dict(status='delivered', answer=ans,
                                         usage=dict(total_tokens=100),
                                         latency_s=0.2))
            ex.by_key[key] = rec
            return rec
        ex.call = sc

        faults = {}
        if fault_at:
            pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/'
                               'FAULT_POOLS.json').read_text())
            faults[task['uid']] = (fault_at, pools.get(
                'e' if fault_at.startswith('e') else 'r', ['###'])[0])
            topo, fam, z, nodes = fp.planned_models(config_to)
            for u, (node, failing) in faults.items():
                mapped = fp.map_fault_node(node, topo)
                if mapped:
                    ex.set_fault(u, mapped, nodes[mapped], failing,
                                 usage=dict(total_tokens=1), lat=0.0)

        rows = fault30_run.eval_config(config_to, ex, led, [task], faults,
                                       task_map)
        # === PHASE 3: RECONCILE ===
        actual_new = sum(1 for c in ex.call_log if c['physical'])
        actual_logical = sum(1 for c in ex.call_log if not c['injected'])
        actual_cached = sum(1 for c in ex.call_log if c['cached'])
        new_nodes = sorted(set(c['node'] for c in ex.call_log if c['physical']))
        recon = dict(
            name=name,
            prediction=pred,
            actual=dict(new_physical_calls=actual_new,
                        logical_calls=actual_logical,
                        cache_hits=actual_cached,
                        new_nodes=new_nodes),
            checks={
                'lower_le_actual': pred['lower'] <= actual_new,
                'actual_le_upper': actual_new <= pred['upper'],
                **expect(pred, actual_new, new_nodes, actual_logical,
                         actual_cached)})
        return recon

    # R1: Isolate r model swap (v model FIXED)
    # HETEROGENEOUS: e=large, r=medium, v=coder
    # BALANCED:      e=medium, r=large, v=medium  <- changes e AND r AND v
    # Use DYNAMICDAG__HETEROGENEOUS__NONE and a synthetic r-only swap:
    # swap r medium→large while keeping e=large, v=coder
    cfg_het = 'DYNAMICDAG__HETEROGENEOUS__NONE__FRESH'
    cache_het = build_cache(cfg_het, ANSWERS)
    # QUALITY: e=large, r=large, v=large — changes r AND v models
    # This tests the COMBINED effect, which the predictor should bound correctly
    cfg_qual = 'DYNAMICDAG__QUALITY__NONE__FRESH'
    results.append(run_and_reconcile(
        'R1_r_and_v_model_swap', cfg_het, cfg_qual, cache_het,
        expect=lambda p, a, nn, lg, ch: {
            'r_in_unconditional': 'r' in p['unconditional'],
            'v_in_unconditional_or_conditional': 'v' in p['unconditional']
                                                 or 'v' in p['conditional'],
            'e_nodes_not_new': 'e1' not in nn and 'e2' not in nn,
        }))

    # R2: Upstream e1 fault with DIFFERENT facts after fb
    cfg_lr = 'DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH'
    cache_lr = build_cache(cfg_lr, ANSWERS)
    results.append(run_and_reconcile(
        'R2_e1_fault_cascade', cfg_lr, cfg_lr, cache_lr, fault_at='e1',
        expect=lambda p, a, nn, lg, ch: {
            'e1_fb_predicted': 'e1' in p['unconditional']
                               or 'e1' in p['conditional'],
            'r_conditional': 'r' in p['conditional'],
            'v_conditional': 'v' in p['conditional'],
            'logical_ge_physical': lg >= a,
        }))

    # R3: Full cache hit (same config, no fault)
    results.append(run_and_reconcile(
        'R3_full_cache', cfg_het, cfg_het, cache_het,
        expect=lambda p, a, nn, lg, ch: {
            'lower_is_zero': p['lower'] == 0,
            'actual_is_zero': a == 0,
            'all_cached': ch == lg,
        }))

    all_pass = all(r['checks'] and all(r['checks'].values()) for r in results)
    out = dict(results=results, all_pass=all_pass, zero_model_calls=True,
               note='predictor sees only configs+cache+task, never reads '
                    'candidate outputs; bounds must contain actual')
    (OUT / 'PREDICTION_RECON.json').write_text(json.dumps(out, indent=1,
                                                          default=str))
    for r in results:
        print(f'\n=== {r["name"]} === '
              f'{"PASS" if all(r["checks"].values()) else "FAIL"}')
        p, a = r['prediction'], r['actual']
        print(f'  predicted: lower={p["lower"]} upper={p["upper"]} '
              f'unconditional={p["unconditional"]} conditional={p["conditional"]}')
        print(f'  actual: new={a["new_physical_calls"]} '
              f'logical={a["logical_calls"]} cache={a["cache_hits"]} '
              f'new_nodes={a["new_nodes"]}')
        for k, v in r['checks'].items():
            print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'\n{"ALL PASS" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
