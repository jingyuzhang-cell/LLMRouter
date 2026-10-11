"""Calibration measurement — REAL model calls (Calibration GO).

Measures per-(node, model, condition): quality, tokens, latency.
Also measures model start/stop wall time and contention ratio.
Output: PRIORS_REAL_V1.json with per-entry provenance.

Budget: <=2,000 requests / <=2M tokens / <=4h wall.
Safety: GPU lock, reserve/settle budget, stop on any cap.
Run: CALIBRATION_EXECUTE=1 python3 -m deadline_reward_v1.calibrate_real
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

from collab_scheduler_v1 import fault30_protocol as fp
from static_dag_v0 import run as engine

HERE = Path(__file__).resolve().parent
OUT = HERE / 'calibration_runs'
PRIORS_OUT = HERE / 'PRIORS_REAL_V1.json'
LOCK = ROOT / 'collect/logs/local_gpu.lock'

MODELS = {'medium', 'large', 'coder'}
NODES = ('e1', 'e2', 'r', 'v')
MODEL_MENU = {'e1': MODELS, 'e2': MODELS, 'r': {'medium', 'large'},
              'v': {'coder', 'large'}}
CONDITIONS = ('clean', 'D1_e_empty', 'D3_r_unparseable', 'D5_v_fail')

BUDGET = dict(max_requests=2000, max_tokens=2000000, max_wall_s=14400)
CALLS_PER_CELL = 30

# Fault injections per condition
CORRUPT = {
    'D1_e_empty': {'e1': '{"facts": []}', 'e2': '{"facts": []}'},
    'D3_r_unparseable': {'r': '###SYNTHETIC UNPARSEABLE r-output###'},
    'D5_v_fail': {'v': '{"value": null}'},
}


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def append(path, obj):
    with open(path, 'a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def build_panel(n=50, seed=42):
    """Calibration task panel: disjoint from evaluation panels."""
    fz = ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json'
    tasks = json.loads(fz.read_text())['tasks']
    # Exclude evaluation-panel uids
    excluded = set()
    tp = ROOT / 'collab_scheduler_v1/joint_search_v1/review/TASK_PANEL_V1.json'
    if tp.exists():
        panel = json.loads(tp.read_text())
        for key in ('tasks_search', 'tasks_holdout'):
            excluded.update(t['uid'] for t in panel.get(key, []))
    candidates = [t for t in tasks if t['uid'] not in excluded]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:n]


def check_budget(b):
    if b['requests'] >= BUDGET['max_requests']:
        raise RuntimeError(f'Budget stop: requests {b["requests"]}')
    if b['tokens'] >= BUDGET['max_tokens']:
        raise RuntimeError(f'Budget stop: tokens {b["tokens"]}')
    if b['wall_s'] >= BUDGET['max_wall_s']:
        raise RuntimeError(f'Budget stop: wall {b["wall_s"]:.0f}s')


def main():
    if os.environ.get('CALIBRATION_EXECUTE') != '1':
        raise PermissionError('Requires CALIBRATION_EXECUTE=1')
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = OUT / 'CALIBRATION_LEDGER.jsonl'
    # no silent resume
    if ledger.exists():
        raise ValueError('Existing calibration ledger; explicit '
                         'reconciliation required')

    lock = LOCK.open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    budget = dict(requests=0, tokens=0, wall_s=0.0)
    start_wall = time.monotonic()
    panel = build_panel()
    led = fp.Ledger()
    panel_sha = hashlib.sha256(json.dumps(
        [t['uid'] for t in panel], sort_keys=True).encode()).hexdigest()
    append(ledger, dict(event='meta', panel_size=len(panel),
                        panel_sha256=panel_sha,
                        budget=BUDGET, calls_per_cell=CALLS_PER_CELL))

    results = {}
    switch_costs = {}

    try:
        for model in ('medium', 'large', 'coder'):
            # ---- start model & measure startup ----
            t0 = time.monotonic()
            proc, log, _ = engine.start_model(model)
            startup_s = time.monotonic() - t0
            append(ledger, dict(event='model_start', model=model,
                                startup_s=round(startup_s, 3)))
            switch_costs.setdefault(model, {})['start_s'] = startup_s
            try:
                applicable_nodes = [n for n in NODES
                                    if model in MODEL_MENU[n]]
                for node in applicable_nodes:
                    for cond in CONDITIONS:
                        # fault injection per condition
                        fault = CORRUPT.get(cond, {}).get(node)
                        cell_key = f'{node}|{model}|{cond}'
                        cell_data = []
                        for attempt in range(min(
                                CALLS_PER_CELL, len(panel))):
                            check_budget(budget)
                            task = panel[attempt % len(panel)]
                            # build the standard prompt for this node
                            if node in ('e1', 'e2'):
                                ctx = (task['ctx_table'] if node == 'e1'
                                       else task['ctx_text'])
                                prompt = led.eprompt(task, ctx)
                            elif node == 'r':
                                # feed clean facts (we're measuring the
                                # model's ability, not the cascade)
                                facts = {'facts': [
                                    {'value': 1.5},
                                    {'value': 2.5}]}
                                prompt = led.sprompt(task, facts)
                            else:
                                expr = '{"expression": "v0+v1"}'
                                prompt = led.vprompt(
                                    task,
                                    [{'value': 1.5}, {'value': 2.5}], expr)
                            # inject fault if this condition targets node
                            inject = (cond != 'clean' and fault is not None
                                      and cond.startswith(
                                          {'e1': 'D1', 'e2': 'D1',
                                           'r': 'D3', 'v': 'D5'}[node]))

                            # ---- REAL MODEL CALL ----
                            t_call = time.monotonic()
                            resp = engine.call_model(model, prompt)
                            lat_s = time.monotonic() - t_call
                            usage = resp.get('usage', {})
                            tot_tok = usage.get('total_tokens', 0)
                            answer = resp.get('answer', '')
                            if inject:
                                answer = fault  # corrupted

                            budget['requests'] += 1
                            budget['tokens'] += tot_tok
                            budget['wall_s'] = time.monotonic() - start_wall

                            cell_data.append(dict(
                                lat_s=round(lat_s, 4),
                                tokens=tot_tok, answer=answer[:100],
                                status=resp.get('status')))
                            append(ledger, dict(
                                event='call', cell=cell_key,
                                model=model, node=node, condition=cond,
                                attempt=attempt, uid=task['uid'],
                                lat_s=round(lat_s, 4), tokens=tot_tok,
                                status=resp.get('status'),
                                answer_head=answer[:60]))
                        results[cell_key] = cell_data
                        print(f'  {cell_key}: {len(cell_data)} calls, '
                              f'mean_lat={sum(d["lat_s"] for d in cell_data)/max(1,len(cell_data)):.3f}s',
                              flush=True)
            finally:
                # ---- stop model & measure stop time ----
                t0 = time.monotonic()
                engine.stop_model(proc, log)
                stop_s = time.monotonic() - t0
                append(ledger, dict(event='model_stop', model=model,
                                    stop_s=round(stop_s, 3)))
                switch_costs[model]['stop_s'] = stop_s

        status = 'COMPLETE'
    except BaseException as exc:
        status = f'INCOMPLETE: {repr(exc)}'
        raise
    finally:
        budget['wall_s'] = time.monotonic() - start_wall
        append(ledger, dict(event='summary', status=status, budget=budget))
        lock.close()

    # ---- build PRIORS_REAL_V1 ----
    priors = dict(
        version='PRIORS_REAL_V1', klass='calibrated',
        standards_sha256=sha_file(
            HERE / 'CALIBRATION_FREEZE_PREREQUISITES.json'),
        panel_sha256=panel_sha,
        switch_costs={m: dict(start_s=round(v['start_s'], 3),
                               stop_s=round(v['stop_s'], 3))
                      for m, v in switch_costs.items()},
        profiles={},
        calibration_provenance=dict(
            requests=budget['requests'], tokens=budget['tokens'],
            wall_s=round(budget['wall_s'], 1), status=status),
    )
    for cell_key, data in results.items():
        if not data:
            continue
        lats = sorted(d['lat_s'] for d in data)
        toks = sorted(d['tokens'] for d in data)
        n = len(data)

        def pct(arr, p):
            idx = min(int(math.ceil(p * len(arr))) - 1, len(arr) - 1)
            return arr[max(0, idx)]

        node, model, cond = cell_key.split('|')
        # quality: parseable + correct node-type output
        ok = 0
        for d in data:
            try:
                parsed = json.loads(d['answer'])
                if node in ('e1', 'e2'):
                    ok += 1 if isinstance(parsed.get('facts'), list) \
                        and parsed['facts'] else 0
                elif node == 'r':
                    ok += 1 if isinstance(parsed.get('expression'), str) else 0
                elif node == 'v':
                    ok += 1 if parsed.get('value') is not None else 0
            except (json.JSONDecodeError, AttributeError):
                pass
        priors['profiles'][cell_key] = dict(
            q_success=round(ok / max(1, n), 4), n_samples=n,
            lat_p50=round(pct(lats, 0.50), 4),
            lat_p90=round(pct(lats, 0.90), 4),
            lat_p95=round(pct(lats, 0.95), 4),
            tok_p50=pct(toks, 0.50), tok_p90=pct(toks, 0.90),
            tok_p95=pct(toks, 0.95),
        )
    PRIORS_OUT.write_text(json.dumps(priors, indent=1,
                                     ensure_ascii=False))
    print(json.dumps(dict(
        status=status, requests=budget['requests'],
        tokens=budget['tokens'],
        wall_s=round(budget['wall_s']), cells=len(results),
        output=str(PRIORS_OUT)), indent=1))
    return 0 if status == 'COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
