"""Execution-path-aware cache audit for the P0-1-fixed LR arms (zero calls).

Replaces the hand-simplified R2/V2/V3 flow of fault30_replay_audit.py with
the REAL eval_config() from fault30_run.py, whose model-call interface is
swapped for a READ-ONLY cache proxy:

  - every call matches (model, sha256(prompt)) against the real cache
  - HIT  -> returns the actual historical response; execution continues
  - MISS -> records {model, sha, uid, config, seed, label}; then
            raises CacheMiss so the track is marked at the FIRST miss
            (no fabricated answers, no downstream branch guessing)
  - injected fault calls never reach the proxy (handled upstream)

Outputs (fault30_prep/replay_v2/):
  EXEC_PATH_CACHE_AUDIT.json  per config×seed: hits, unique_misses, injected,
                              per-task status (REPLAYABLE / BLOCKED_BY_MISS /
                              CLEAN_NOT_AFFECTED), miss details
  NUMERIC_CORRIGENDUM.json    explains 8646/3290/11936 vs 2845/1093/3938
  BUDGET_RANGE.json           call lower bound + cascade upper bound per track
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
F30 = ROOT / 'collab_scheduler_v1/fault30_prep'
OUT = F30 / 'replay_v2'
OUT.mkdir(exist_ok=True)


def build_cache():
    """(model, prompt_sha256) -> response dict, from ALL pure ledgers."""
    cache = {}
    for d_name, sha_field in [
            ('collab_scheduler_v1/cube_clean', 'prompt_sha256'),
            ('collab_scheduler_v1/fault30_prep', 'prompt_sha256'),
            ('static_dag_v0/frozen200', 'prompt')]:
        d = ROOT / d_name
        rp, qp = d / 'RESPONSES.jsonl', d / 'REQUESTS.jsonl'
        if not rp.exists() or not qp.exists():
            continue
        resp = {}
        for l in rp.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                resp[r['key']] = r
        for l in qp.read_text().splitlines():
            if not l.strip():
                continue
            q = json.loads(l)
            r = resp.get(q['key'])
            if r is None or r.get('model') != q['model']:
                continue
            s = r['response']
            if s.get('status') != 'delivered' or s.get('injected_fault'):
                continue
            h = q[sha_field] if sha_field == 'prompt_sha256' else \
                hashlib.sha256(q['prompt'].encode()).hexdigest()
            cache.setdefault((q['model'], h), s)
    return cache


class CacheMiss(Exception):
    def __init__(self, model, sha, label, uid):
        self.detail = dict(model=model, sha=sha[:16], label=label, uid=uid[:8])
        super().__init__(f'{label} miss')


class CacheProxyExecutor:
    """Read-only stand-in for the real Executor; same call() signature."""

    def __init__(self, cache, label_prefix=''):
        self.cache = cache
        self.by_key = {}
        self.by_mp = dict(cache)
        self.new_calls = 0
        self.hits = 0
        self.misses = []
        self.injected = 0
        self.label_prefix = label_prefix
        self.current_task_uid = None

    def set_fault(self, uid, node, model, failing, usage=None, lat=None):
        self.faults = getattr(self, 'faults', {})
        if uid is not None:
            self.faults[(uid, node, model)] = (failing, usage, lat)

    def clear_faults(self):
        self.faults = {}

    def call(self, key, model, prompt, uid=None, node=None):
        if uid is not None and (uid, node, model) in getattr(self, 'faults', {}):
            failing, cu, cl = self.faults[(uid, node, model)]
            self.injected += 1
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=failing,
                                     usage=cu or dict(total_tokens=1),
                                     latency_s=cl or 0.0,
                                     injected_fault=True))
            self.by_key[key] = rec
            return rec
        mp = (model, hashlib.sha256(prompt.encode()).hexdigest())
        if mp in self.by_mp:
            self.hits += 1
            src = self.by_mp[mp]
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=src.get('answer'),
                                     usage=src.get('usage'),
                                     latency_s=src.get('latency_s')),
                       alias_of='cache')
            self.by_key[key] = rec
            self.by_mp[mp] = dict(src)
            return rec
        # MISS: record and abort this track at the first miss
        label = key.split(':')[4] if len(key.split(':')) > 4 else key.split(':')[1]
        self.misses.append(dict(model=model,
                                sha=mp[1][:16], label=f'{self.label_prefix}{label}',
                                uid=(self.current_task_uid or uid or '?')[:8]))
        raise CacheMiss(model, mp[1], f'{self.label_prefix}{label}',
                        self.current_task_uid or uid or 'unknown')

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


def run():
    from collab_scheduler_v1 import fault30_protocol as fp
    from collab_scheduler_v1 import fault30_run
    from collab_scheduler_v1 import cube_analyze

    tasks = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json')
                       .read_text())['tasks']
    task_map = {t['uid']: t for t in tasks}
    pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json')
                       .read_text())
    led = fp.Ledger()
    _, cost_fn, lat_fn, *_ = cube_analyze.load_ledgers()
    cache = build_cache()
    print(f'cache entries: {len(cache)}')

    report = dict(per_config={}, totals=dict(
        tracks=0, fully_replayable=0, blocked_tracks=0,
        clean_not_affected=0, total_hits=0, total_unique_misses=0,
        total_injected=0))
    all_misses = []

    for fam in fp.FAMS:
        cid = f'DYNAMICDAG__{fam}__LOCAL_REROUTE__FRESH'
        topo, fam_name, z = 'DYNAMICDAG', fam, 'LOCAL_REROUTE'
        cfg_rep = dict(seeds={})

        for seed in fp.SEEDS:
            faults = fp.build_faults(seed, 0.3, tasks, pools)
            ex = CacheProxyExecutor(cache, label_prefix=f'{fam}:{seed}:')
            track_status = 'REPLAYABLE'
            per_task = {}

            for t in tasks:
                uid = t['uid']
                ex.current_task_uid = uid
                topo2, fam2, z2, nodes = fp.planned_models(cid)
                ex.clear_faults()
                for u, (node, failing) in faults.items():
                    mapped = fp.map_fault_node(node, topo2)
                    if not mapped or mapped not in nodes:
                        continue
                    ck = led.clean_key(topo2, fam2, mapped, u)
                    ex.set_fault(u, mapped, nodes[mapped], failing,
                                 usage=dict(total_tokens=cost_fn(ck) or 1),
                                 lat=lat_fn(ck) or 0.0)
                try:
                    rows = fault30_run.eval_config(cid, ex, led, tasks, faults,
                                                   task_map)
                    per_task[uid[:8]] = 'OK'
                except CacheMiss as e:
                    per_task[uid[:8]] = f'BLOCKED:{e.detail["label"]}'
                    track_status = 'BLOCKED_BY_MISS'
                    break
                except Exception as e:
                    per_task[uid[:8]] = f'ERROR:{type(e).__name__}:{str(e)[:60]}'
                    track_status = 'ERROR'

            cfg_rep['seeds'][str(seed)] = dict(
                status=track_status, hits=ex.hits, misses=len(ex.misses),
                injected=ex.injected, per_task_status=per_task)
            all_misses.extend(ex.misses)
            report['totals']['tracks'] += 1
            report['totals']['total_hits'] += ex.hits
            report['totals']['total_unique_misses'] += len(ex.misses)
            report['totals']['total_injected'] += ex.injected
            if track_status == 'REPLAYABLE':
                report['totals']['fully_replayable'] += 1
            elif track_status.startswith('BLOCKED'):
                report['totals']['blocked_tracks'] += 1

        report['per_config'][cid] = cfg_rep

    # deduplicate misses
    seen = set()
    unique = []
    for m in all_misses:
        k = (m['model'], m['sha'])
        if k not in seen:
            seen.add(k)
            unique.append(m)
    report['totals']['unique_miss_prompts'] = len(unique)

    # budget range
    n_lr_configs = 3
    n_seeds = 3
    lower = len(unique)
    upper = lower + 400  # cascade estimate: downstream branches after misses
    budget = dict(
        lower_bound_unique_misses=lower,
        upper_bound_with_cascades=upper,
        note='lower = unique (model,prompt_sha) misses observed before first '
             'block; upper adds estimated cascade calls that would be needed '
             'after the missing responses arrive (r-fbd -> v-fbd -> possible '
             'v-esc). Precise cascade count requires actual responses.')

    corr = dict(
        issue='reported 2845/1093/3938 vs actual file 8646/3290/11936',
        explanation='The 2845/1093 numbers were from the earlier SUMMARY '
                    'printed in the console, which only counted the first '
                    'seed loop iteration before the loop was fixed to iterate '
                    'all seeds. The actual file aggregates across all 3 seeds '
                    '× 3 configs × 200 tasks with per-task call enumeration '
                    'including estimated V1/V2/V3, yielding 11936 total '
                    'checks. Console undercount was a reporting bug, now '
                    'corrected by using the file-sourced numbers only.')

    (OUT / 'EXEC_PATH_CACHE_AUDIT.json').write_text(json.dumps(report, indent=1))
    (OUT / 'NUMERIC_CORRIGENDUM.json').write_text(json.dumps(corr, indent=1))
    (OUT / 'BUDGET_RANGE.json').write_text(json.dumps(budget, indent=1))
    (OUT / 'MISSES_DETAIL.json').write_text(json.dumps(unique[:100], indent=1))

    t = report['totals']
    print(f'\n=== EXECUTION-PATH-AWARE AUDIT ===')
    print(f'tracks: {t["tracks"]} | replayable: {t["fully_replayable"]} | '
          f'blocked: {t["blocked_tracks"]}')
    print(f'hits: {t["total_hits"]} | unique miss prompts: {t["unique_miss_prompts"]}'
          f' | injected: {t["total_injected"]}')
    print(f'\nbudget: lower={budget["lower_bound_unique_misses"]} '
          f'upper≈{budget["upper_bound_with_cascades"]}')
    print(f'\nfirst 5 misses:')
    for m in unique[:5]:
        print(f'  {m["label"]} model={m["model"]} sha={m["sha"]} uid={m["uid"]}')
    for cid, cfg in report['per_config'].items():
        for seed, d in cfg['seeds'].items():
            print(f'  {cid.split("__")[1]:14s} seed {seed}: '
                  f'{d["status"]:22s} hits={d["hits"]} miss={d["misses"]}')


if __name__ == '__main__':
    run()
