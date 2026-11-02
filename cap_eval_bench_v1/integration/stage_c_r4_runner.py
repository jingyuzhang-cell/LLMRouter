"""Stage-C-R4 runner: information-faithful execution chain with the FROZEN
six-arm decision layer (operator ruling: repair information fidelity, do NOT
redesign scheduling).

Differences vs stage_c_r1 (frozen, untouched):
  * every node carries a FactLedger; prompts pass the STRUCTURED fact list
    (one line per fact: id|kind|content|source|status), not only raw
    parent text;
  * input assembly over the cap records dropped facts (truncation_log),
    never silently;
  * the REPORT node reads the MERGED ancestor ledger + necessary evidence
    excerpts, not just the last summary hop;
  * UNKNOWN taxonomy is explicit: confirmed / unconfirmed /
    insufficient_evidence / upstream_missing — 'absent' is no proxy.

Zero-call: driven by the DeterministicFactAdapter (declared synthetic, for
mechanics/fidelity validation only). The real Meter path remains HOLD
behind the auth gate (stage_c_r4_v1 record does not exist).
"""
import json, re, sys
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))

from six_arm_scheduler import (ARMS, ARM_META, ARM_DECIDERS, DAGState,
                               NodeState)          # FROZEN decisions
from fact_ledger import FactLedger, extract_facts_from_text
import stage_c_r1 as R1                             # frozen engine pieces

SC = B / 'stage_c_evidence'
SYS_R4 = ('你是调查DAG节点。基于给定结构化事实清单执行subtask。'
          '输出JSON：{"facts":[{"content":"...","kind":"...","source_doc":"...",'
          '"status":"confirmed|unconfirmed|insufficient_evidence"}],'
          '"new_facts":[...同结构...],"dropped":[{"fid":"...","reason":"..."}]}。'
          '规则：继承的每条事实必须出现在facts中（可更新status），不得静默丢弃；'
          '确无法保留的列入dropped并给原因；新增事实标注来源文档。')

REPORT_SYS_R4 = ('你是终端调查报告生成器。输入：全部上游结构化事实清单（含状态与来源）'
                 '与证据摘录。输出JSON：{"investigation_timeline":"...",'
                 '"fraud_nature":"...","report":"...","fact_ids_used":["f..."],'
                 '"unknown_marks":[{"fid":"...","status":"..."}]}。'
                 'report须引用你实际使用的事实id；状态非confirmed的事实须在'
                 'unknown_marks中保留，不得捏造。')

FACT_CAP = 6000        # chars of structured facts per node input
                         # (default fits the largest task ledger;
                         #  smaller values exercise the accounting)
EVID_CAP = 1200        # evidence excerpt chars for extraction nodes
REPORT_EVID_CAP = 2400  # evidence budget at the report node


def norm(s):
    return re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）年月日/.-]', '', str(s))


class DeterministicFactAdapter:
    """Declared-synthetic faithful model: extraction nodes pull REAL facts
    (dates/amounts, with doc spans) from the actual evidence slices;
    downstream nodes carry the inherited ledger forward (all facts kept,
    statuses re-verified); the report consumes the merged ledger."""

    def __init__(self, anomalies=None, inject_fake_fact=False):
        self.anomalies = dict(anomalies or {})
        self.inject_fake_fact = inject_fake_fact
        self.calls = []

    def call(self, nid, kind, model, prompt, ledger, evidence,
             visible_fids=None):
        inj = self.anomalies.get(nid)
        lat = R1.LATENCY_PRIOR[model] * (1.1 if kind == 'report' else 1.0)
        toks = {'in': min(len(prompt), 4000), 'out': 400 if model == 'glm53' else 260}
        if inj and inj.get('type') == 'contract':
            return dict(success=False, failure='contract', usage=toks,
                        latency_s=lat, output=None, ledger=None)
        if inj and inj.get('left', 0) > 0 and inj['type'] == 'transport':
            inj['left'] -= 1
            return dict(success=False, failure='transport', usage=toks,
                        latency_s=lat / 2, output=None, ledger=None)
        depth = 800 if model == 'glm53' else 300
        out_ledger = FactLedger()
        # a real model can only forward facts it actually SAW; facts cut by
        # the input cap become upstream_missing placeholders — the LOSS is
        # itself carried forward (non-silent truncation, end to end)
        from fact_ledger import Fact
        for f in ledger.facts.values():
            if visible_fids is None or f.fid in visible_fids:
                out_ledger.merge_fact(f, via_node=nid)
            elif f.fid not in out_ledger.facts:
                # preserve the ORIGINAL fid so the loss record dedupes
                # across hops: one lost fact = one upstream_missing entry
                out_ledger.facts[f.fid] = Fact(
                    f.fid, f'(事实{f.fid}在传递中被截断)', 'missing',
                    f.source_doc, None, nid, 1, 'upstream_missing')
        if kind in ('index', 'extracts'):
            for did, txt in evidence.items():
                extract_facts_from_text(txt[:6000], did, out_ledger,
                                        parent_node=nid, parent_version=1)
            if self.inject_fake_fact:
                out_ledger.add('3019年1月1日', 'date', source_doc=None,
                               parent_node=nid, parent_version=1,
                               status='unconfirmed')
            body = {'facts_n': out_ledger.stats()['n'],
                    'excerpt': ' '.join(evidence.values())[:depth]}
        elif kind == 'report':
            used = [f.fid for f in out_ledger.facts.values()
                    if f.status == 'confirmed'][:8]
            body = {'fact_ids_used': used,
                    'report': '；'.join(f'{f.content}({f.source_doc})'
                                       for f in out_ledger.facts.values()
                                       if f.status == 'confirmed')[:depth],
                    'unknown_marks': [{'fid': f.fid, 'status': f.status}
                                      for f in out_ledger.facts.values()
                                      if f.status != 'confirmed'][:8]}
        else:
            body = {'facts_n': out_ledger.stats()['n'],
                    'carried': True}
        out_ledger.verify_against(' '.join(evidence.values()), norm)
        self.calls.append(dict(node=nid, model=model, prompt_chars=len(prompt)))
        return dict(success=True, failure=None, usage=toks, latency_s=lat,
                    output=body, ledger=out_ledger)


def build_prompt_r4(state, nid, ledger, evidence):
    """Returns (prompt, visible_fids). Facts beyond the cap are NOT shown —
    they will surface downstream as upstream_missing (never vanish)."""
    kind = state.kinds[nid]
    sub = state.subtasks[nid]
    facts_txt, n_dropped, kept_fids = ledger.serialize3(cap_chars=FACT_CAP)
    if kind == 'report':
        ev = ' '.join(f'文档{did}摘录：{txt[:REPORT_EVID_CAP // len(evidence)]}'
                      for did, txt in evidence.items())
        return (f'{REPORT_SYS_R4}\nsubtask: {sub}\n\n结构化事实清单（含来源与状态）：'
                f'\n{facts_txt}\n\n{ev}\n', kept_fids)
    ev = ''
    if kind in ('index', 'extracts'):
        ev = '\n'.join(f'文档{did}（前600字）：{txt[:600]}'
                       for did, txt in evidence.items())
    return (f'{SYS_R4}\nsubtask: {sub}\n\n继承事实清单：\n{facts_txt}\n{ev}\n',
            kept_fids)


def run_arm_r4(arm, data, anomalies=None, budget_tokens=20000,
               deadline_s=None, fork=None, inject_fake_fact=False):
    from copy import deepcopy
    state = build_state_r4(data, budget_tokens, deadline_s)
    kernel = R1.Kernel()
    adapter = DeterministicFactAdapter(anomalies, inject_fake_fact)
    meta = ARM_META[arm]
    rounds, spent, calls = [], 0.0, []
    recovery_rounds = 0
    status = 'RUNNING'
    terminal = state.terminal()
    ledgers = {}          # node id -> FactLedger (its OUTPUT ledger)

    def merged_ledger_for(nid):
        m = FactLedger()
        for p in state.parents(nid):
            if p in ledgers:
                m.merge(ledgers[p], via_node=p,
                        via_version=state.nodes[p].version)
        return m

    trunc_events = []
    while status == 'RUNNING':
        if state.failed_nodes():
            recovery_rounds += 1
        dec = ARM_DECIDERS[arm](state)
        rounds.append(dict(round=len(rounds) + 1, action=dec.action_type,
                           z_op=dec.z_op, recovery_set=sorted(dec.recovery_set),
                           rationale=dec.rationale[:160]))
        if dec.action_type == 'terminate' or not dec.assignments:
            status = ('COMPLETE' if state.nodes[terminal].status == 'done' else
                      'INCOMPLETE_NO_RECOVERY'
                      if (state.failed_nodes() and not meta['recovers']) else
                      'INCOMPLETE_RECOVERY_EXHAUSTED'
                      if state.failed_nodes() else 'STALLED')
            break
        if dec.z_op != 'KEEP':
            R1.apply_z(state, dec.z_op, dec.z_detail)
        for nid, model in dec.reoptimize:
            if nid in state.nodes:
                state.nodes[nid].model = model
        if not meta['recovers']:
            dec.assignments = [(n, m) for n, m in dec.assignments
                               if state.nodes[n].status != 'failed']
        # execute the round serially here (virtual clock via kernel not
        # needed for fidelity metrics; latency accounting preserved)
        t_end = state.t_now
        trunc_events = []
        for nid, model in dec.assignments:
            merged = merged_ledger_for(nid)
            prompt, kept_fids = build_prompt_r4(state, nid, merged, data['texts'])
            trunc_events.extend(dict(node=nid, **t)
                                for t in merged.truncation_log)
            res = adapter.call(nid, state.kinds[nid], model, prompt,
                               merged, data['texts'],
                               visible_fids=kept_fids)
            res = R1.inject_result(anomalies or {}, nid, res)
            n = state.nodes[nid]
            n.attempts += 1
            n.version += 1
            n.model, n.latency_s = model, res['latency_s']
            n.usage = res['usage']
            spent += res['usage']['in'] + res['usage']['out']
            state.budget_remaining -= res['usage']['in'] + res['usage']['out']
            t_end += res['latency_s']
            if res['success']:
                n.status, n.output = 'done', res['output']
                ledgers[nid] = res['ledger']
            else:
                n.status, n.output = 'failed', None
                n.failure_type = res['failure']
            calls.append(dict(node=nid, model=model, attempt=n.attempts,
                              success=res['success'], failure=res['failure'],
                              usage=res['usage'], latency_s=res['latency_s']))
        state.t_now = t_end
        for nid in state.blocked_nodes():
            state.nodes[nid].status = 'blocked'
        for nid, n in state.nodes.items():
            if n.status == 'blocked' and all(
                    state.nodes[p].status == 'done' for p in state.parents(nid)):
                n.status = 'pending'
        if state.nodes[terminal].status == 'done':
            status = 'COMPLETE'
        elif state.budget_remaining <= 0:
            status = 'BUDGET_STOP'
        elif (state.failed_nodes() and meta['recovers']
              and recovery_rounds >= R1.MAX_RECOVERY_ROUNDS):
            status = 'INCOMPLETE_RECOVERY_EXHAUSTED'

    term_ledger = ledgers.get(terminal)
    rep = (state.nodes[terminal].output or {}) if term_ledger else None
    return dict(
        arm=arm, task=data['task']['task_id'], status=status,
        tokens=int(spent), makespan=round(state.t_now, 2),
        z_ops_applied=state.z_ops_applied, rounds=rounds, calls=calls,
        terminal_ledger_stats=term_ledger.stats() if term_ledger else None,
        terminal_truncations=len(term_ledger.truncation_log) if term_ledger else 0,
        truncation_events=trunc_events,
        report_fact_ids=(rep or {}).get('fact_ids_used'),
        report_unknown_marks=(rep or {}).get('unknown_marks'))


def build_state_r4(data, budget_tokens, deadline_s=None):
    dag = data['task']['dag']
    nodes = {n['id']: NodeState(n['id'], n['kind'], n.get('subtask', ''),
                                model=R1.INITIAL_PI.get(n['kind'], 'glm53'))
             for n in dag['nodes']}
    deps = {n['id']: list(n.get('deps', [])) for n in dag['nodes']}
    return DAGState(nodes=nodes, deps=deps,
                    kinds={n['id']: n['kind'] for n in dag['nodes']},
                    subtasks={n['id']: n.get('subtask', '') for n in dag['nodes']},
                    deadline_s=deadline_s or data['deadline'],
                    budget_remaining=budget_tokens)

class MeterFactAdapter(DeterministicFactAdapter):
    """REAL path adapter for the R4 chain: same interface, model transport
    via the pilot Meter. Parses the R4 output schema
    {facts:[{content,kind,source_doc,status}], new_facts:[...], dropped:[...]}
    into the node's output FactLedger. FAIL-CLOSED: only constructed by an
    auth-gated driver (batch record stage_c_r6_v1 does not exist yet)."""

    OUT_CAPS = {'report': 1024}
    OUT_DEFAULT = 1024

    def __init__(self, meter, run_id):
        self.meter = meter
        self.run_id = run_id
        self._ver = {}

    def call(self, nid, kind, model, prompt, ledger, evidence,
             visible_fids=None):
        from pilot_common import fenced_json
        from fact_ledger import Fact
        self._ver[nid] = self._ver.get(nid, 0) + 1
        rec, txt = self.meter.call(
            model, SYS_R4 if kind != 'report' else REPORT_SYS_R4, prompt,
            self.OUT_CAPS.get(kind, self.OUT_DEFAULT),
            purpose=f'{self.run_id}:{nid}:v{self._ver[nid]}', timeout_s=60)
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
        # inherited facts the model confirmed it is carrying forward
        carried = {f['content']: f for f in obj.get('facts', [])
                   if isinstance(f, dict) and f.get('content')}
        for f in ledger.facts.values():
            if visible_fids is None or f.fid in visible_fids:
                st = next((c.get('status', f.status)
                           for c in carried.values()
                           if c.get('content') == f.content), f.status)
                if st not in ('confirmed', 'unconfirmed',
                              'insufficient_evidence', 'upstream_missing'):
                    st = 'unconfirmed'
                out.facts[f.fid] = Fact(f.fid, f.content, f.kind, f.source_doc,
                                        f.span, nid, 1, st)
        # new facts asserted by the model (lineage: this node)
        for nf in obj.get('new_facts', []):
            if isinstance(nf, dict) and nf.get('content'):
                st = nf.get('status', 'unconfirmed')
                if st not in ('confirmed', 'unconfirmed',
                              'insufficient_evidence'):
                    st = 'unconfirmed'
                out.add(nf['content'], nf.get('kind', 'statement'),
                        source_doc=nf.get('source_doc'),
                        parent_node=nid, parent_version=1, status=st)
        return dict(success=True, failure=None, usage=usage, latency_s=lat,
                    output=obj, ledger=out)
