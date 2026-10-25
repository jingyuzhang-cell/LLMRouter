"""R2-fix runner: targeted (D2) vs full (C) recovery on a HETEROGENEOUS
diamond. NOT executable without operator authorization: requires
R2FIX_GO=1 + --approved-freeze-sha256 (r2fix_design_review.py output).

Design (frozen in R2FIX_SCORING_FREEZE.json):
  DAG      diamond_8: n0 -> {b0,b1,b2,b3}; b0->x0->sink; b1->x1->sink;
           b2->sink; b3->sink. Single-extraction: only n0 sees the doc.
  Roles    n0=extraction | b0/x0=timeline | b1/x1=amounts |
           b2=penalties | b3=entity_relations | sink=synthesis
  Fault    F_JSON garbage replacing b0's output (non-root branch node)
  Arms     D0 accept | D2 closure {b0,x0,sink} | C all 7 non-root
  Scoring  frozen mechanical slices of doc atoms (13 keys, 4 categories)
  Model    GLM-5.3-Flash via zhipu anthropic-compatible endpoint (v3
           track switch, operator approval 2026-10-25); subscription
           billing -> marginal cash ¥0/call, cash cap holds trivially
  Budget   guard enforces planned 18 calls + wall 1800s + anomaly
           fail-stop on first error (no retries, no paid-model switch)

Import is side-effect-free (zero API calls); review script imports this
to verify prompt/closure/budget properties before any authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

from deadline_reward_v1.budget_guard import (
    BudgetGuard, worst_case_cny, plan_worst_total)
from deadline_reward_v1.complex_dag import STRUCTURES, topo_sort
from deadline_reward_v1.full_dag_executor import load_env_creds
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.terminal_eval import eval_terminal

HERE = Path(__file__).resolve().parent
FREEZE = HERE / 'R2FIX_SCORING_FREEZE.json'
DOC_SLOT = 'ydt#D3_E03-yuandao_2026-08-29'
FAULT = 'b0'
D = 350.0
C0_TOK = 60000.0
PLANNED_CALLS = 18
CAP_CNY = 0.30
WALL_S = 1800.0
GARBAGE = '[{"fact":"占位","evidence_doc_id":"?"}]'

EDGES = STRUCTURES['diamond'](8)
ORDER = topo_sort(EDGES)
ROOT_NODE = ORDER[0]
SINKS = [n for n in ORDER if not EDGES.get(n)]

# Per-role output caps (operator directive 2026-10-25: hard budget must
# hold under worst-case output on EVERY call). Justification vs observed
# real outputs: extraction completed at 3,723-4,000 chars within 2048
# (keep 2048); role sections are strictly smaller than the homogeneous
# full-summary clones (2,981 chars, finished 'stop' under 2048) — 768
# tokens ≈ 1,500-1,900 chars of role-focused JSON; sink 1,280 ≈
# 2,100-2,600 chars vs observed 2,455-char synthesis. Truncation risk
# is recorded honestly via finish_reason in the artifacts.
# Per-role output caps — v3 (GLM-5.3-Flash track, operator approval
# 2026-10-25). Uniform 3072: GLM thinking blocks fire NONDETERMINISTICALLY
# and count against max_tokens (screening: 768-cap timeline truncated
# when a thinking block appeared; 1536 completed). 3072 absorbs the
# thinking variance; it REDUCES truncation risk and is NOT a correctness
# guarantee — incomplete outputs are recorded honestly via
# finish_reason/has_thinking_block, criteria never loosened. Under
# subscription billing (marginal ¥0/call) caps cost nothing.
OUT_CAP = {'extraction': 3072, 'timeline': 3072, 'timeline_deep': 3072,
           'amounts': 3072, 'amounts_check': 3072, 'penalties': 3072,
           'entity_relations': 3072, 'synthesis': 3072}
SECTION_OUT_CAP = 3072
ROOT_OUT_CAP = 3072
SINK_OUT_CAP = 3072
BILLING = 'subscription'          # GLM via zhipu: marginal ¥0/call
GLM_MODEL = 'GLM-5.3-Flash'
GLM_URL = 'https://open.bigmodel.cn/api/anthropic/v1/messages'

# Frozen 18-call sequence: shared 8 -> D0 0 -> D2 3 -> C 7.
# Roles in dispatch order; char bounds are by CONSTRUCTION (doc[:3000]
# at root; each upstream answer truncated [:3000]; fixed boilerplate).
PLAN_ROLES = (['extraction'] + ['section'] * 6 + ['synthesis']   # shared
              + ['section', 'section', 'synthesis']              # D2
              + ['section'] * 6 + ['synthesis'])                 # C
assert len(PLAN_ROLES) == 18

ROLE = {
    ROOT_NODE: 'extraction',
    'b0': 'timeline', 'x0': 'timeline_deep',
    'b1': 'amounts', 'x1': 'amounts_check',
    'b2': 'penalties', 'b3': 'entity_relations',
    'sink': 'synthesis',
}

ROLE_SPEC = {
    'extraction': dict(
        head='## 节点任务类型：extraction（信息入口）',
        task=('从证据文档抽取原子事实（事实陈述、日期、数值、涉事主体），'
              '每条须含 fact, date, entities, evidence_doc_id 字段。')),
    'timeline': dict(
        head='## 节点任务类型：timeline（事件时间线）',
        task=('仅整理事件时间线：将上游抽取事实中含时间的事件按日期排序，'
              '输出 JSON 数组，每条含 date, event 字段，不得虚构日期。')),
    'timeline_deep': dict(
        head='## 节点任务类型：timeline_deep（时间线复核与阶段划分）',
        task=('基于上游时间线输出阶段划分：每条含 stage, start_date, '
              'end_date, summary；日期必须来自上游，不得新增。')),
    'amounts': dict(
        head='## 节点任务类型：amounts（金额核算）',
        task=('汇总涉案金额类事实（虚增收入金额、占比、罚款金额），输出 '
              'JSON 数组，每条含 amount, context 字段；金额必须来自上游。')),
    'amounts_check': dict(
        head='## 节点任务类型：amounts_check（金额交叉复核）',
        task=('核对上游金额口径：每条含 item, amount, note；只复核上游'
              '给出的金额，不得新增金额。')),
    'penalties': dict(
        head='## 节点任务类型：penalties（处罚决定梳理）',
        task=('汇总处罚决定：处罚类型、对象、依据条款，输出 JSON 数组，'
              '每条含 penalty_type, target, basis 字段。')),
    'entity_relations': dict(
        head='## 节点任务类型：entity_relations（主体关系识别）',
        task=('识别涉事主体及角色（公司、责任人、监管机构）及其关系，'
              '输出 JSON 数组，每条含 entity, role, relation 字段。')),
    'synthesis': dict(
        head='## 节点任务类型：synthesis（最终调查结论）',
        task=('汇总全部上游输出，输出最终调查结论，JSON 数组，每条含 '
              'conclusion, key_dates, amounts, penalties, entities 字段。'
              'key_dates 从上游时间线类输出（x0）提取；若该路缺失或'
              '无效，key_dates 置空并在 conclusion 中注明时间线信息'
              '缺失。amounts/penalties/entities 分别取自对应上游。'
              '所有事实必须来自上游输出，不得虚构。')),
}


class HeteroDAG:
    """Single-extraction DAG with role-heterogeneous nodes."""

    def __init__(self, doc_text: str, doc_id: str):
        self.edges = EDGES
        self.doc_text, self.doc_id = doc_text, doc_id
        self.outputs = {}
        self.order = ORDER
        self.root = ROOT_NODE

    def upstream_of(self, node):
        return [p for p in self.edges if node in self.edges.get(p, [])]

    def build_prompt(self, node) -> str:
        spec = ROLE_SPEC[ROLE[node]]
        parts = ['你是一个资本市场事件调查助手。\n', spec['head'], '']
        if node == self.root:
            parts += [f'## 证据文档 doc_id：{self.doc_id}',
                      f'## 文档内容：\n{self.doc_text[:3000]}', '']
        else:
            ups = self.upstream_of(node)
            parts.append('## 上游输出（唯一信息来源）：')
            for u in ups:
                ans = str(self.outputs.get(u, {}).get('answer', ''))[:3000]
                parts += [f'### {u}的输出：\n{ans}', '']
        parts += ['## 任务要求', spec['task'], '',
                  '## 输出要求：JSON数组，禁止输出任何非JSON文本。']
        return '\n'.join(parts)

    def stale_downstream(self, node):
        seen, stack = set(), [node]
        while stack:
            n = stack.pop()
            for m in self.edges.get(n, []):
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        return {d for d in seen if d in self.outputs and d != node}


def construction_bounds(doc_text: str, doc_id: str) -> dict:
    """Provable prompt-char bounds by construction (zero-call): every
    upstream answer enters the prompt truncated to [:3000]; the doc
    enters only at root truncated to [:3000]; boilerplate is fixed.
    Adversarial probe: EVERY upstream answered exactly 3000 chars.
    Must receive the REAL doc_id (the root prompt embeds it; an earlier
    placeholder probe under-bound root by the id-length difference and
    was caught by the pre-dispatch bound check, 2026-10-25)."""
    dag = HeteroDAG(doc_text, doc_id)
    fat = 'X' * 3000
    for n in ORDER:
        dag.outputs[n] = dict(answer=fat)
    sizes = dict(
        root=len(dag.build_prompt(ROOT_NODE)),
        section=max(len(dag.build_prompt(n)) for n in ORDER
                    if n not in (ROOT_NODE, 'sink')),
        sink=len(dag.build_prompt('sink')))
    return sizes


def plan_call_specs(doc_text: str, doc_id: str):
    """(char_bound, out_cap) per planned call, in dispatch order."""
    b = construction_bounds(doc_text, doc_id)
    out = []
    for role in PLAN_ROLES:
        if role == 'extraction':
            out.append((b['root'], ROOT_OUT_CAP))
        elif role == 'synthesis':
            out.append((b['sink'], SINK_OUT_CAP))
        else:
            out.append((b['section'], SECTION_OUT_CAP))
    return out, b


def closures():
    fault = FAULT
    d2 = {fault} | downstream(fault)
    c_full = set(ORDER) - {ROOT_NODE}
    preserved = set(ORDER) - {ROOT_NODE} - d2
    return d2, c_full, preserved


def downstream(node):
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        for m in EDGES.get(n, []):
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen - {node}


def utility(q, tokens, clock):
    late = clock > D
    return ((0.0 if late else 1.0) * q - 0.5 * tokens / C0_TOK
            - (max(0.0, clock - D) / D if late else 0.0)
            - (2.0 if late else 0.0))


def category_keys(valid_keys):
    out = {'timeline': [], 'amounts': [], 'penalties': [], 'entities': []}
    for k in valid_keys:
        p = k.split('|')[0]
        if p.startswith('d:'):
            out['timeline'].append(k)
        elif p.startswith('a:'):
            out['amounts'].append(k)
        elif p.startswith('p:'):
            out['penalties'].append(k)
        elif p.startswith('e:'):
            out['entities'].append(k)
    return out


def eval_by_category(outputs, valid_keys):
    full = eval_terminal(outputs, EDGES, valid_keys)
    by_cat = {}
    for cat, keys in category_keys(valid_keys).items():
        if keys:
            ev = eval_terminal(outputs, EDGES, keys)
            by_cat[cat] = dict(hits=ev['terminal_hits'], n=ev['n_ref'])
    return full, by_cat


def call_ds(prompt: str, creds: dict, max_out_tokens: int = 3072):
    """GLM-5.3-Flash dispatch (v3). thinking:disabled is REQUESTED but
    not guaranteed (screening evidence); thinking blocks are detected
    and recorded, never silently dropped. cash_cny = 0.0 exactly
    (subscription profile, frozen rates glm_53_flash ¥0/call)."""
    import requests
    body = dict(model=GLM_MODEL, max_tokens=max_out_tokens,
                messages=[dict(role='user', content=prompt)],
                temperature=0.0, thinking={'type': 'disabled'})
    t0 = time.time()
    resp = requests.post(
        GLM_URL,
        headers={'x-api-key': creds['ZHIPU_API_KEY'],
                 'anthropic-version': '2023-06-01',
                 'Content-Type': 'application/json'},
        json=body, timeout=180)
    lat = time.time() - t0
    d = resp.json()
    text = ''
    has_thinking = False
    for blk in d.get('content', []) or []:
        if blk.get('type') == 'text':
            text += blk.get('text', '')
        elif blk.get('type') == 'thinking':
            has_thinking = True
    u = d.get('usage', {})
    if resp.status_code != 200 or not text:
        raise RuntimeError(f'API error: HTTP {resp.status_code} '
                           f'{str(d)[:200]}')
    return dict(answer=text,
                finish_reason=d.get('stop_reason'),
                tokens_in=u.get('input_tokens', 0),
                tokens_out=u.get('output_tokens', 0),
                cash_cny=0.0,
                has_thinking_block=has_thinking,
                latency_s=round(lat, 1))


def gates(args):
    if os.environ.get('R2FIX_GO') != '1':
        raise PermissionError('requires R2FIX_GO=1')
    dirty = subprocess.run(
        ['git', '-C', str(ROOT), 'status', '--porcelain', '--',
         'deadline_reward_v1'], capture_output=True, text=True).stdout.strip()
    if dirty:
        raise PermissionError(f'uncommitted changes:\n{dirty}')
    raw = FREEZE.read_bytes()
    if args.approved_freeze_sha256 != hashlib.sha256(raw).hexdigest():
        raise PermissionError('scoring freeze hash mismatch')
    f = json.loads(raw)
    if (f.get('version') != 'R2FIX_SCORING_FREEZE_v4'
            or f['doc_slot'] != DOC_SLOT or f['fault'] != FAULT):
        raise PermissionError('freeze design mismatch')
    ev_path = ROOT / 'deadline_reward_v1' / 'terminal_eval.py'
    ev_sha = hashlib.sha256(ev_path.read_bytes()).hexdigest()
    if f.get('evaluator_sha256') != ev_sha:
        raise PermissionError(
            f'evaluator sha mismatch: freeze pins '
            f'{f.get("evaluator_sha256", "?")[:12]}... current '
            f'{ev_sha[:12]}... — scoring instrument drifted')
    return f


def execute(args):
    freeze = gates(args)
    valid_keys = freeze['valid_keys']
    creds = load_env_creds()
    doc = load_docs()[DOC_SLOT]
    d2_closure, c_full, preserved = closures()
    repeats = int(freeze.get('repeats', 1))

    # PLAN-LEVEL HARD-BUDGET ASSERTION (before ANY call, per repeat)
    specs, bounds = plan_call_specs(doc['text'], doc['doc_id'])
    plan_worst = plan_worst_total(specs, billing=BILLING)
    if plan_worst > CAP_CNY + 1e-12:
        raise PermissionError(
            f'plan worst-case total ¥{plan_worst:.4f} > cap '
            f'¥{CAP_CNY} — refusing to start (bounds {bounds})')
    print(f'plan worst-case total: ¥{plan_worst:.4f} <= cap '
          f'¥{CAP_CNY} x {repeats} repeats '
          f'(bounds {bounds})', flush=True)

    base_dir = HERE / 'fe_screening_runs' / time.strftime(
        'r2fixv4_%Y%m%d_%H%M%S')
    base_dir.mkdir(parents=True)
    t_start = time.monotonic()
    all_reps = []
    from copy import deepcopy
    import statistics as _st

    for rep in range(1, repeats + 1):
        if time.monotonic() - t_start > 5400.0:
            raise RuntimeError('global wall cap 5400s')
        run_dir = base_dir / f'rep{rep}'
        run_dir.mkdir(parents=True)
        print(f'\n===== repeat {rep}/{repeats} =====', flush=True)
        guard = BudgetGuard(PLANNED_CALLS, CAP_CNY, mode='adaptive',
                            wall_seconds=WALL_S, billing=BILLING)
        results = []

        def bound_for(node):
            if node == ROOT_NODE:
                return bounds['root']
            if node in SINKS:
                return bounds['sink']
            return bounds['section']

        def call_checked(dag, node, replace_garbage=False):
            role = ROLE[node]
            cap_out = OUT_CAP[role]
            prompt = dag.build_prompt(node)
            if len(prompt) > bound_for(node):
                raise RuntimeError(
                    f'construction bound violated: {node} prompt '
                    f'{len(prompt)} > bound {bound_for(node)} — fail-stop')
            stop = guard.may_start(prompt_chars=len(prompt),
                                   max_out_tokens=cap_out)
            if stop:
                raise RuntimeError(f'budget stop: {stop}')
            o = call_ds(prompt, creds, max_out_tokens=cap_out)
            if replace_garbage:
                o = dict(o, answer=GARBAGE, finish_reason='stop')
            dag.outputs[node] = o
            guard.record(o['cash_cny'])
            if guard.anomaly:
                raise RuntimeError(f'guard: {guard.anomaly}')
            print(f'  {node} [{role}]: {o["latency_s"]}s '
                  f'len={len(o["answer"])} '
                  f'finish={o["finish_reason"]} '
                  f'think={o.get("has_thinking_block")} '
                  f'{"<-GARBAGE" if replace_garbage else ""}', flush=True)
            return o

        try:
            chain = HeteroDAG(doc['text'], doc['doc_id'])
            clk = tok = 0.0
            for node in chain.order:
                o = call_checked(chain, node,
                                 replace_garbage=(node == FAULT))
                clk += o['latency_s']
                tok += o['tokens_in'] + o['tokens_out']
            shared, sh_clk, sh_tok = deepcopy(chain.outputs), clk, tok
            (run_dir / 'shared_outputs.json').write_text(json.dumps(
                {n: dict(answer=o['answer'], role=ROLE[n],
                         finish=o.get('finish_reason'),
                         thinking=o.get('has_thinking_block'))
                 for n, o in shared.items()}, indent=1,
                ensure_ascii=False))
            print(f'Shared: {sh_clk:.1f}s, ¥{guard.spent:.4f}')

            def arm(label, closure):
                ac = HeteroDAG(doc['text'], doc['doc_id'])
                ac.outputs = deepcopy(shared)
                r_clk, r_tok = sh_clk, sh_tok
                for rn in sorted(n for n in closure if n == FAULT):
                    o = call_checked(ac, rn)
                    r_clk += o['latency_s']
                    r_tok += o['tokens_in'] + o['tokens_out']
                for dn in ORDER:
                    if dn in closure and dn != FAULT:
                        o = call_checked(ac, dn)
                        r_clk += o['latency_s']
                        r_tok += o['tokens_in'] + o['tokens_out']
                full, by_cat = eval_by_category(ac.outputs, valid_keys)
                eu = utility(full['terminal_q'], r_tok, r_clk)
                pres = {n: (ac.outputs[n]['answer']
                            == shared[n]['answer'])
                        for n in preserved}
                results.append(dict(
                    arm=label, calls=len(closure),
                    t_q=full['terminal_q'], hits=full['terminal_hits'],
                    n_ref=full['n_ref'], p_q=full['pipeline_q'],
                    by_category=by_cat, tokens=int(r_tok),
                    latency=round(r_clk, 1), met=r_clk <= D,
                    eU=round(eu, 4),
                    preserved_byte_identical=pres,
                    lost_in_synthesis=full['lost_in_synthesis']))
                (run_dir / f'{label}_outputs.json').write_text(
                    json.dumps(
                        {n: dict(answer=o['answer'], role=ROLE[n],
                                 finish=o.get('finish_reason'),
                                 thinking=o.get('has_thinking_block'))
                         for n, o in ac.outputs.items()}, indent=1,
                        ensure_ascii=False))
                print(f'{label}: t_q={full["terminal_q"]:.3f} '
                      f'({full["terminal_hits"]}/{full["n_ref"]}) '
                      f'cats={by_cat} eU={eu:+.4f}', flush=True)

            full0, cat0 = eval_by_category(shared, valid_keys)
            results.append(dict(
                arm='D0', calls=0, t_q=full0['terminal_q'],
                hits=full0['terminal_hits'], n_ref=full0['n_ref'],
                p_q=full0['pipeline_q'], by_category=cat0,
                tokens=int(sh_tok), latency=round(sh_clk, 1),
                met=sh_clk <= D,
                eU=round(utility(full0['terminal_q'], sh_tok, sh_clk), 4),
                preserved_byte_identical={},
                lost_in_synthesis=full0['lost_in_synthesis']))
            print(f'D0: t_q={full0["terminal_q"]:.3f} cats={cat0}',
                  flush=True)

            arm('D2', d2_closure)
            arm('C', c_full)

            (run_dir / 'REP_RESULTS.json').write_text(json.dumps(dict(
                status='COMPLETE', rep=rep, results=results,
                fault=FAULT, d2_closure=sorted(d2_closure),
                c_full=sorted(c_full),
                preserved_siblings=sorted(preserved),
                doc=DOC_SLOT, budget=guard.snapshot(),
                plan_worst_cny=plan_worst, char_bounds=bounds,
                out_caps=OUT_CAP), indent=1))
            all_reps.append(dict(rep=rep, results=results,
                                 budget=guard.snapshot()))
            print(f'rep{rep} COMPLETE: {guard.calls} calls, '
                  f'¥{guard.spent:.4f}', flush=True)
        except BaseException as exc:
            (run_dir / 'REP_INCOMPLETE.json').write_text(json.dumps(dict(
                status='INCOMPLETE', rep=rep, reason=repr(exc),
                results=results, budget=guard.snapshot(),
                traceback=traceback.format_exc()), indent=1))
            (base_dir / 'AGGREGATE.json').write_text(json.dumps(dict(
                status='INCOMPLETE_AT_REP', rep=rep, reason=repr(exc),
                completed_reps=[r['rep'] for r in all_reps]),
                indent=1))
            print(f'INCOMPLETE at rep{rep}: {exc}')
            print(f'Run: {base_dir}')
            return

    # ---- pre-registered aggregate analysis ----
    def arm_rows(arm):
        return [next(r for r in rep['results'] if r['arm'] == arm)
                for rep in all_reps]

    d0s, d2s, cs = arm_rows('D0'), arm_rows('D2'), arm_rows('C')

    def series(rows, k):
        return [r[k] for r in rows]

    def stats(v):
        return dict(mean=round(_st.mean(v), 4),
                    sd=round(_st.stdev(v), 4) if len(v) > 1 else 0.0,
                    min=min(v), max=max(v))

    paired = dict(
        d_tq_recovery=[a['t_q'] - b['t_q'] for a, b in zip(d2s, d0s)],
        d_eU_recovery=[a['eU'] - b['eU'] for a, b in zip(d2s, d0s)],
        d_tq_targeted=[a['t_q'] - c['t_q'] for a, c in zip(d2s, cs)],
        d_eU_targeted=[a['eU'] - c['eU'] for a, c in zip(d2s, cs)])
    n = len(all_reps)
    agg = dict(
        status='COMPLETE', repeats=n, per_arm=dict(
            D0=dict(t_q=stats(series(d0s, 't_q')),
                    eU=stats(series(d0s, 'eU'))),
            D2=dict(t_q=stats(series(d2s, 't_q')),
                    eU=stats(series(d2s, 'eU'))),
            C=dict(t_q=stats(series(cs, 't_q')),
                   eU=stats(series(cs, 'eU')))),
        paired=paired,
        decision_rules=freeze['decision_rules'],
        verdicts=dict(
            recovery_supported=(
                _st.mean(paired['d_tq_recovery']) > 0
                and sum(x > 0 for x in paired['d_tq_recovery'])
                >= (n // 2 + 1)),
            recovery_utility=(
                _st.mean(paired['d_eU_recovery']) > 0),
            targeted_beats_full_utility=(
                _st.mean(paired['d_eU_targeted']) > 0
                and sum(x > 0 for x in paired['d_eU_targeted'])
                >= (n // 2 + 1)),
            targeted_quality_noninferior=(
                _st.mean(paired['d_tq_targeted']) >= 0)),
        c6_all=all(all(r['preserved_byte_identical'].get(s)
                       for s in preserved) for r in d2s))
    # C7 (branch outputs pairwise distinct) is verified post-hoc from
    # each repeat's saved shared_outputs.json in the analysis step
    (base_dir / 'AGGREGATE.json').write_text(json.dumps(
        agg, indent=1, ensure_ascii=False))
    print('\n' + '=' * 60)
    print(f'AGGREGATE over {n} repeats:')
    for a in ('D0', 'D2', 'C'):
        print(f'  {a}: t_q {agg["per_arm"][a]["t_q"]} '
              f'eU {agg["per_arm"][a]["eU"]}')
    for k, v in paired.items():
        print(f'  {k}: mean {_st.mean(v):+.4f} '
              f'[{", ".join(f"{x:+.3f}" for x in v)}]')
    print(f'verdicts: {json.dumps(agg["verdicts"], ensure_ascii=False)}')
    print(f'\nCOMPLETE: {n} repeats x 18 calls, '
          f'¥{sum(r["budget"]["spent_cny"] for r in all_reps):.4f}')
    print(f'Run: {base_dir}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--approved-freeze-sha256', required=True)
    execute(p.parse_args())


if __name__ == '__main__':
    main()
