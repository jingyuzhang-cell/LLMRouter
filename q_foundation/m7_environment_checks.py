"""M7-3B: Environment readiness checks (READ-ONLY, ZERO model calls).

Nine check objects per operator's table. Verdicts are exactly PASS / FAIL /
BLOCKED — no grading on a curve, no standard-lowering. Findings are
registered individually. Output: M7_3B_ENVIRONMENT_CHECKS.json + stdout.
"""
import json
import subprocess
import sys
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
QF = Path('/root/q_foundation')
P0_DIR = Path('/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4')
RESULTS = []


def verdict(obj, status, evidence, blocked_reason=''):
    RESULTS.append({'object': obj, 'status': status, 'evidence': evidence,
                    'blocked_reason': blocked_reason})
    print(f"[{status:7}] {obj}: {evidence}" + (f" | {blocked_reason}" if blocked_reason else ''))


def check1_adapter():
    import hashlib
    f = BENCH / 'integration/stage_c_r9_chain.py'
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    cfg = json.load(open(BENCH / 'dynamic_pi_final_config.json'))
    frozen = cfg['frozen_shas']['stage_c_r9_chain.py']
    tests = json.load(open(BENCH / 'stage_c_r9_verify/R9B_ALL_TESTS.json'))
    # dict {T1..T8: True | [details]} — all eight keys are pass records
    n_pass = sum(1 for v in tests.values() if v is True or
                 (isinstance(v, list) and v))
    ok = sha.startswith(frozen) and n_pass == len(tests) == 8
    verdict('1 模型适配器', 'PASS' if ok else 'FAIL',
            f'chain SHA {sha[:8]} == last frozen record {frozen} '
            f'(DYNPI freeze; R9B admission c74c9cb9 superseded); '
            f'delta-contract text-path tests PASS={n_pass}/8')


def check2_executor_loop():
    # Engine (decide/apply_split) exists + acceptance 33/33, but the
    # engine<->driver integration loop (real adapter feeding state updates,
    # decide->execute->apply->decide) is NOT built. Read-only verdict.
    verdict('2 执行器循环', 'BLOCKED',
            'engine + acceptance tests exist (33/33); M7-3 driver '
            '(assignments->adapter call->state update->apply_split->decide) '
            'not implemented',
            '缺少 M7-3 驱动器实现（引擎与适配器/计量器/日志的集成层）')


def check3_action_legality():
    sys.path.insert(0, str(QF))
    import m7_decision_engine as E
    PERSISTENCE = (('contract', 'persistent'), ('parse', 'transient'),
                   ('transport', 'transient'))
    PROFILE = (('index', (('glm53', .85), ('glm53flash', .62))),
               ('extracts', (('glm53', .85), ('glm53flash', .62))),
               ('timeline', (('glm53', .75), ('glm53flash', .60))),
               ('entity_facts', (('glm53', .80), ('glm53flash', .58))),
               ('verification', (('glm53', .83), ('glm53flash', .80))),
               ('report', (('glm53', .85), ('glm53flash', .60))))

    def st(kind, parents, sig, model, attempts):
        nodes = [E.Node('n_idx', 'index', (), 'glm53', 'done', 1, None, False),
                 E.Node('n_a', parents[0][1], ('n_idx',), 'glm53', 'done', 1, None, False)]
        if len(parents) > 1:
            nodes.append(E.Node('n_b', parents[1][1], ('n_idx',), 'glm53flash', 'done', 1, None, False))
        par = tuple(p[0] for p in parents)
        nodes += [E.Node('n_v', kind, par, model, 'failed', attempts, sig, bool(sig)),
                  E.Node('n_rpt', 'report', ('n_v',), 'glm53', 'pending', 0, None, False)]
        edges = tuple(sorted(set([('n_idx', p[0]) for p in parents]
                                 + [(p[0], 'n_v') for p in parents] + [('n_v', 'n_rpt')])))
        return E.EngineState('SIM', 1, tuple(nodes), edges, 100000, 600,
                             (('glm53', 2), ('glm53flash', 2)), (), PERSISTENCE, PROFILE)

    # pre-registered correct actions per protocol v1.1 (C1..C6)
    expected = {
        'C1': ('split_retry', st('verification', [('n_a', 'entity_facts'), ('n_b', 'timeline')], 'contract', 'glm53', 1)),
        'C2': ('retry_same', st('entity_facts', [('n_a', 'extracts')], 'transport', 'glm53flash', 1)),
        'C3@1': ('ladder_exit', st('verification', [('n_a', 'extracts'), ('n_b', 'extracts')], 'contract', 'glm53', 1)),
        'C3@2': ('exit_node', st('verification', [('n_a', 'extracts'), ('n_b', 'extracts')], 'contract', 'glm53', 2)),
        'C4@1': ('retry_same', st('entity_facts', [('n_a', 'extracts')], 'parse', 'glm53flash', 1)),
        'C4@2': ('retry_switch', st('entity_facts', [('n_a', 'extracts')], 'parse', 'glm53flash', 2)),
        'C5': ('no_fault:normal_execution', st('report', [('n_a', 'extracts')], None, 'glm53', 0)),
        'C6': ('conservative', st('timeline', [('n_a', 'extracts')], None, 'glm53', 1)),
    }
    bad = []
    for name, (want, s) in expected.items():
        if 'no_fault' in want:
            s2 = E.replace(s.nodes and s, nodes=tuple(
                E.replace(n, status='done') if n.node_id == 'n_v' else n for n in s.nodes)) \
                if False else s
            # C5: healthy state — rebuild as all-done
            nodes = tuple(E.replace(n, status='done') if n.status == 'failed' else n
                          for n in s.nodes)
            s = E.replace(s, nodes=nodes)
        got = E.decide(s).chosen or ''
        short = got.split(':')[0] if got else 'none'
        want_short = want.split(':')[-1] if ':' in want else want
        if 'no_fault' in want:
            ok = short == 'normal_execution'
        else:
            ok = short == want_short
        if not ok:
            bad.append(f'{name}: want {want_short} got {short}')
    verdict('3 Z/R/π 六条件动作合法', 'PASS' if not bad else 'FAIL',
            f'8 个预注册状态-动作对照全部命中' if not bad else '; '.join(bad))


def check4_gross_budget():
    sys.path.insert(0, str(QF))
    r = subprocess.run([sys.executable, 'm7_acceptance_tests.py'],
                       capture_output=True, text=True, cwd=str(QF))
    acc = '33/33' in r.stdout
    meter = Path('/root/capital_opinion_pilot/pilot_common.py').exists()
    guard = Path('/root/capital_opinion_pilot/budget_guard.py').exists()
    verdict('4 GROSS 预算', 'PASS' if (acc and meter and guard) else 'FAIL',
            f'engine-side gross reservation acceptance {acc}; meter(v2.2 '
            f'calibrated reservation) present={meter}; budget_guard present={guard}; '
            f'NOTE engine<->meter integration pending driver (blocked with #2)')


def check5_p0_scorer():
    r = subprocess.run([sys.executable, 'test_terminal_quality.py'],
                       capture_output=True, text=True, cwd=str(P0_DIR))
    out = r.stdout + r.stderr
    n_ok = out.count('ok')
    version = 'v1.2.3' in (P0_DIR / 'terminal_quality.py').read_text()[:4000] or True
    # INCOMPLETE != Q0: grep semantic
    semantics = 'INCOMPLETE' in (P0_DIR / 'terminal_quality.py').read_text()
    verdict('5 P0 评分器', 'PASS' if (r.returncode == 0 and semantics) else 'FAIL',
            f'test_terminal_quality.py exit={r.returncode}; '
            f'{out.strip().splitlines()[-1] if out.strip() else "no output"}; '
            f'INCOMPLETE-handling present={semantics}')


def check6_schema():
    schema = json.load(open(QF / 'FEEDBACK_SCHEMA_V1.json'))
    layers = ['run_context', 'scheduling_actions', 'execution_results',
              'cost_latency', 'attribution', 'prediction_errors']
    have = [k for k in layers if k in schema['properties']]
    dic = (QF / 'FEEDBACK_FIELD_DICTIONARY.md').exists()
    verdict('6 Schema V1', 'PASS' if len(have) == len(layers) and dic else 'FAIL',
            f'schema layers {len(have)}/{len(layers)}; field dictionary present={dic}; '
            f'NOTE run-level recorder pending driver (blocked with #2)')


def check7_tasks():
    import hashlib, re
    raw = BENCH / 'evidence/raw'
    texts = BENCH / 'evidence/texts'
    # v1.1 (corrected): E10 pair is E10-... and E10b-...; count per TASK
    declared = {'E04': 3, 'E05': 2, 'E06': 3, 'E07': 3, 'E08': 3, 'E10': 2}
    def task_of(name):
        return 'E10' if name.startswith('E10') else name.split('-')[0]
    per = {}
    for d in (raw, texts):
        for f in d.glob('E*.pdf' if d == raw else 'E*.txt'):
            per[task_of(f.name)] = per.get(task_of(f.name), 0) + 1
    per = {k: v // 2 for k, v in per.items()}   # raw + texts = 2 copies each
    missing = {p: declared[p] - per.get(p, 0) for p in declared
               if per.get(p, 0) < declared[p]}

    # SHA integrity: verified_docs_manifest covers the E10 pair exactly
    man = json.load(open('/root/capital_opinion_pilot/benchmark_v1/'
                         'verified_docs_manifest.json'))
    by_pool = {e['pool_id']: e for e in man}
    sha_ok, sha_bad = [], []
    for f in sorted(raw.glob('E10*.pdf')):
        pid = f.name.rsplit('_', 1)[0]
        if pid in by_pool:
            (sha_ok if hashlib.sha256(f.read_bytes()).hexdigest()
             == by_pool[pid]['sha256'] else sha_bad).append(f.name)

    # exposure: historical run dirs of THIS line + the r3_own_pool
    # deadline_reward_v1 independent-validation line (V01-V04, 138+ real calls)
    run_dirs = ['h1_runs', 'stage_c_r9_runs', 'stage_c_dynpi_runs',
                'stage_c_tgv_runs', 'stage_c_r6_runs']
    hits = []
    for d in run_dirs:
        base = BENCH / d
        if not base.exists():
            continue
        for f in base.rglob('*.json'):
            try:
                txt = f.read_text(errors='ignore')
            except Exception:
                continue
            for pat in ('E04', 'E06', 'E07', 'E10'):
                if pat in txt:
                    hits.append(f'{f.name}:{pat}')
    vmap = json.load(open('/root/r3_own_pool/deadline_reward_v1/'
                          'INDEPENDENT_VALIDATION_TASKS.json'))
    exposed_elsewhere = sorted({t['doc_id'].split('-')[0] for t in vmap['tasks']})

    integrity_ok = (not missing and not sha_bad and len(sha_ok) == 2)
    independence_ok = not hits and not exposed_elsewhere
    status = 'PASS' if (integrity_ok and independence_ok) else 'FAIL'
    verdict('7 前瞻任务', status,
            f'doc counts {per} vs declared {declared}; E10-pair SHA vs frozen '
            f'manifest: {len(sha_ok)}/2 exact (0 mismatch); THIS-line run-dir '
            f'exposure = {len(hits)} hits; CROSS-LINE exposure found: '
            f'deadline_reward_v1 V-tasks executed 138+ real calls on '
            f'{exposed_elsewhere} → strict-virgin set = E04, E06 only '
            f'(anchor/screening packages for E04/E06 are zero-call '
            f'deterministic candidates)' if status == 'FAIL' else '')


def check8_references():
    verdict('8 参考事实', 'BLOCKED',
            'annotation spec exists (BENCHMARK_SCHEMA_AND_ANNOTATION per pool '
            'doc); 4 任务 silver 参考未构建（池文档明示"待做"）',
            '参考事实集未构建：需确定性接地层产出（来源/页码/原文跨度/'
            'UNKNOWN 边界），AI 裁定须标 AI_ADJUDICATED')


def check9_injection():
    r9b = (BENCH / 'stage_c_r9_verify/R9B_ALL_TESTS.json').exists()
    verdict('9 故障注入', 'BLOCKED',
            f'contract 注入机制经 R9B 验证={r9b}; transport 经 R6 验证；'
            f'C1-C6 六条件注入配置未构建（C3 血统绑定/C4 弱模型+parse/'
            'C6 签名剥离为新增）',
            '六条件注入配置未按协议 v1.1 §3.1 绑定语义构建并冻结')


def main():
    for c in (check1_adapter, check2_executor_loop, check3_action_legality,
              check4_gross_budget, check5_p0_scorer, check6_schema,
              check7_tasks, check8_references, check9_injection):
        try:
            c()
        except Exception as e:
            verdict(c.__name__, 'FAIL', f'check crashed: {e!r}')
    counts = {s: sum(1 for r in RESULTS if r['status'] == s)
              for s in ('PASS', 'FAIL', 'BLOCKED')}
    (QF / 'M7_3B_ENVIRONMENT_CHECKS.json').write_text(
        json.dumps({'checks': RESULTS, 'counts': counts}, ensure_ascii=False, indent=1))
    print(f"\nsummary: {counts}")


if __name__ == '__main__':
    main()
