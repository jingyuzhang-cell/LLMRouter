"""runtime_v2_exec — Part 2: generic heterogeneous node execution
adapter. Unified I/O contracts, upstream consumption, anomaly
detection, per-node Q/C/L/E metering, call ledger. Backends:

  ReplayBackend  (zero-call): produces contract-conformant outputs
                 from frozen texts / templates; labeled REPLAY.
  RealBackend    (gated): GLM-Flash via the frozen transport; env
                 RUNTIME_V2_GO=1 + hard call/cash caps; every call
                 ledged. Not invoked in this zero-call round.

Contract enforcement: the node output must parse as JSON with all
'produces' fields present; otherwise the node is marked BAD
(anomaly event) — the runtime's feedback signal.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

HERE = Path('/root/r3_own_pool/deadline_reward_v1')
LEDGER_PATH = HERE / 'runtime_v2_corpus' / 'NODE_LEDGER.jsonl'

ROLE_PROMPTS = {
    'retrieval': '检索并返回证据文档列表。',
    'extraction': '从证据文档抽取原子事实（含日期/金额/主体），'
                  '输出 JSON。',
    'timeline': '整理时间线，输出 JSON。',
    'amounts': '汇总金额类事实，输出 JSON。',
    'penalties': '梳理处罚决定，输出 JSON。',
    'entity_relations': '识别涉事主体及关系，输出 JSON。',
    'entity_graph': '构建主体关系图谱，输出 JSON。',
    'timeline_deep': '时间线阶段复核，输出 JSON。',
    'amounts_check': '金额交叉复核，输出 JSON。',
    'cross_check': '跨来源核验，输出 JSON。',
    'merge': '合并多来源内容，输出 JSON。',
    'synthesis': '汇总全部上游，输出最终调查结论 JSON。',
}


def enforce_contract(text, produces, require_nonempty=True):
    """returns (ok, obj). Fence-strip + parse + field presence +
    content gate: empty values fail (reason recorded in ledger;
    the node is BAD for scheduling but observable)."""
    t = (text or '').strip()
    if t.startswith('```'):
        parts = t.split('\n', 1)
        t = parts[1].rsplit('```', 1)[0].strip() if len(parts) == 2 else t
    import re
    m = re.search(r'\{.*\}|\[.*\]', t, re.S)
    if m:
        t = m.group(0)
    try:
        obj = json.loads(t)
    except Exception:
        return False, ('reason', 'parse_fail'), None
    if isinstance(obj, dict):
        for f in produces:
            if f not in obj:
                return False, ('reason', 'missing_field:' + f), obj
            if require_nonempty:
                v = obj[f]
                if v is None or v == [] or v == {} or \
                        (isinstance(v, str) and not v.strip()):
                    return False, ('reason', 'empty_field:' + f), obj
    return True, None, obj


class Meter:
    def __init__(self):
        self.calls = 0
        self.cash = 0.0
        self.tokens = 0
        self.lat = 0.0
        self.events = []

    def ledger(self, rec):
        with open(LEDGER_PATH, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')


ROLE_LAT_TOK = {  # per-role means from frozen ledgers (2026-10)
    'extraction': (13.0, 2900), 'timeline': (14.5, 2300),
    'amounts': (13.5, 2200), 'penalties': (14.0, 2400),
    'entity_relations': (14.5, 2200), 'timeline_deep': (13.0, 2100),
    'amounts_check': (12.5, 2000), 'cross_check': (13.0, 2100),
    'merge': (14.0, 2300), 'entity_graph': (14.5, 2200),
    'synthesis': (28.0, 4900), 'retrieval': (2.0, 300),
}


class ReplayBackend:
    """zero-call backend. Retrieval nodes go through providers; LLM
    nodes produce deterministic contract-conformant JSON built from
    upstream content (labeled REPLAY — never reported as real)."""

    source_tag = 'REPLAY'

    def __init__(self, meter, retrieval_provider):
        self.meter = meter
        self.rp = retrieval_provider

    def predict_eU(self, rt, Rset, pi, pred_q, pred_cost):
        """planner-tier predicted eU for arbitrary specs."""
        import dag_runtime_v1 as R1
        nodes = {n['id']: n for n in rt.spec['nodes']}
        todo = [n['id'] for n in rt.spec['nodes']
                if n['id'] not in rt.state
                or rt.state[n['id']].status == 'bad' or n['id'] in Rset]
        cash = rt.spent['cash'] + sum(
            pred_cost(nodes[i], pi.get(i, 'Flash')) for i in todo)
        if cash > rt.Ccap + 1e-12:
            return -9.0
        tok = rt.spent['tokens'] + sum(
            ROLE_LAT_TOK.get(nodes[i]['role'], (13.0, 2200))[1]
            for i in todo)
        # level-serial latency over todo
        lvl = {}
        for i in todo:
            d = 0
            stack = list(nodes[i]['inputs'])
            seen = set()
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                if x in todo and x != i:
                    d = max(d, 1)
                    stack.extend(nodes[x]['inputs'])
            lvl.setdefault(d, []).append(i)
        lat = rt.spent['lat'] + sum(
            max(ROLE_LAT_TOK.get(nodes[i]['role'], (13.0, 2200))[0]
                for i in ids) for ids in lvl.values())
        if lat > rt.D + 1e-9:
            return -9.0
        w = 1.0 / len(nodes)
        q = 0.0
        for n in rt.spec['nodes']:
            nid = n['id']
            if nid in Rset or (nid in todo and
                               (nid not in rt.state or
                                rt.state[nid].status == 'bad')):
                q += w * pred_q(n, pi.get(nid, 'Flash'))
            elif nid in rt.state and nid not in todo:
                q += w * rt.state[nid].q
            elif nid in todo:
                q += w * pred_q(n, pi.get(nid, 'Flash'))
            else:
                q += w * 0.0
        return q - 0.5 * tok / 60000.0 - max(0.0, lat - rt.D) / rt.D

    def execute(self, node, model, upstream_results):
        t0 = time.perf_counter()
        if upstream_results and not isinstance(
                upstream_results[0], tuple):
            ids = node['inputs']
            us = [(ids[i] if i < len(ids) else f'u{i}', u)
                  for i, u in enumerate(upstream_results)]
        else:
            us = list(upstream_results or [])
        lat = 2.0 + 0.5 * len(json.dumps(
            [u.output_text[:200] for _, u in us],
            ensure_ascii=False)) / 500.0
        lat = min(lat, 12.0)
        tok = 800 + 200 * len(upstream_results)
        if node['role'] == 'retrieval':
            docs = self.rp.search(node.get('query', node['id']),
                                  source=node.get('source'))
            text = json.dumps(
                {node['contract']['produces'][0]:
                 [dict(doc_id=d['doc_id'], title=d['title'])
                  for d in docs]}, ensure_ascii=False)
        else:
            payload = {}
            doc_text = node.get('_doc_text')
            for f in node['contract']['produces']:
                payload[f] = [
                    dict(from_upstream=nid, content=u.output_text[:800])
                    for nid, u in us][:4] or (
                    dict(source='evidence_doc',
                         content=(doc_text or '')[:2000])
                    if doc_text else 'derived')
            text = json.dumps(payload, ensure_ascii=False)
        ok, _why, obj = enforce_contract(text, node['contract']['produces'])
        self.meter.calls += 1
        self.meter.tokens += tok
        self.meter.lat += lat
        self.meter.ledger(dict(backend='replay', node=node['id'],
                               role=node['role'], model=model,
                               contract_ok=ok, tokens=tok,
                               lat=round(lat, 2), cash=0.0))
        from dag_runtime_v1 import NodeResult
        return NodeResult(status='done' if ok else 'bad',
                          output_text=text[:4000], q=0.0, tokens=tok,
                          lat=lat, cash=0.0, model=model,
                          source=self.source_tag)


class RealBackend(ReplayBackend):
    """GLM-Flash execution (gated). Same contracts/metering; prompt =
    role instruction + upstream outputs + contract requirements.
    Inherits retrieval handling (providers) from ReplayBackend."""

    source_tag = 'REAL_GLM_FLASH'

    def __init__(self, meter, retrieval_provider, cap_calls=40,
                 cap_cash=0.0):
        super().__init__(meter, retrieval_provider)
        self.cap_calls = cap_calls
        self.cap_cash = cap_cash
        import sys
        sys.path.insert(0, '/root/r3_own_pool')
        from deadline_reward_v1.r2fix_runner import call_ds, \
            load_env_creds
        self._call_ds = call_ds
        self._creds = load_env_creds()

    def execute(self, node, model, upstream_results):
        if os.environ.get('RUNTIME_V2_GO') != '1':
            raise PermissionError('RealBackend requires RUNTIME_V2_GO=1')
        if self.meter.calls >= self.cap_calls:
            raise RuntimeError('node call cap')
        if model != 'Flash':
            raise RuntimeError('real phase round-1: Flash-only (¥0)')
        prompt = self._build_prompt(node, upstream_results)
        o = self._call_ds(prompt, self._creds, max_out_tokens=3072)
        self.meter.calls += 1
        self.meter.cash += float(o.get('cash_cny', 0.0) or 0.0)
        if self.meter.cash > self.cap_cash + 1e-9:
            raise RuntimeError(f'cash cap {self.meter.cash}')
        ok, why, obj = enforce_contract(o['answer'],
                                        node['contract']['produces'])
        self.meter.tokens += o['tokens_in'] + o['tokens_out']
        self.meter.lat += o['latency_s']
        self.meter.ledger(dict(backend='real', node=node['id'],
                                role=node['role'], model=model,
                                contract_ok=ok,
                                fail_reason=(why[1] if why else None),
                                tokens=o['tokens_in'] + o['tokens_out'],
                                lat=round(o['latency_s'], 2),
                                cash=o.get('cash_cny', 0.0),
                                output_text=o['answer']))   # FULL: scoring consumes complete answers; truncation only for display
        from dag_runtime_v1 import NodeResult
        return NodeResult(status='done' if ok else 'bad',
                          output_text=o['answer'], q=0.0,
                          tokens=o['tokens_in'] + o['tokens_out'],
                          lat=o['latency_s'],
                          cash=float(o.get('cash_cny', 0.0) or 0.0),
                          model=model, source=self.source_tag)

    def _build_prompt(self, node, upstream_results):
        head = ROLE_PROMPTS.get(node['role'], node['role'])
        parts = [f'你是调查DAG中的节点执行者。\n任务：{head}\n']
        doc = node.get('_doc_text')
        if doc:
            parts += ['## 证据文档（任务事实的唯一来源，内容必须'
                      '出自此处，不得留空）：', doc, '']
        for nid_u in upstream_results:
            nid, u = (nid_u if isinstance(nid_u, tuple)
                      else ('upstream', nid_u))
            parts.append(f'## 上游 {nid} 输出：\n'
                         f'{u.output_text[:2500]}\n')
        parts.append('## 输出要求：只输出 JSON 对象，包含字段：'
                     + ', '.join(node['contract']['produces'])
                     + '。禁止输出非JSON文本。')
        return '\n'.join(parts)
