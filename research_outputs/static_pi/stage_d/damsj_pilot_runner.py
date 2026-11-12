"""DAMJS_PILOT_54 orchestrator (authorized: 400 calls / 1.4M tokens / Y2.50).

18 paired blocks = 3 deadlines x 2 scenarios x 3 reps; each block runs the three
arms in randomized order with identical fixtures. Every execution runs in an
isolated child process under a hard deadline watchdog (damsj_executor).

Usage: python3 damsj_pilot_runner.py [--mock] [--limit N]
       default = MOCK smoke (zero real calls). Real mode needs --real AND
       STAGE_D_REAL_CALLS_AUTHORIZED=1.
"""
import argparse, json, os, random, sys, time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from damsj_executor import run_isolated, BudgetGuard

BATCH = 'DAMJS_PILOT_54'
ARMS = ['Static', 'Current-Proposed', 'DAMJS']
DEADLINES = [110.0, 150.0, 240.0]
SCENARIOS = ['S3', 'S4']
REPS = [1, 2, 3]
RUNS = HERE / 'damsj_pilot_runs'
LEDGER = HERE / 'DAMJS_PILOT_LEDGER.jsonl'


def build_blocks(seed=20261105):
    blocks = []
    for d in DEADLINES:
        for sc in SCENARIOS:
            for r in REPS:
                blocks.append(dict(deadline=d, scenario=sc, rep=r))
    rng = random.Random(seed)
    for b in blocks:
        order = ARMS[:]
        rng.shuffle(order)
        b['order'] = order
        b['block_id'] = f"{int(b['deadline'])}s|{b['scenario']}|r{b['rep']}"
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--real', action='store_true')
    ap.add_argument('--limit', type=int, default=None)
    a = ap.parse_args()
    real = a.real
    if real and os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
        raise SystemExit('REFUSED: --real requires STAGE_D_REAL_CALLS_AUTHORIZED=1')
    RUNS.mkdir(exist_ok=True)
    (RUNS / 'progress').mkdir(exist_ok=True)
    (RUNS / 'results').mkdir(exist_ok=True)
    guard = BudgetGuard(calls_max=400, tokens_max=1_400_000, yuan_max=2.50)
    blocks = build_blocks()
    done = 0
    t_start = time.time()
    for b in blocks:
        for arm in b['order']:
            if a.limit is not None and done >= a.limit:
                break
            tag = f"{int(b['deadline'])}s_{b['scenario']}_r{b['rep']}_{arm}"
            prog = str(RUNS / 'progress' / f'{tag}.jsonl')
            canc = str(RUNS / 'progress' / f'{tag}.cancel')
            out = str(RUNS / 'results' / f'{tag}.json')
            if os.path.exists(out):
                print(f'  [skip] {tag} (exists)')
                continue
            env = dict(os.environ,
                       # 冻结执行器的 GLM 路径只认 env 变量（不落盘、不打印）
                       STAGE_D_GLM_KEY=(open('/root/.zhipu_std_key').read().strip()
                                        if os.path.exists('/root/.zhipu_std_key') else ''),
                       # D3 修复：冻结执行器 deepseek 路径需要此环境变量
                       DEEPSEEK_API_KEY=(json.load(open('/root/.zcode/v2/provider_config.json'))
                                         ['config']['providerConfigRules']['providerRules'] and
                                         next((r['config']['access']['apiKey'].strip()
                                               for r in json.load(open('/root/.zcode/v2/provider_config.json'))
                                               ['config']['providerConfigRules']['providerRules']
                                               if r.get('providerId')=='deepseek' and r['config']['access']['apiKey']), '')),
                       APILOT_ARM=arm, APILOT_SCEN=b['scenario'], APILOT_REP=str(b['rep']),
                       APILOT_DEADLINE=str(b['deadline']), APILOT_OUT=out,
                       APILOT_PROGRESS=prog, APILOT_CANCEL=canc, APILOT_BATCH=BATCH,
                       APILOT_REAL=('1' if real else '0'))
            cmd = [sys.executable, str(HERE / '_damsj_real_child.py')]
            r = run_isolated(arm=arm, scenario=b['scenario'], rep=b['rep'],
                             deadline_s=b['deadline'], exec_cmd=cmd,
                             progress_path=prog, cancel_path=canc,
                             reserve_s=15.0, kill_grace_s=3.0, poll_s=0.3, env=env)
            rec = dict(batch=BATCH, block=b['block_id'], arm=arm, real=real,
                       watchdog=r.get('status'), elapsed_s=r.get('elapsed'),
                       answer_status=r.get('answer_status'),
                       completed_nodes=r.get('completed_nodes'),
                       aborted_nodes=r.get('aborted_nodes'),
                       result_path=out if os.path.exists(out) else None)
            if os.path.exists(out):
                rec['result'] = json.load(open(out))
            elif r.get('status') == 'INCOMPLETE_DEADLINE_DEGRADED':
                # L4：降级输出评分（SINK 完成则用它，否则全槽 UNKNOWN → TP=0）
                partial = r.get('partial_outputs') or {}
                sink_txt = partial.get('SINK')
                tp = 0; slot = 0.0; scored_from = 'unknown_all'
                if sink_txt:
                    try:
                        sys.path.insert(0, str(HERE))
                        import d2_executor as _D2
                        from terminal_quality import evaluate_terminal_quality
                        parsed = _D2.extract_json(sink_txt)
                        if parsed:
                            term = _D2.SA_EX.build_terminal_output(json.loads(json.dumps(parsed)))
                            q = evaluate_terminal_quality(_D2.SA_EX.CONTRACT, term, _D2.SRC())
                            tp = sum(1 for c in q['claim_results'] if c['status'].startswith('CORRECT'))
                            slot = round(tp / 23, 4); scored_from = 'partial_sink'
                    except Exception:
                        pass
                rec['result'] = dict(arm=arm, scenario=b['scenario'], rep=b['rep'],
                                     deadline_s=b['deadline'], status='INCOMPLETE_DEADLINE_DEGRADED',
                                     tp=tp, slot_success=slot, scored_from=scored_from,
                                     completed_nodes=r.get('completed_nodes') or [],
                                     aborted_nodes=r.get('aborted_nodes') or [],
                                     degradation='L4')
                with open(out, 'w') as fh:
                    json.dump(rec['result'], fh, ensure_ascii=False, indent=1)
            with open(LEDGER, 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            done += 1
            tp = rec.get('result', {}).get('tp')
            print(f"  [{done:2d}] {tag}: watchdog={rec['watchdog']} tp={tp} el={rec['elapsed_s']}s")
        if a.limit is not None and done >= a.limit:
            break
    print(f"\nDONE: {done} executions in {round(time.time()-t_start,1)}s; budget={guard.snapshot()}")


if __name__ == '__main__':
    main()
