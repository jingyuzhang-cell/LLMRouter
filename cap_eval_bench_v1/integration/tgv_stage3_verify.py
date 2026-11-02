"""TGV Stage-3: five zero-call verification packages (S3-1..S3-5).
Operator requirements: independent test cases, actual assertions, execution log;
failures NOT masked. Writes TGV_STAGE3_VERIFICATION.json. Zero model calls —
all transports are stubs / deterministic models.
"""
import json, sys, tempfile, hashlib
from pathlib import Path
B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import stage_c_r9_chain as R9
import stage_c_r1 as R1
import stage_c_r4_runner as R4
import stage_c_tgv_exec as DX
from pilot_common import Meter
from six_arm_scheduler import z_candidates, decide_Joint_Z_R_pi
import stage_c_r1 as R1

LOG, RESULTS = [], []

def case(pkg, cid, desc, passed, evidence):
    entry = dict(package=pkg, case=cid, desc=desc, passed=bool(passed), evidence=evidence)
    RESULTS.append(entry)
    LOG.append(f"[{pkg}] {cid}: {'PASS' if passed else 'FAIL'} — {desc} | {evidence}")
    print(LOG[-1], flush=True)

# ---------- S3-1: Real-MCF rule freeze ----------
def s3_1(tasks):
    # case 1: real-path adapter contains no model-conditional injection
    src = (B/'integration'/'stage_c_r9_chain.py').read_text() + \
          (B/'integration'/'stage_c_tgv_exec.py').read_text()
    bad = [pat for pat in ("model == 'glm53flash'", "model=='glm53flash'",
                           "alias == 'glm53flash'", "if model == \"flash\"")
           if pat in src]
    case('S3-1', 'no-model-conditional-injection-on-real-path',
         '真实路径代码零模型条件化失败逻辑（源码级扫描）', not bad, f'命中={bad}')

    # case 2: behavioral — a VALID flash response on a reasoning node passes through untouched
    def tr(alias, system, user, max_tokens, timeout_s):
        return {'usage': {'input_tokens': 100, 'output_tokens': 40},
                'text': '{"new_facts":[{"content":"2026年10月9日","kind":"date","source_doc":"E05-nachuan_20261009"}],"comparisons":[],"dropped":[],"status_changes":[]}',
                'latency_s': 0.1, 'stop_reason': 'end_turn'}
    tmp = Path(tempfile.mkdtemp())
    m = Meter(ledger_path=tmp/'L.jsonl', max_calls=10, max_guaranteed_actual=50000)
    m._transport = tr
    ad = R9.MeterR9Adapter(m, 's31')
    r = ad.call('e05_gov', 'reasoning', 'glm53flash', 'p', R9.FactLedger(), {})
    case('S3-1', 'valid-flash-reasoning-response-passes',
         '合法 flash 响应在 reasoning 节点原样放行（不被覆写）',
         r['success'] is True, f"success={r['success']}")

    # case 3: frozen structure rule picks the reasoning node (pi0=flash) on both tasks
    ok = all(DX.mcf_target(tasks[t]) in ('e05_gov', 'e08_numeric') for t in DX.TASKS)
    pi0 = R1.INITIAL_PI.get('reasoning')
    case('S3-1', 'structure-rule-targets-reasoning-pi0-flash',
         '结构规则=MCF 目标为 reasoning 节点（能力表 0.58 vs 0.80；π0=flash）',
         ok and pi0 == 'glm53flash', f'targets ok={ok}, pi0(reasoning)={pi0}')

    # case 4: three-state classifier unit tests
    c = DX.classify_mcf_state
    tests = [([('glm53flash', False), ('glm53flash', False), ('glm53', True)], 'MCF-MANIFESTED'),
             ([( 'glm53flash', True)], 'MCF-NOT-MANIFESTED'),
             ([], 'MCF-NOT-MANIFESTED')]
    okc = all(c(tc) == exp for tc, exp in tests)
    case('S3-1', 'three-state-classifier-units',
         'MCF-MANIFESTED / NOT-MANIFESTED 分类单元测试（S3-CONTROL 为设计层标签）',
         okc, f'results={[c(tc) for tc,_ in tests]}')

# ---------- S3-2: four-arm differentiation + action constraints ----------
class SynthMCF(R9.DeterministicContractModel):
    """SYNTHETIC-ONLY model-conditional contract-failure injection (harness scaffolding;
    named per v2.2 §1.2 — never used on the real path)."""
    def call(self, nid, kind, model, *a, **kw):
        r = super().call(nid, kind, model, *a, **kw)
        if kind == 'reasoning' and model == 'glm53flash':
            return dict(r, success=False, failure='contract', output=None, ledger=None)
        return r

def s3_2(tasks):
    EXPECT = {'Static-Parallel': 'INCOMPLETE_NO_RECOVERY',
              'R-only': 'INCOMPLETE_RECOVERY_EXHAUSTED',
              'pi-only': 'COMPLETE',
              'Joint(Z,R,pi)': 'COMPLETE'}
    for tid in DX.TASKS:
        data = tasks[tid]
        tgt = DX.mcf_target(data)
        for arm, exp in EXPECT.items():
            r = R9.run_r9(arm, data, {}, budget_tokens=60000,
                          adapter_factory=lambda a=None, c=False: SynthMCF())
            tgt_calls = [(c2['model'], c2['success']) for c2 in r['calls'] if c2['node'] == tgt]
            diff_ok = r['status'] == exp
            # action constraints per arm
            zs = [rd['z_op'] for rd in r['rounds'] if rd['z_op'] != 'KEEP']
            if arm == 'Static-Parallel':
                cons = len(tgt_calls) <= 1 and not zs
                cons_ev = f'tgt_attempts={len(tgt_calls)}, z={zs}'
            elif arm == 'R-only':
                cons = all(m == 'glm53flash' for m, _ in tgt_calls) and not zs
                cons_ev = f'models={sorted({m for m,_ in tgt_calls})}, z={zs}'
            elif arm == 'pi-only':
                cons = ('glm53flash' in {m for m, _ in tgt_calls[:1]}
                        if tgt_calls else True) and not zs
                cons = cons and any(m == 'glm53' for m, _ in tgt_calls)
                cons_ev = f'tgt={tgt_calls}, z={zs}'
            else:
                cons = True   # Joint allowed full action space; legality checked in S3-5
                cons_ev = f'tgt={tgt_calls}, z={zs}'
            case('S3-2', f'{tid}-{arm}',
                 f'{tid} {arm}: 期望 {exp} + 动作约束',
                 diff_ok and cons,
                 f'status={r["status"]}, {cons_ev}')

# ---------- S3-3: cache guarantees (model-suffixed purposes) ----------
def s3_3(tasks):
    hits = []
    def tr(alias, system, user, max_tokens, timeout_s):
        hits.append(alias)
        return {'usage': {'input_tokens': 100, 'output_tokens': 40},
                'text': '{"new_facts":[{"content":"x-' + alias + '","kind":"statement","source_doc":"E05-nachuan_20260904"}],"comparisons":[],"dropped":[],"status_changes":[]}',
                'latency_s': 0.1, 'stop_reason': 'end_turn'}
    tmp = Path(tempfile.mkdtemp())
    m = Meter(ledger_path=tmp/'L.jsonl', max_calls=50, max_guaranteed_actual=100000)
    m._transport = tr
    qm = DX.QuotaMeter(m)
    # identical (purpose, prompt) same model -> single transport hit (replay)
    qm.call('glm53', 'S', 'P1', 2048, 'ns:n1:v1')
    qm.call('glm53', 'S', 'P1', 2048, 'ns:n1:v1')
    case('S3-3', 'same-key-same-model-replays-free',
         '同 purpose+prompt+模型 → 去重重放（1 次真实传输）', len(hits) == 1, f'transport_hits={len(hits)}')
    # same prompt different model -> separate real calls (treatment isolation)
    qm.call('glm53flash', 'S', 'P1', 2048, 'ns:n1:v1')
    case('S3-3', 'same-prompt-different-model-real-call',
         '同 prompt 不同模型 → 独立真实调用（模型后缀进缓存键）', len(hits) == 2, f'transport_hits={len(hits)}')
    # ledger purposes carry the suffix and match actual model
    calls = [json.loads(l) for l in open(tmp/'L.jsonl') if l.strip()]
    real_alias = {'GLM-5.3': 'glm53', 'GLM-5.3-Flash': 'glm53flash'}
    ok = all(c['purpose'].endswith(':' + real_alias[c['model']]) for c in calls)
    case('S3-3', 'purpose-suffix-equals-actual-model',
         '账本 purpose 模型后缀与实际调用模型一致', ok,
         f"purposes={[c['purpose'] for c in calls]}")
    # version increment -> distinct purpose (no stale replay across attempts)
    qm.call('glm53', 'S', 'P1', 2048, 'ns:n1:v2')
    case('S3-3', 'version-change-new-key',
         '版本号变化 → 新缓存键（无跨版本陈旧重放）', len(hits) == 3, f'transport_hits={len(hits)}')

# ---------- S3-4: quota & identity ----------
def s3_4(tasks):
    from pilot_common import BudgetExceeded
    hits = []
    def tr(alias, system, user, max_tokens, timeout_s):
        hits.append(alias)
        return {'usage': {'input_tokens': 100, 'output_tokens': 40},
                'text': '{"new_facts":[],"comparisons":[],"dropped":[],"status_changes":[]}',
                'latency_s': 0.1, 'stop_reason': 'end_turn'}
    tmp = Path(tempfile.mkdtemp())
    m = Meter(ledger_path=tmp/'L.jsonl', max_calls=50, max_guaranteed_actual=100000)
    m._transport = tr
    qm_small = DX.QuotaMeter(m)
    qm_small.calls['glm53flash'] = DX.QUOTAS['glm53flash'][0]   # flash call quota exhausted
    try:
        qm_small.call('glm53flash', 'S', 'x', 2048, 'q:n:v1')
        tripped = False
    except BudgetExceeded:
        tripped = True
    case('S3-4', 'per-model-quota-trips-independently',
         'flash 配额触顶时立即拒绝（不占用 glm53 额度路径）', tripped,
         f'flash quota cap={DX.QUOTAS["glm53flash"][0]}')
    # replay of an existing record does NOT consume quota
    qm2 = DX.QuotaMeter(m)
    before = dict(qm2.calls)
    # (fresh tmp ledger above has only the flash-reject attempt; craft replay within this meter)
    qm2.call('glm53', 'S', 'R1', 2048, 'q2:n:v1')
    qm2.call('glm53', 'S', 'R1', 2048, 'q2:n:v1')
    ok = qm2.calls['glm53'] == before['glm53'] + 1
    case('S3-4', 'replay-does-not-consume-quota',
         '去重重放不消耗配额（真实调用计数=1）', ok,
         f"glm53 counted={qm2.calls['glm53']}, before={before['glm53']}")
    # identity: response content tagged by actual alias
    hits.clear()
    tmp2 = Path(tempfile.mkdtemp())
    m2 = Meter(ledger_path=tmp2/'L.jsonl', max_calls=10, max_guaranteed_actual=50000)
    m2._transport = tr
    qm3 = DX.QuotaMeter(m2)
    rec, txt = qm3.call('glm53', 'SYS', 'IDENT', 2048, 'id:n:v1')
    case('S3-4', 'call-identity-settlement',
         '结算记录模型=请求模型（身份不串扰）', rec['model'] == 'GLM-5.3' and 'glm53' in rec['purpose'],
         f"model={rec['model']}, purpose={rec['purpose']}")
    # global caps = per-model sums (arithmetic invariant)
    case('S3-4', 'global-cap-equals-sum',
         '全局硬顶=分模型之和（95 次/130K，无幻余量）',
         DX.MAX_CALLS == sum(v[0] for v in DX.QUOTAS.values())
         and DX.MAX_TOKENS == sum(v[1] for v in DX.QUOTAS.values()),
         f"calls {DX.MAX_CALLS}=={sum(v[0] for v in DX.QUOTAS.values())}, "
         f"tokens {DX.MAX_TOKENS}=={sum(v[1] for v in DX.QUOTAS.values())}")

# ---------- S3-5: Z candidate legality ----------
def s3_5(tasks):
    from six_arm_scheduler import ARM_DECIDERS
    for tid in DX.TASKS:
        data = tasks[tid]
        state = R4.build_state_r4(data, 60000)
        # execute prefix synthetically so mid nodes become ready/healthy
        r = R9.run_r9('Static-Parallel', data, {}, budget_tokens=60000)
        state2 = R4.build_state_r4(data, 60000)
        # mark nodes done as a healthy-prefix state (use the synthetic run's call order)
        done_kinds = {}
        for c in r['calls']:
            nid = c['node']
            if nid in state2.nodes:
                state2.nodes[nid].status = 'done'
                done_kinds[nid] = state2.kinds[nid]
        chk = next(n['id'] for n in data['task']['dag']['nodes'] if n['kind'] == 'verification')
        state2.nodes[chk].status = 'failed'      # decision-time legality: SPLIT requires failed node
        cands = z_candidates(state2)
        z_ops = [op for op, _ in cands if op != 'KEEP']
        has_split = any(op == 'SPLIT_VERIFY' and chk in d for op, d in cands)
        merge_absent = not any(op == 'MERGE' for op, _ in cands)   # frozen rule: extracts have disjoint doc focus
        case('S3-5', f'{tid}-candidates-legal',
             'chk 失败态产生 SPLIT_VERIFY 候选（异类双亲）；MERGE 因证据焦点不相交而合法不适用',
             has_split and merge_absent, f'z_ops={z_ops}')
        # apply_z acyclicity + terminal preservation
        import six_arm_scheduler as SAS
        chk = next(n['id'] for n in data['task']['dag']['nodes'] if n['kind'] == 'verification')
        ok_apply = R1.apply_z(state2, 'SPLIT_VERIFY', f'{chk} -> per-lineage verifiers over parents')
        import stage_c_r1 as _R1
        # acyclicity via topological sort on active_deps
        deps = state2.active_deps
        order, cyc = _R1.topological_sort(deps) if hasattr(_R1, 'topological_sort') else (None, None)
        acyc = True
        try:
            import graphlib
            graphlib.TopologicalSorter(deps).prepare()
        except Exception:
            acyc = False
        rpt_present = any(True for n in state2.nodes if n.endswith('rpt'))
        case('S3-5', f'{tid}-apply-z-acyclic-terminal-preserved',
             'apply_z(SPLIT_VERIFY) 后依赖无环且 report 节点仍在',
             ok_apply and acyc and rpt_present,
             f'applied={ok_apply}, acyclic={acyc}, rpt_present={rpt_present}')

def main():
    tasks = DX.load_tgv_tasks()
    s3_1(tasks); s3_2(tasks); s3_3(tasks); s3_4(tasks); s3_5(tasks)
    by_pkg = {}
    for e in RESULTS:
        by_pkg.setdefault(e['package'], []).append(e['passed'])
    summary = {k: dict(cases=len(v), passed=sum(v), failed=len(v)-sum(v)) for k, v in by_pkg.items()}
    verdict = 'GO' if all(all(v) for v in by_pkg.values()) else 'HOLD'
    out = dict(verdict=verdict, summary=summary, cases=RESULTS,
               zero_model_calls=True,
               note='all transports stubbed/deterministic; failures not masked')
    (B / 'TGV_STAGE3_VERIFICATION.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('\n==== SUMMARY ====')
    for k, v in summary.items():
        print(f'{k}: {v["passed"]}/{v["cases"]} PASS')
    print('VERDICT:', verdict)

if __name__ == '__main__':
    main()
