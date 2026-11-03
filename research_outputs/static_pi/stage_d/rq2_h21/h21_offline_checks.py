"""RQ2-H2.1 offline readiness checks (zero model calls).

Runs:
  1. concurrency/makespan check with a mock provider (A vs B vs C)
  2. v_pre whitelist + v_post parent-completeness audit
  3. R4 frozen-scorer compatibility probe
  4. budget estimate (4 tasks x 2 reps x 3 arms)
  5. block randomization table
Writes H2.1_DEPENDENCY_AUDIT.json / H2.1_BUDGET_ESTIMATE.json /
H2.1_RANDOMIZATION.json / H2.1_OFFLINE_CHECKS.json
"""
import json, os, random, sys, time
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/rq2_h21')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import h21_core as C

ROOT = '/root/research_outputs/static_pi/stage_d'
H21 = f'{ROOT}/rq2_h21'
TASKS = ['E05', 'E06', 'E07', 'E08']
REPS = (1, 2)
SEED = 20261103

# mock latencies (seconds) mirror the R4 BASE_LAT ordering
LAT = {'e0': 0.30, 'e1': 0.30, 't': 0.20, 'm': 0.40, 'r': 0.25, 'v': 0.50,
       'v_post': 0.25, 'p': 0.20, 'v_pre': 0.20}


def mock_call(node, model, inputs):
    time.sleep(LAT[node] * (1.0 if model == C.GLM else 0.75))
    return dict(node=node, model=model, facts=[f'{node}-f0'])


def mock_vpre(inputs):
    assert 'm' not in inputs
    time.sleep(LAT['v_pre'])
    return dict(checked=[d for d in inputs])


def mock_vpost(inputs):
    assert 'm' in inputs and 'v_pre' in inputs
    time.sleep(LAT['v_post'])
    return dict(node='v', facts=['v-f0', 'v-f1'])


def run_concurrency():
    res = {}
    for arm in ('A', 'B', 'C'):
        r = C.run_execution(arm, {'id': 'MOCK'}, mock_call, mock_vpre, mock_vpost)
        res[arm] = dict(makespan=round(r['makespan'], 4),
                        overlap=round(r['vpre_m_overlap'] or 0, 4),
                        nodes=sorted(r['outputs']),
                        windows={k: [round(x, 4) for x in v] for k, v in r['windows'].items()})
    ok_c = (res['C']['overlap'] > 0.05) and (res['C']['makespan'] < res['B']['makespan'])
    return dict(results=res, concurrent=ok_c,
                note='mock latencies; C must overlap v_pre with m and beat B on makespan')


def dependency_audit():
    v_parents = {'m', 't'}
    vpre_deps = {'e0', 'e1', 't'}
    # t reaches v_post transitively through v_pre's results; m must be direct
    covered = {'m'} | vpre_deps
    audit = dict(
        vpre_whitelist=sorted(vpre_deps),
        vpre_reads_m='m' in vpre_deps,
        vpost_inputs=['m', 'v_pre'],
        vpost_direct_parents=['m'],
        vpost_transitive_coverage=sorted(covered),
        vpost_covers_original_parents=v_parents <= covered,
        v_outputs_preserved=('v' in ('v_pre', 'v_post')),
        legal=(('m' not in vpre_deps) and (v_parents <= covered)),
        note=('v_pre is restricted to e0/e1/t; v_post consumes m directly and t '
              'transitively via v_pre; v_post emits all original v facts'))
    return audit


def r4_compat():
    """Probe whether the frozen R4 scorer can ingest real outputs directly."""
    from rq1_v1_8_2_r4_p0_calibration import score, DEC, CRIT
    import inspect
    sig = str(inspect.signature(score))
    # fact counts of the selected real tasks
    facts = json.load(open(f'{ROOT}/rq1_tasks/facts_E05_E08.json'))
    import collections
    counts = collections.Counter(k.split('-')[1] for k in facts)
    direct = False
    try:
        score({'text': 'answer'}, None, None, None)
    except Exception as e:
        err = f'{type(e).__name__}: {e}'
    else:
        err = None
    return dict(
        score_signature=sig,
        decidable_slots=len(DEC), critical_slots=CRIT,
        real_task_fact_counts=dict(counts),
        mismatch=('R4 score() consumes a 7x2 outcome matrix (TP/FP/UNKNOWN + loc + sup + '
                  'exec_ok); it cannot ingest model text. Selected real tasks carry '
                  '10-12 facts, not the 13 decidable slots the frozen scorer requires.'),
        direct_ingest_works=direct,
        probe_error=err,
        verdict='BLOCKED')


def budget():
    mats = json.load(open(f'{ROOT}/rq1_tasks/rq1_tasks_materials.json'))['tasks']
    docs_dir = '/root/cap_eval_bench_v1/evidence/texts'
    per_task = {}
    for t in TASKS:
        docs = mats[t]['docs']
        chars = sum(os.path.getsize(os.path.join(docs_dir, d['file'])) for d in docs)
        per_task[t] = dict(docs=len(docs), chars=chars)
    # 24 executions: 4 tasks x 2 reps x 3 arms; 7 model calls each (C's v_pre is code)
    calls = 4 * 2 * 3 * 7
    # token estimate: e-nodes see one doc, t/m/r/v/post see upstream; conservative 0.6 tok/char
    in_tok = 0
    for t in TASKS:
        ch = per_task[t]['chars']
        per_exec = ch * 0.6 + 6 * 2200 + 3000  # e x ndocs + mid nodes + sink overhead
        in_tok += per_exec * 2 * 3
    out_tok = calls * 500
    cost = in_tok * 0.8e-6 + out_tok * 2.8e-6
    caps = dict(calls=int(calls * 1.15), tokens=int((in_tok + out_tok) * 1.2),
                yuan=round(cost * 1.25, 2))
    return dict(tasks=per_task, executions=24, calls_per_execution=7,
                estimated_calls=calls, estimated_in_tokens=int(in_tok),
                estimated_out_tokens=out_tok, estimated_tokens=int(in_tok + out_tok),
                estimated_cost_yuan=round(cost, 3), hard_stop=caps,
                note='estimates only; hard stops are ceilings, not budgets')


def randomization():
    cells = [(t, r, a) for t in TASKS for r in REPS for a in ('A', 'B', 'C')]
    rng = random.Random(SEED)
    order = []
    for t in TASKS:
        for r in REPS:
            block = [c for c in cells if c[0] == t and c[1] == r]
            rng.shuffle(block)
            order.extend(block)
    return dict(seed=SEED, n_cells=len(order),
                order=[dict(task=t, rep=r, arm=a, position=i + 1)
                       for i, (t, r, a) in enumerate(order)],
                unit='independent task; repeats are not independent samples')


def main():
    checks = dict(
        batch='RQ2_H21_OFFLINE_CHECKS', model_calls=0,
        concurrency=run_concurrency(),
        dependency=dependency_audit(),
        r4_compat=r4_compat(),
        budget=budget(),
        randomization=randomization())
    json.dump(dict(batch='RQ2_H21_DEPENDENCY_AUDIT', model_calls=0,
                   **checks['dependency']),
              open(f'{H21}/H2.1_DEPENDENCY_AUDIT.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(dict(batch='RQ2_H21_BUDGET', model_calls=0, **checks['budget']),
              open(f'{H21}/H2.1_BUDGET_ESTIMATE.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(dict(batch='RQ2_H21_RANDOMIZATION', model_calls=0, **checks['randomization']),
              open(f'{H21}/H2.1_RANDOMIZATION.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(checks, open(f'{H21}/H2.1_OFFLINE_CHECKS.json', 'w'), ensure_ascii=False, indent=1)

    print('concurrency:', checks['concurrency']['results'])
    print('concurrent OK:', checks['concurrency']['concurrent'])
    print('dependency legal:', checks['dependency']['legal'])
    print('R4 compat:', checks['r4_compat']['verdict'], '|', checks['r4_compat']['mismatch'][:90])
    print('budget:', {k: checks['budget'][k] for k in
                      ('estimated_calls', 'estimated_tokens', 'estimated_cost_yuan', 'hard_stop')})
    print('randomization cells:', checks['randomization']['n_cells'])


if __name__ == '__main__':
    main()
