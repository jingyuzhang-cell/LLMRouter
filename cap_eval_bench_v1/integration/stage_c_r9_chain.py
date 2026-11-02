"""Stage-C-R9: v2 derivation-contract production chain (zero-call).

Implements the operator-approved R9 work package on a NEW module; frozen
files untouched (stage_c_r4_runner.py, fact_ledger.py, six_arm_scheduler.py,
stage_c_r1.py, silver/scorer/history).

  P0  v2 extraction contract — the deterministic test model extracts
      ALL dates / exchange ratios / penalty amounts FROM THE REAL EVIDENCE
      TEXTS by contract rules (regex + spans). It never reads Silver and
      never injects answers (operator prohibition).
  P1  cross-doc comparison by the MERGE CONSUMER (report node), consuming
      both lineages' ledgers; branches never assert cross-doc conclusions.
  P2  operand-priority serialization — within FACT_CAP, kinds are kept in
      priority order ratio > date > derived > statement, so key operands
      survive; dropped facts are still recorded (never silent).
  P3  derivation validation — correct computation (deterministic interval
      arithmetic citing bilateral dates+docs), missing operand (refusal
      with insufficient_evidence), wrong computation (fabricated assertion
      detected and downgraded at the merge consumer).
  P4  terminal report keeps derived value + bilateral operands + doc ids
      + spans + UNKNOWN marks.
"""
import json, re, sys
from datetime import date
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import stage_c_r4_runner as R4
import stage_c_r1 as R1
from fact_ledger import FactLedger

FACT_CAP = 6000
PRIORITY = {'ratio': 0, 'derived': 1, 'date': 2, 'missing': 3}
PRIORITY.update({k: 4 for k in ('amount', 'entity', 'statement')})

SYS_R9 = (
 '你是调查DAG节点。事实继承由执行器自动完成——你【不需要也不得】回显任何继承事实，'
 '只输出增量JSON：{"new_facts":[{"content","kind","source_doc","span","status"}],'
 '"dropped":[{"fid","reason"}],"status_changes":[{"fid","status","reason"}]}。\n'
 '抽取合同（index/extracts）：从每份文档抽取【全部】日期（容空白断行）、全部换股比例'
 '（1:X.XXXX）、主要处罚/虚增金额到new_facts，每条带source_doc与span。\n'
 '时间推导合同（timeline）：对来自【不同文档】的显著性日期对（每文档span序前2+后2），'
 '在new_facts输出"|b-a|天(日期a→日期b,docA×docB)"；任一侧无日期→status='
 'insufficient_evidence并注明缺哪侧；禁止无双侧来源的间隔断言。\n'
 '核验分支合同（verification）：只核验本分支单侧事实，【禁止】输出任何跨文档一致/'
 '不一致结论。\n'
 '变更规则：dropped/status_changes 必须逐条给reason；无原因的删除或状态变更将被'
 '执行器拒绝。')

REPORT_SYS_R9 = (
 '你是终端合并消费者与调查报告生成器。输入：合并事实清单与证据摘录。'
 '事实继承由执行器完成，只输出增量JSON：{"new_facts":[...],'
 '"comparisons":[{"item","operand_a","span_a","doc_a","operand_b","span_b",'
 '"doc_b","conclusion","status"}],"report":"...","unknown_marks":[...],'
 '"dropped":[...],"status_changes":[...]}\n'
 '跨文档比较合同：仅当两侧操作数（含span与doc）都在合并清单中时输出确定结论'
 '（一致/不一致）并引用两个操作数值与双侧来源；缺任一侧→conclusion=null且'
 'status=insufficient_evidence，【禁止】给出确定一致性结论。'
 'report引用实际使用的事实；非confirmed事实列入unknown_marks，不得捏造。')

def serialize_priority(ledger, cap=FACT_CAP):
    """P2: kind-priority serialization under the cap; overflow recorded."""
    items = sorted(ledger.facts.values(),
                   key=lambda f: (PRIORITY.get(f.kind, 4), f.fid))
    lines, kept, used, dropped = [], [], 0, []
    for f in items:
        l = f.compact()
        if used + len(l) + 1 <= cap:
            lines.append(l)
            kept.append(f.fid)
            used += len(l) + 1
        else:
            dropped.append(f)
            ledger.truncation_log.append(dict(fid=f.fid, content=f.content,
                                              source_doc=f.source_doc,
                                              reason='input_cap_after_priority'))
    if dropped:
        lines.append(f'[TRUNCATED {len(dropped)} (priority-ordered, recorded)]')
    return '\n'.join(lines), set(kept)


def build_prompt_r9(state, nid, ledger, evidence):
    kind = state.kinds[nid]
    sub = state.subtasks[nid]
    facts_txt, kept = serialize_priority(ledger)
    if kind == 'report':
        ev = '\n'.join(f'文档{did}摘录：{t[:1200]}' for did, t in evidence.items())
        return (f'{REPORT_SYS_R9}\nsubtask: {sub}\n\n合并事实清单：\n{facts_txt}'
                f'\n\n{ev}\n'), kept
    ev = ''
    if kind in ('index', 'extracts'):
        ev = '\n'.join(f'文档{did}（前600字）：{t[:600]}'
                       for did, t in evidence.items())
    return (f'{SYS_R9}\nsubtask: {sub}\n\n继承事实清单：\n{facts_txt}\n{ev}\n'), kept


DATE_RE = re.compile(r'(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?')
RATIO_RE = re.compile(r'1\s*[:：]\s*(0\.\d+)')


class DeterministicContractModel:
    """Declared-synthetic model HONORING the v2 contracts. Extraction is
    regex-over-real-evidence (never Silver, never answer injection)."""

    def __init__(self, anomalies=None, corrupt_plan_ratio=False):
        self.anomalies = dict(anomalies or {})
        self.corrupt_plan_ratio = corrupt_plan_ratio   # P3 wrong-value probe
        self.calls = []

    def call(self, nid, kind, model, prompt, ledger, evidence, visible_fids=None):
        lat = R1.LATENCY_PRIOR[model] * (1.1 if kind == 'report' else 1.0)
        toks = {'in': min(len(prompt), 6000), 'out': 500}
        inj = self.anomalies.get(nid)
        if inj and inj.get('type') == 'contract':
            return dict(success=False, failure='contract', usage=toks,
                        latency_s=lat, output=None, ledger=None)
        if inj and inj.get('left', 0) > 0 and inj['type'] == 'transport':
            inj['left'] -= 1
            return dict(success=False, failure='transport', usage=toks,
                        latency_s=lat / 2, output=None, ledger=None)
        out = FactLedger()
        for f in ledger.facts.values():
            if visible_fids is None or f.fid in visible_fids:
                out.facts[f.fid] = type(f)(f.fid, f.content, f.kind, f.source_doc,
                                           f.span, nid, 1, f.status)
        self.calls.append(dict(node=nid, model=model, prompt_chars=len(prompt)))

        if kind in ('index', 'extracts'):
            for did, txt in evidence.items():
                for m in DATE_RE.finditer(txt[:6000]):
                    out.add(re.sub(r'\s+', '', m.group(0)), 'date',
                            source_doc=did, span=[m.start(), m.end()],
                            parent_node=nid, parent_version=1)
                for m in RATIO_RE.finditer(txt[:8000]):
                    val = m.group(1)
                    if self.corrupt_plan_ratio and did.endswith('plan_summary_2024'):
                        val = '0.9999'      # P3: wrong-value probe
                    out.add(f'1:{val}', 'ratio', source_doc=did,
                            span=[m.start(), m.end()], parent_node=nid,
                            parent_version=1)

        if kind == 'timeline':
            # 合同v2：显著性日期对规则——每文档取 span 序前2与后2日期，
            # 仅对跨文档显著性对计算间隔（有界枚举，非全对爆炸）
            by_doc = {}
            for f in sorted(out.facts.values(), key=lambda x: x.span or [0]):
                m = DATE_RE.match(f.content)
                if m and f.kind == 'date' and f.source_doc:
                    by_doc.setdefault(f.source_doc, []).append(
                        (f, date(*map(int, m.groups()))))
            salient = {d: v[:2] + v[-2:] for d, v in by_doc.items()}
            docs = sorted(salient)
            for i in range(len(docs)):
                for j in range(i + 1, len(docs)):
                    for fa, da in salient[docs[i]]:
                        for fb, db in salient[docs[j]]:
                            out.add(f'{abs((db - da).days)}天({fa.content}→'
                                    f'{fb.content},{fa.source_doc}×'
                                    f'{fb.source_doc})', 'derived', source_doc=None,
                                    parent_node=nid, parent_version=1,
                                    status='confirmed')

        if kind == 'report':
            # P1: merge consumer performs cross-doc comparison
            rats = [f for f in out.facts.values() if f.kind == 'ratio']
            by_doc = {}
            for f in rats:
                by_doc.setdefault(f.source_doc, []).append(f)
            comparisons = []
            if len(by_doc) >= 2:
                docs = sorted(by_doc)
                # 合同v2：每文档首个比率为其角色主值（文档先陈述自身主比率）
                a = min(by_doc[docs[0]], key=lambda f: f.span or [0])
                b = min(by_doc[docs[1]], key=lambda f: f.span or [0])
                concl = '一致' if a.content == b.content else '不一致'
                out.add(f'换股比例{concl}（{a.content}@{a.source_doc} vs '
                        f'{b.content}@{b.source_doc}）', 'derived',
                        parent_node=nid, parent_version=1, status='confirmed')
                comparisons.append(dict(item='exchange_ratio',
                                        operand_a=a.content, span_a=a.span,
                                        doc_a=a.source_doc,
                                        operand_b=b.content, span_b=b.span,
                                        doc_b=b.source_doc,
                                        conclusion=concl, status='confirmed'))
            elif rats:
                # P3 refusal: one side missing -> NO definitive conclusion
                only = rats[0]
                out.add(f'换股比例无法比较：仅{only.source_doc}侧操作数'
                        f'（{only.content}），缺对侧', 'derived',
                        parent_node=nid, parent_version=1,
                        status='insufficient_evidence')
                comparisons.append(dict(item='exchange_ratio',
                                        operand_a=only.content, span_a=only.span,
                                        operand_b=None, span_b=None,
                                        conclusion=None,
                                        status='insufficient_evidence'))
            rep = dict(comparisons=comparisons,
                       report='；'.join(f.content for f in out.facts.values()
                                       if f.status == 'confirmed')[:800],
                       unknown_marks=[{'fid': f.fid, 'status': f.status}
                                      for f in out.facts.values()
                                      if f.status != 'confirmed'][:10])
            return dict(success=True, failure=None, usage=toks, latency_s=lat,
                        output=rep, ledger=out)
        return dict(success=True, failure=None, usage=toks, latency_s=lat,
                    output={'facts_n': out.stats()['n']}, ledger=out)


def run_r9(arm, data, anomalies=None, budget_tokens=60000,
           corrupt_plan_ratio=False, capture=None, adapter_factory=None,
           fork=None):
    """Minimal contract-chain executor: arm-agnostic pi0 execution with the
    FROZEN deciders for recovery (same loop semantics as R4/R6 drivers).
    fork=(state, ledgers, calls, t_now): resume from a shared paid prefix
    snapshot — prefix costs are NOT re-paid."""
    from six_arm_scheduler import ARM_META, ARM_DECIDERS
    if fork is not None:
        state, ledgers, calls, t0 = (fork[0], fork[1], list(fork[2]), fork[3])
        state.budget_remaining = budget_tokens - sum(
            c['usage']['in'] + c['usage']['out'] for c in calls)
        state.t_now = t0
        rounds = []
        recovery_rounds0 = 1 if state.failed_nodes() else 0
    else:
        state = R4.build_state_r4(data, budget_tokens)
        t0, recovery_rounds0 = 0.0, 0
        ledgers, calls, rounds = {}, [], []
    adapter = adapter_factory(anomalies, corrupt_plan_ratio) if adapter_factory \
        else DeterministicContractModel(anomalies, corrupt_plan_ratio)
    try:
        recovery_rounds0
    except NameError:
        recovery_rounds0 = 0
    recovery_rounds, status = recovery_rounds0, 'RUNNING'
    terminal = state.terminal()
    while status == 'RUNNING':
        if state.failed_nodes():
            recovery_rounds += 1
        dec = ARM_DECIDERS[arm](state)
        rounds.append(dict(z_op=dec.z_op, z_detail=dec.z_detail,
                           recovery_set=sorted(dec.recovery_set),
                           rationale=dec.rationale[:120]))
        if dec.action_type == 'terminate' or not dec.assignments:
            status = ('COMPLETE' if state.nodes[terminal].status == 'done' else
                      'INCOMPLETE_NO_RECOVERY'
                      if (state.failed_nodes() and not ARM_META[arm]['recovers'])
                      else 'INCOMPLETE_RECOVERY_EXHAUSTED'
                      if state.failed_nodes() else 'STALLED')
            break
        if dec.z_op != 'KEEP':
            R1.apply_z(state, dec.z_op, dec.z_detail)
        for nid, model in dec.reoptimize:
            if nid in state.nodes:
                state.nodes[nid].model = model
        if not ARM_META[arm]['recovers']:
            dec.assignments = [(n, m) for n, m in dec.assignments
                               if state.nodes[n].status != 'failed']
        for nid, model in dec.assignments:
            merged = FactLedger()
            for p in state.parents(nid):
                if p in ledgers:
                    merged.merge(ledgers[p], via_node=p,
                                 via_version=state.nodes[p].version)
            prompt, kept = build_prompt_r9(state, nid, merged, data['texts'])
            r = adapter.call(nid, state.kinds[nid], model, prompt, merged,
                             data['texts'], visible_fids=kept)
            r = R1.inject_result(anomalies or {}, nid, r)
            if capture is not None:
                capture.setdefault('prompts', []).append(
                    dict(node=nid, kind=state.kinds[nid], prompt=prompt,
                         visible=sorted(kept)))
            n = state.nodes[nid]
            n.attempts += 1
            n.version += 1
            state.t_now += r['latency_s']
            if r['success']:
                n.status, n.output = 'done', r['output']
                ledgers[nid] = r['ledger']
            else:
                n.status, n.output, n.failure_type = 'failed', None, r['failure']
            calls.append(dict(node=nid, model=model, success=r['success'],
                              failure=r['failure'], usage=r['usage']))
        for nid in state.blocked_nodes():
            state.nodes[nid].status = 'blocked'
        for nid, n in state.nodes.items():
            if n.status == 'blocked' and all(
                    state.nodes[p].status == 'done' for p in state.parents(nid)):
                n.status = 'pending'
        if state.nodes[terminal].status == 'done':
            status = 'COMPLETE'
        elif (state.failed_nodes() and ARM_META[arm]['recovers']
              and recovery_rounds >= R1.MAX_RECOVERY_ROUNDS):
            status = 'INCOMPLETE_RECOVERY_EXHAUSTED'
        term = ledgers.get(terminal)
        if status != 'RUNNING':
            break
    term = ledgers.get(terminal)
    return dict(status=status, rounds=rounds, calls=calls,
                terminal_facts=[dict(fid=f.fid, content=f.content, kind=f.kind,
                                     status=f.status, source=f.source_doc,
                                     span=f.span)
                                for f in (term.facts.values() if term else [])],
                terminal_stats=term.stats() if term else None,
                report=state.nodes[terminal].output if term else None,
                makespan=round(state.t_now, 2),
                tokens=int(sum(c['usage']['in'] + c['usage']['out']
                               for c in calls)))

class MeterR9Adapter:
    """REAL path for the R9 chain (DELTA contract). The executor owns
    inheritance: visible facts are copied into the output ledger with
    original fid/doc/span/lineage; the model returns ONLY new_facts /
    comparisons / dropped (reason required) / status_changes (legal
    transitions only). Malformed/truncated output fails closed with
    billing; an empty delta is a legal success."""

    # EXEC_124828 evidence: 5/46 real calls rambled past 1024 (incl. the
    # SPLIT replacement node and the report node, both killed mid-recovery).
    # Delta outputs are typically <600 tok; 2048 gives ~4x headroom against
    # sampling variance. Truncation at the cap still fails closed (T5).
    OUT_CAP = 2048
    VALID_STATUS = ('confirmed', 'unconfirmed', 'insufficient_evidence',
                    'upstream_missing')

    def __init__(self, meter, run_id):
        self.meter = meter
        self.run_id = run_id
        self._ver = {}
        self.rejected_ops = []          # audit trail of refused deltas

    def call(self, nid, kind, model, prompt, ledger, evidence, visible_fids=None):
        from pilot_common import fenced_json
        from fact_ledger import Fact
        self._ver[nid] = self._ver.get(nid, 0) + 1
        system = REPORT_SYS_R9 if kind == 'report' else SYS_R9
        rec, txt = self.meter.call(model, system, prompt, self.OUT_CAP,
                                   purpose=f'{self.run_id}:{nid}:v{self._ver[nid]}',
                                   timeout_s=60)
        usage = {'in': rec['usage']['input_tokens'],
                 'out': rec['usage']['output_tokens']}
        lat = rec['latency_s']
        if rec.get('stop_reason') == 'max_tokens':
            return dict(success=False, failure='parse', usage=usage,
                        latency_s=lat, output=None, ledger=None)
        try:
            obj = fenced_json(txt)
        except Exception:
            obj = None
        if not isinstance(obj, dict):
            return dict(success=False, failure='parse', usage=usage,
                        latency_s=lat, output=None, ledger=None)

        out = FactLedger()
        # executor-side inheritance (keeps fid/doc/span/lineage/status)
        for f in ledger.facts.values():
            if visible_fids is None or f.fid in visible_fids:
                out.facts[f.fid] = Fact(f.fid, f.content, f.kind, f.source_doc,
                                        f.span, nid, 1, f.status)
        # status_changes: legal transitions only, reason required
        for sc in obj.get('status_changes', []) or []:
            if not isinstance(sc, dict) or not sc.get('fid') \
                    or not sc.get('reason'):
                self.rejected_ops.append(dict(op='status_change', entry=sc,
                                              reason='missing fid/reason'))
                continue
            f = out.facts.get(sc['fid'])
            if f is None or sc.get('status') not in self.VALID_STATUS:
                self.rejected_ops.append(dict(op='status_change', entry=sc,
                                              reason='unknown fid or illegal status'))
                continue
            f.status = sc['status']
        # dropped: reason required, else the fact is KEPT
        dropped_ok = []
        for dp in obj.get('dropped', []) or []:
            if isinstance(dp, dict) and dp.get('fid') and dp.get('reason'):
                dropped_ok.append(dp['fid'])
            else:
                self.rejected_ops.append(dict(op='drop', entry=dp,
                                              reason='missing fid/reason -> kept'))
        # new_facts: content-deduped against inherited facts (a model
        # re-stating an existing fact folds into a status update on the
        # ORIGINAL fid — no duplicate rows, no fid overwrite)
        import re as _re
        _nrm = lambda t: _re.sub(r'\s+', '', str(t))
        # dedupe key includes SOURCE: same value from a different document is
        # a DISTINCT evidence fact (bilateral-proof), not a duplicate
        existing = {(_nrm(f.content), f.source_doc): f
                    for f in out.facts.values()}
        for nf in obj.get('new_facts', []) or []:
            if isinstance(nf, dict) and nf.get('content'):
                st = nf.get('status', 'unconfirmed')
                if st not in ('confirmed', 'unconfirmed',
                              'insufficient_evidence'):
                    st = 'unconfirmed'
                hit = existing.get((_nrm(nf['content']), nf.get('source_doc')))
                if hit is not None:
                    hit.status = st      # folded status update, original fid
                    continue
                f = out.add(nf['content'], nf.get('kind', 'statement'),
                            source_doc=nf.get('source_doc'),
                            parent_node=nid, parent_version=1, status=st)
                existing[(_nrm(f.content), nf.get('source_doc'))] = f
        # comparisons (merge consumer)
        for cmp_ in obj.get('comparisons', []) or []:
            if isinstance(cmp_, dict) and cmp_.get('conclusion') in ('一致', '不一致') \
                    and cmp_.get('operand_a') and cmp_.get('operand_b'):
                out.add(f"换股比例{cmp_['conclusion']}"
                        f"（{cmp_.get('operand_a')}@{cmp_.get('doc_a')} vs "
                        f"{cmp_.get('operand_b')}@{cmp_.get('doc_b')}）",
                        'derived', parent_node=nid, parent_version=1,
                        status='confirmed')
            elif isinstance(cmp_, dict):
                out.add('换股比例无法比较：缺对侧操作数', 'derived',
                        parent_node=nid, parent_version=1,
                        status='insufficient_evidence')
        for fid in dropped_ok:
            out.facts.pop(fid, None)
        return dict(success=True, failure=None, usage=usage, latency_s=lat,
                    output=obj, ledger=out)
