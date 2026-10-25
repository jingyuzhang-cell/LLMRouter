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
  Budget   adaptive worst-case guard, planned 18 calls, cap ¥0.30,
           wall 1800s, fail-stop on first error (no retries)

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

from deadline_reward_v1.budget_guard import BudgetGuard, worst_case_cny
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


def call_ds(prompt: str, creds: dict):
    import requests
    body = dict(model='deepseek-flash', max_tokens=2048,
                messages=[dict(role='user', content=prompt)],
                temperature=0.0, thinking={'type': 'disabled'})
    t0 = time.time()
    resp = requests.post(
        'https://api.deepseek.com/chat/completions',
        headers={'Authorization': f'Bearer {creds["DEEPSEEK_API_KEY"]}',
                 'Content-Type': 'application/json'},
        json=body, timeout=180)
    lat = time.time() - t0
    d = resp.json()
    ch = d.get('choices', [{}])[0]
    u = d.get('usage', {})
    tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
    if resp.status_code != 200 or not ch.get('message', {}).get('content'):
        raise RuntimeError(f'API error: HTTP {resp.status_code} '
                           f'{str(d)[:200]}')
    return dict(answer=ch['message']['content'],
                finish_reason=ch.get('finish_reason'),
                tokens_in=tin, tokens_out=tout,
                cash_cny=round((tin * 2.13 + tout * 8.52) / 1e6, 6),
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
    if f['doc_slot'] != DOC_SLOT or f['fault'] != FAULT:
        raise PermissionError('freeze design mismatch')
    return f


def execute(args):
    freeze = gates(args)
    valid_keys = freeze['valid_keys']
    creds = load_env_creds()
    doc = load_docs()[DOC_SLOT]
    d2_closure, c_full, preserved = closures()
    guard = BudgetGuard(PLANNED_CALLS, CAP_CNY, mode='adaptive',
                        wall_seconds=WALL_S)
    run_dir = HERE / 'fe_screening_runs' / time.strftime(
        'r2fix_%Y%m%d_%H%M%S')
    run_dir.mkdir(parents=True)
    results = []
    from copy import deepcopy

    def call_checked(dag, node, replace_garbage=False):
        prompt = dag.build_prompt(node)
        stop = guard.may_start(prompt_chars=len(prompt))
        if stop:
            raise RuntimeError(f'budget stop: {stop}')
        o = call_ds(prompt, creds)
        if replace_garbage:
            o = dict(o, answer=GARBAGE, finish_reason='stop')
        dag.outputs[node] = o
        guard.record(o['cash_cny'])
        print(f'  {node} [{ROLE[node]}]: {o["latency_s"]}s '
              f'len={len(o["answer"])} '
              f'{"<-GARBAGE" if replace_garbage else ""}', flush=True)
        return o

    try:
        chain = HeteroDAG(doc['text'], doc['doc_id'])
        clk = tok = 0.0
        for node in chain.order:
            o = call_checked(chain, node, replace_garbage=(node == FAULT))
            clk += o['latency_s']
            tok += o['tokens_in'] + o['tokens_out']
        shared, sh_clk, sh_tok = deepcopy(chain.outputs), clk, tok
        (run_dir / 'shared_outputs.json').write_text(json.dumps(
            {n: dict(answer=o['answer'][:2000], role=ROLE[n])
             for n, o in shared.items()}, indent=1, ensure_ascii=False))
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
            pres = {n: (ac.outputs[n]['answer'] == shared[n]['answer'])
                    for n in preserved}
            results.append(dict(
                arm=label, calls=len(closure), t_q=full['terminal_q'],
                hits=full['terminal_hits'], n_ref=full['n_ref'],
                p_q=full['pipeline_q'], by_category=by_cat,
                tokens=int(r_tok), latency=round(r_clk, 1),
                met=r_clk <= D, eU=round(eu, 4),
                preserved_byte_identical=pres,
                lost_in_synthesis=full['lost_in_synthesis']))
            (run_dir / f'{label}_outputs.json').write_text(json.dumps(
                {n: dict(answer=o['answer'][:2000], role=ROLE[n])
                 for n, o in ac.outputs.items()}, indent=1,
                ensure_ascii=False))
            print(f'{label}: t_q={full["terminal_q"]:.3f} '
                  f'({full["terminal_hits"]}/{full["n_ref"]}) '
                  f'cats={by_cat} eU={eu:+.4f}', flush=True)

        # D0: accept garbage, zero calls
        full0, cat0 = eval_by_category(shared, valid_keys)
        results.append(dict(
            arm='D0', calls=0, t_q=full0['terminal_q'],
            hits=full0['terminal_hits'], n_ref=full0['n_ref'],
            p_q=full0['pipeline_q'], by_category=cat0, tokens=int(sh_tok),
            latency=round(sh_clk, 1), met=sh_clk <= D,
            eU=round(utility(full0['terminal_q'], sh_tok, sh_clk), 4),
            preserved_byte_identical={}, 
            lost_in_synthesis=full0['lost_in_synthesis']))
        print(f'D0: t_q={full0["terminal_q"]:.3f} cats={cat0}', flush=True)

        arm('D2', d2_closure)
        arm('C', c_full)

        (run_dir / 'R2FIX_RESULTS.json').write_text(json.dumps(dict(
            status='COMPLETE', results=results,
            fault=FAULT, d2_closure=sorted(d2_closure),
            c_full=sorted(c_full),
            preserved_siblings=sorted(preserved),
            doc=DOC_SLOT, budget=guard.snapshot()), indent=1))
        print(f'\nCOMPLETE: {guard.calls} calls, ¥{guard.spent:.4f}')
    except BaseException as exc:
        (run_dir / 'R2FIX_INCOMPLETE.json').write_text(json.dumps(dict(
            status='INCOMPLETE', reason=repr(exc), results=results,
            budget=guard.snapshot(),
            traceback=traceback.format_exc()), indent=1))
        print(f'INCOMPLETE: {exc}')
    print(f'Run: {run_dir}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--approved-freeze-sha256', required=True)
    execute(p.parse_args())


if __name__ == '__main__':
    main()
