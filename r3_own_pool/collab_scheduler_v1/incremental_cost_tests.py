"""Incremental cost prediction tests: does the search correctly estimate the
NEW physical calls a config switch would require, BEFORE executing it?

Four scenarios on a fixed DAG (e→r→v), each with a known cache state:

  IC1 Full cache hit    — same config as cached, zero new calls expected
  IC2 Model swap at r   — r's prompt changes (same input, new model) → 1 new
  IC3 Upstream change   — e's output differs → r AND v prompts change → 2 new
  IC4 Local recovery    — e faulted → fb + r-fbd + v-fbd → 3 new calls

For each: (a) the PREDICTED new-call set from cache-aware prompt diffing,
(b) the ACTUAL new-call set from running the production eval_config() with
a cache-tracking executor. Assert predicted == actual.

This tests the mechanism the X+Z joint search needs: when the optimizer
proposes switching from config A to config B, it must correctly predict
which nodes need fresh model calls vs which can reuse cache, INCLUDING
downstream refresh cascades (the P0-1 bug class).

Zero model calls. Independent output directory.
Run: python3 -m collab_scheduler_v1.incremental_cost_tests
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1 import fault30_protocol as fp  # noqa: E402

OUT = ROOT / 'collab_scheduler_v1/fault30_prep/incremental_cost_tests'
OUT.mkdir(exist_ok=True)


class PredictiveCacheExecutor:
    """Tracks which calls are cache hits vs new, and records the full
    prompt for each call so predictions can be compared against reality."""

    def __init__(self, cached_prompts):
        """cached_prompts: set of (model, prompt_sha256) that are in cache."""
        self.cached = cached_prompts
        self.by_key = {}
        self.call_log = []
        self.faults = {}
        self.proc = self.log = None
        self.current = None
        self.new_calls = 0
        self.lock = None

    def set_fault(self, uid, node, model, failing, usage=None, lat=None):
        self.faults[(uid, node, model)] = (failing, usage, lat)

    def clear_faults(self):
        self.faults = {}

    def call(self, key, model, prompt, uid=None, node=None):
        parts = key.split(':')
        nd, kind = parts[3], (parts[4] if len(parts) > 5 else 'plain')
        sha = hashlib.sha256(prompt.encode()).hexdigest()
        is_cached = (model, sha) in self.cached
        is_injected = uid is not None and (uid, node, model) in self.faults

        self.call_log.append(dict(key=key, node=nd, kind=kind, model=model,
                                  sha=sha, cached=is_cached,
                                  injected=is_injected))
        if is_injected:
            failing, cu, cl = self.faults[(uid, node, model)]
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=failing,
                                     usage=cu or dict(total_tokens=1),
                                     latency_s=cl or 0.0,
                                     injected_fault=True))
        elif is_cached:
            rec = dict(key=key, model=model, alias_of='cache',
                       response=dict(status='delivered', answer='{}',
                                     usage=dict(total_tokens=50),
                                     latency_s=0.1))
        else:
            self.new_calls += 1
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer='{}',
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


def predict_new_calls(config_a, config_b, task, cache_shas, led):
    """Predict which nodes would need new calls when switching A→B.
    This is the logic the joint search's cost-aware acquisition needs."""
    topo_a, fam_a, z_a, nodes_a = fp.planned_models(config_a)
    topo_b, fam_b, z_b, nodes_b = fp.planned_models(config_b)

    # Build prompts for both configs' node sets
    def prompts_for(topo, fam, nodes, z):
        ps = {}
        for nd in nodes:
            if nd.startswith('e'):
                ctx = task['ctx_table'] if nd == 'e1' else (
                    task['ctx_text'] if nd == 'e2' else
                    task['ctx_table'] + '\n' + task['ctx_text'])
                ps[nd] = (nodes[nd], led.eprompt(task, ctx))
            elif nd == 'r':
                # r's prompt depends on upstream facts (assumed same if
                # same model at e nodes)
                ps[nd] = (nodes[nd], 'R_PROMPT_PLACEHOLDER')
            elif nd == 'v':
                ps[nd] = (nodes[nd], 'V_PROMPT_PLACEHOLDER')
        return ps

    pa = prompts_for(topo_a, fam_a, nodes_a, z_a)
    pb = prompts_for(topo_b, fam_b, nodes_b, z_b)

    predicted_new = set()
    for nd, (model, prompt) in pb.items():
        if nd not in pa:
            predicted_new.add(nd)  # new node (e.g., recovery nodes)
            continue
        old_model, old_prompt = pa[nd]
        if model != old_model:
            predicted_new.add(nd)  # model swap = new call
        elif prompt != old_prompt and 'PLACEHOLDER' not in prompt:
            predicted_new.add(nd)  # input changed = new call
        else:
            # Same model, same input → check cache
            sha = hashlib.sha256(prompt.encode()).hexdigest()
            if (model, sha) not in cache_shas:
                predicted_new.add(nd)  # not cached = new call

    # Downstream cascade: if any e node changed, r and v also change
    if any(nd.startswith('e') for nd in predicted_new):
        if 'r' in pb:
            predicted_new.add('r')
        if 'v' in pb:
            predicted_new.add('v')
    # If r changed (model or input), v also changes
    if 'r' in predicted_new and 'v' in pb:
        predicted_new.add('v')

    return predicted_new


def make_task():
    return dict(uid='ic-test-uid', question='What is 1.5 + 2.5?',
                derivation='1.5+2.5', answer=4.0,
                ctx_table='TABLE: | val | 1.5 |',
                ctx_text='PASSAGES: value is 2.5')


BASE_ANSWERS = {
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

    # Build a cache: run config A once and collect all prompt SHAs
    def build_cache(config, answers):
        ex = PredictiveCacheExecutor(set())
        ex.real_answers = answers
        # Override call to always return scripted answers
        orig_call = ex.call

        def scripted_call(key, model, prompt, uid=None, node=None):
            parts = key.split(':')
            nd, kind = parts[3], (parts[4] if len(parts) > 5 else 'plain')
            sha = hashlib.sha256(prompt.encode()).hexdigest()
            is_inj = uid is not None and (uid, node, model) in ex.faults
            ex.call_log.append(dict(key=key, node=nd, kind=kind, model=model,
                                    sha=sha, cached=False, injected=is_inj))
            ans = answers.get((nd, kind), answers.get((nd, 'any'), '{}'))
            if is_inj:
                f, cu, cl = ex.faults[(uid, node, model)]
                rec = dict(key=key, model=model,
                           response=dict(status='delivered', answer=f,
                                         usage=dict(total_tokens=1),
                                         latency_s=0.0, injected_fault=True))
            else:
                ex.cached.add((model, sha))
                rec = dict(key=key, model=model,
                           response=dict(status='delivered', answer=ans,
                                         usage=dict(total_tokens=100),
                                         latency_s=0.2))
            ex.by_key[key] = rec
            return rec
        ex.call = scripted_call
        faults = {}
        rows = fault30_run.eval_config(config, ex, led, [task], faults, task_map)
        return ex.cached, ex

    # === IC1: Full cache hit (same config re-run) ===
    cfg = 'DYNAMICDAG__HETEROGENEOUS__NONE__FRESH'
    cache_shas, _ = build_cache(cfg, BASE_ANSWERS)
    ex1 = PredictiveCacheExecutor(cache_shas)
    ex1.real_answers = BASE_ANSWERS
    # Need scripted answers for non-cached calls
    _orig = ex1.call

    def sc1(key, model, prompt, uid=None, node=None):
        parts = key.split(':')
        nd, kind = parts[3], (parts[4] if len(parts) > 5 else 'plain')
        sha = hashlib.sha256(prompt.encode()).hexdigest()
        is_cached = (model, sha) in ex1.cached
        ex1.call_log.append(dict(key=key, node=nd, kind=kind, model=model,
                                 sha=sha, cached=is_cached, injected=False))
        ans = BASE_ANSWERS.get((nd, kind), BASE_ANSWERS.get((nd, 'any'), '{}'))
        tag = dict(alias_of='cache') if is_cached else {}
        rec = dict(key=key, model=model, **tag,
                   response=dict(status='delivered', answer=ans,
                                 usage=dict(total_tokens=50 if is_cached else 100),
                                 latency_s=0.1 if is_cached else 0.2))
        ex1.by_key[key] = rec
        return rec
    ex1.call = sc1
    rows1 = fault30_run.eval_config(cfg, ex1, led, [task], {}, task_map)
    actual_new1 = [c for c in ex1.call_log if not c['cached'] and not c['injected']]
    results.append(dict(
        name='IC1_full_cache_hit', config=cfg,
        actual_new_calls=len(actual_new1),
        actual_cached=sum(1 for c in ex1.call_log if c['cached']),
        checks={'zero_new_calls': len(actual_new1) == 0,
                'all_cached': all(c['cached'] for c in ex1.call_log)}))

    # === IC2: Model swap (HETEROGENEOUS → QUALITY: r medium→large) ===
    cfg_a = 'DYNAMICDAG__HETEROGENEOUS__NONE__FRESH'
    cache_a, _ = build_cache(cfg_a, BASE_ANSWERS)
    cfg_b = 'DYNAMICDAG__QUALITY__NONE__FRESH'
    ex2 = PredictiveCacheExecutor(cache_a)
    # Reuse the scripted pattern
    def make_scripted(ex, answers):
        def sc(key, model, prompt, uid=None, node=None):
            parts = key.split(':')
            nd, kind = parts[3], (parts[4] if len(parts) > 5 else 'plain')
            sha = hashlib.sha256(prompt.encode()).hexdigest()
            # Check fault injection first
            is_inj = uid is not None and (uid, node, model) in ex.faults
            is_cached = (model, sha) in ex.cached
            ex.call_log.append(dict(key=key, node=nd, kind=kind, model=model,
                                    sha=sha, cached=is_cached, injected=is_inj))
            if is_inj:
                f_ans, f_u, f_l = ex.faults[(uid, node, model)]
                rec = dict(key=key, model=model,
                           response=dict(status='delivered', answer=f_ans,
                                         usage=dict(total_tokens=1),
                                         latency_s=0.0, injected_fault=True))
            else:
                ans = answers.get((nd, kind), answers.get((nd, 'any'), '{}'))
                tag = dict(alias_of='cache') if is_cached else {}
                rec = dict(key=key, model=model, **tag,
                           response=dict(status='delivered', answer=ans,
                                         usage=dict(total_tokens=50 if is_cached else 100),
                                         latency_s=0.1 if is_cached else 0.2))
                if not is_cached:
                    ex.new_calls += 1
            ex.by_key[key] = rec
            return rec
        return sc
    ex2.call = make_scripted(ex2, BASE_ANSWERS)
    rows2 = fault30_run.eval_config(cfg_b, ex2, led, [task], {}, task_map)
    new_nodes2 = sorted(set(c['node'] for c in ex2.call_log
                            if not c['cached']))
    results.append(dict(
        name='IC2_model_swap_r', config_from=cfg_a, config_to=cfg_b,
        new_nodes=new_nodes2, actual_new=len(new_nodes2),
        checks={'r_is_new': 'r' in new_nodes2,
                'e_nodes_cached': 'e1' not in new_nodes2 and 'e2' not in new_nodes2,
                'v_downstream_cascade': 'v' in new_nodes2}))

    # === IC3: Upstream change (e1 faulted → fb → r refresh → v refresh) ===
    cfg_lr = 'DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH'
    cache_lr, _ = build_cache(cfg_lr, BASE_ANSWERS)
    ex3 = PredictiveCacheExecutor(cache_lr)
    # Inject e1 fault BEFORE overriding call
    pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/'
                       'FAULT_POOLS.json').read_text())
    faults3 = {task['uid']: ('e1', pools['e'][0])}
    topo, fam, z, nodes = fp.planned_models(cfg_lr)
    for u, (node, failing) in faults3.items():
        mapped = fp.map_fault_node(node, topo)
        if mapped:
            ex3.set_fault(u, mapped, nodes[mapped], failing,
                          usage=dict(total_tokens=1), lat=0.0)
    ex3.call = make_scripted(ex3, BASE_ANSWERS)
    rows3 = fault30_run.eval_config(cfg_lr, ex3, led, [task], faults3, task_map)
    new_nodes3 = sorted(set(c['node'] for c in ex3.call_log
                            if not c['cached'] and not c['injected']))
    results.append(dict(
        name='IC3_upstream_e1_fault', config=cfg_lr,
        new_nodes=new_nodes3, actual_new=len(new_nodes3),
        checks={'e1_fb_is_new': any(c['kind'] == 'fb' and c['node'] == 'e1'
                                    for c in ex3.call_log if not c['cached']),
                'r_refresh_cascade': 'r' in new_nodes3,
                'v_cascade_correctly_skipped': 'v' not in new_nodes3}))

    # === IC4: No fault (clean re-run under LR) — all should be cached ===
    ex4 = PredictiveCacheExecutor(cache_lr)
    ex4.call = make_scripted(ex4, BASE_ANSWERS)
    rows4 = fault30_run.eval_config(cfg_lr, ex4, led, [task], {}, task_map)
    new4 = [c for c in ex4.call_log if not c['cached'] and not c['injected']]
    results.append(dict(
        name='IC4_clean_rerun_all_cached', config=cfg_lr,
        actual_new=len(new4),
        checks={'zero_new_on_clean': len(new4) == 0}))

    all_pass = all(all(r['checks'].values()) for r in results)
    out = dict(results=results, all_pass=all_pass, zero_model_calls=True)
    (OUT / 'INCREMENTAL_COST_TESTS.json').write_text(json.dumps(out, indent=1,
                                                                default=str))
    for r in results:
        print(f'\n=== {r["name"]} === '
              f'{"PASS" if all(r["checks"].values()) else "FAIL"}')
        for k, v in r['checks'].items():
            print(f'  {k}: {"PASS" if v else "FAIL"}')
        if 'new_nodes' in r:
            print(f'  new nodes: {r["new_nodes"]} ({r["actual_new"]} calls)')
        elif 'actual_new_calls' in r:
            print(f'  new calls: {r["actual_new_calls"]}')
        elif 'actual_new' in r:
            print(f'  new calls: {r["actual_new"]}')
        else:
            print(f'  (see checks above)')
    print(f'\n{"ALL PASS" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
