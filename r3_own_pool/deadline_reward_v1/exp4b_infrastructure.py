"""Experiment 4B: True DAG execution chain with real document
content, downstream consumption, and layered quality evaluation.

This fixes the fundamental flaw of exp4: nodes had synthetic labels
instead of actual document text, and downstream nodes didn't consume
upstream outputs.

Key guarantees:
1. Node prompts include ACTUAL document text (from the event doc)
2. Downstream nodes consume upstream OUTPUT (not labels)
3. Repair of upstream triggers downstream re-execution with the
   repaired output
4. Independent evaluator checks: contract, coverage, correctness
5. Zero-call e2e tests verify the chain before any real calls

Run: python3 -m deadline_reward_v1.exp4b_infrastructure --test
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from deadline_reward_v1.complex_dag import (
    STRUCTURES, topo_sort, downstream, enumerate_joint_actions,
    closure_options)
from deadline_reward_v1.full_dag_silver import doc_atoms
from deadline_reward_v1.full_dag_tasks import load_docs

HERE = Path(__file__).resolve().parent

# ---- node prompts with REAL document content ------------------------
def build_node_prompt(node_id, node_type, doc_text, upstream_outputs,
                      doc_id):
    """Build a node prompt that contains:
    - the node's task type and contract
    - ACTUAL document text (for extraction-type nodes)
    - ACTUAL upstream outputs (for downstream nodes)
    - the doc_id for citation"""
    parts = [f'你是一个资本市场事件调查助手。\n']
    parts.append(f'## 节点任务类型：{node_type}\n')

    if node_type == 'extraction':
        parts.append(f'## 任务：从证据文档中抽取原子事实\n')
        parts.append(f'## 证据文档 doc_id：{doc_id}\n')
        parts.append(f'## 文档内容：\n{doc_text[:3000]}\n')
        parts.append(f'## 输出要求：JSON数组，每条包含 fact, '
                      f'date, entities, evidence_doc_id={doc_id}\n')
    elif node_type == 'reasoning':
        parts.append(f'## 任务：基于上游抽取的事实进行推理\n')
        if upstream_outputs:
            parts.append(f'## 上游节点输出：\n')
            for up_id, up_out in upstream_outputs.items():
                parts.append(f'### {up_id}的输出：\n'
                             f'{str(up_out)[:2000]}\n')
        else:
            parts.append(f'## （无上游输出——独立节点）\n')
            parts.append(f'## 证据文档 doc_id：{doc_id}\n')
            parts.append(f'## 文档内容：\n{doc_text[:2000]}\n')
        parts.append(f'## 输出要求：JSON数组，每条包含 '
                      f'conclusion, evidence, confidence\n')
    elif node_type == 'verification':
        parts.append(f'## 任务：核查推理结论是否与事实一致\n')
        if upstream_outputs:
            parts.append(f'## 上游节点输出：\n')
            for up_id, up_out in upstream_outputs.items():
                parts.append(f'### {up_id}的输出：\n'
                             f'{str(up_out)[:2000]}\n')
        parts.append(f'## 证据文档摘要：\n{doc_text[:1000]}\n')
        parts.append(f'## 输出要求：JSON数组，每条包含 '
                      f'claim, verdict(SUPPORTED/UNSUPPORTED), '
                      f'evidence\n')
    else:
        parts.append(f'## 任务：综合所有信息\n')
        if upstream_outputs:
            for up_id, up_out in upstream_outputs.items():
                parts.append(f'### {up_id}：\n'
                             f'{str(up_out)[:1500]}\n')
        parts.append(f'## 输出要求：JSON对象\n')

    return '\n'.join(parts)


def build_node_types(edges):
    nodes = topo_sort(edges)
    depth = {}
    for n in nodes:
        depth[n] = max([depth[m] + 1 for m, vs in
                        edges.items() if n in vs] + [0])
    md = max(depth.values()) if depth else 0
    return {n: ('extraction' if depth[n] / max(1, md) < 0.34
                else 'reasoning' if depth[n] / max(1, md) < 0.67
                else 'verification') for n in nodes}


# ---- layered quality evaluation ---------------------------------------
def eval_contract(answer):
    """Layer 1: structural contract (parseable, non-empty)."""
    if not answer or not answer.strip():
        return 0.0
    t = answer.strip()
    if t.startswith('```'):
        parts = t.split('\n', 1)
        if len(parts) == 2:
            t = parts[1].rsplit('```', 1)[0].strip()
    try:
        obj = json.loads(t)
        items = obj if isinstance(obj, list) else [obj]
        return 1.0 if items else 0.0
    except (ValueError, TypeError):
        return 0.0


def eval_coverage(answer, doc_text):
    """Layer 2: doc-atom coverage (what fraction of the document's
    verifiable facts appear in the output)."""
    atoms = doc_atoms(doc_text)
    all_atoms = atoms['dates'] + atoms['amounts'] + atoms['penalties']
    if not all_atoms:
        return None  # untestable
    clean_ans = re.sub(r'\s+', '', answer or '')
    hits = sum(1 for a in all_atoms
               if re.sub(r'\s+', '', a) in clean_ans)
    return round(hits / len(all_atoms), 4)


def eval_correctness(answer, doc_text):
    """Layer 3: fact correctness (are the claimed facts actually
    supported by the document?). This is HARDER than coverage —
    it checks that the output's claims match the document."""
    # For now: use precision (fraction of output items that contain
    # at least one doc atom) as a proxy for correctness
    atoms = doc_atoms(doc_text)
    all_atoms = atoms['dates'] + atoms['amounts'] + atoms['penalties']
    if not all_atoms:
        return None
    # parse output items
    t = (answer or '').strip()
    if t.startswith('```'):
        parts = t.split('\n', 1)
        if len(parts) == 2:
            t = parts[1].rsplit('```', 1)[0].strip()
    try:
        obj = json.loads(t)
        items = obj if isinstance(obj, list) else [obj]
    except (ValueError, TypeError):
        items = [{'raw': t[i:i+100]}
                 for i in range(0, min(len(t), 500), 100)]
    if not items:
        return 0.0
    correct = sum(
        1 for item in items
        if isinstance(item, dict) and any(
            re.sub(r'\s+', '', a)
            in re.sub(r'\s+', '', json.dumps(item,
                                             ensure_ascii=False))
            for a in all_atoms))
    return round(correct / len(items), 4)


def eval_layered(all_answers, doc_text):
    """Full layered evaluation of a task's final state."""
    combined = ' '.join(str(a) for a in all_answers)
    return dict(
        contract=round(
            sum(eval_contract(a) for a in all_answers)
            / max(1, len(all_answers)), 4),
        coverage=eval_coverage(combined, doc_text),
        correctness=eval_correctness(combined, doc_text),
        correctness_status=('UNVERIFIED' if
                            eval_correctness(combined, doc_text)
                            is None else 'PROXY'),
        note='coverage != correctness; correctness uses output-item '
             'precision as proxy; true correctness requires human '
             'or oracle verification')


# ---- DAG execution chain (with real content propagation) --------------
class TrueDAGChain:
    """Executes a DAG where:
    - Each node gets a prompt with REAL document content
    - Downstream nodes consume ACTUAL upstream outputs
    - Repairing upstream invalidates and re-executes downstream
    - Cache: unaffected nodes keep their outputs"""

    def __init__(self, edges, node_types, doc_text, doc_id):
        self.edges = edges
        self.node_types = node_types
        self.doc_text = doc_text
        self.doc_id = doc_id
        self.outputs = {}  # node -> dict(answer, finish, tokens, ...)
        self.order = topo_sort(edges)

    def build_prompt(self, node):
        """Build prompt with real doc content + actual upstream
        outputs."""
        upstream = {}
        for pred in self.edges:
            if node in self.edges.get(pred, []):
                if pred in self.outputs:
                    upstream[pred] = self.outputs[pred].get(
                        'answer', '')
        return build_node_prompt(
            node, self.node_types.get(node, 'reasoning'),
            self.doc_text, upstream, self.doc_id)

    def execute_node(self, node, transport, creds, force_cap=None):
        """Execute one node (real call or simulated)."""
        prompt = self.build_prompt(node)
        model = 'deepseek-flash'
        o = transport(model, {}, prompt, creds,
                      force_max_tokens=force_cap)
        self.outputs[node] = o
        return o

    def inject_fault(self, node, fault_type, transport, creds):
        """Inject a fault at the specified node."""
        if fault_type == 'F_TRUNCATED':
            o = transport('deepseek-flash', {},
                          self.build_prompt(node), creds,
                          force_max_tokens=64)
            self.outputs[node] = o
        elif fault_type == 'F_JSON':
            # execute normally but replace the answer
            o = transport('deepseek-flash', {},
                          self.build_prompt(node), creds)
            self.outputs[node] = dict(
                o, answer='[{"fact":"占位","evidence_doc_id":"?"}]',
                finish_reason='stop')

    def repair_node(self, node, model, transport, creds):
        """Repair a node with the given model, then re-execute all
        stale downstream with the REPAIRED output propagating."""
        prompt = self.build_prompt(node)
        o = transport(model, {}, prompt, creds)
        self.outputs[node] = o
        # re-execute stale downstream (they consume the new output)
        stale = self.stale_downstream(node)
        for d in topo_sort(self.edges):
            if d in stale:
                prompt_d = self.build_prompt(d)
                o_d = transport('deepseek-flash', {},
                                prompt_d, creds)
                self.outputs[d] = o_d

    def stale_downstream(self, node):
        return {d for d in downstream(self.edges, node)
                if d in self.outputs}

    def run_planned(self, transport, creds, fault_node=None,
                    fault_type=None):
        """Execute all nodes in topological order; inject fault."""
        for node in self.order:
            if node == fault_node:
                self.inject_fault(node, fault_type, transport,
                                  creds)
            else:
                self.execute_node(node, transport, creds)

    def evaluate(self):
        """Independent layered evaluation of final outputs."""
        answers = [self.outputs.get(n, {}).get('answer', '')
                   for n in self.order if n in self.outputs]
        return eval_layered(answers, self.doc_text)


# ---- zero-call e2e test ------------------------------------------------
def test_execution_chain():
    """Verify: doc content in prompts, downstream consumes upstream,
    fault propagates, repair propagates, evaluator detects quality
    difference, cache works."""
    edges = {'n0': ['n1'], 'n1': ['n2'], 'n2': []}  # chain_3
    node_types = {'n0': 'extraction', 'n1': 'reasoning',
                  'n2': 'verification'}
    doc_text = ('2024年4月24日，中国证监会对ST西王处以1000万元罚款。'
                '公司于2022年11月4日收到立案告知书。'
                '2023年6月30日收到事先告知书。')
    doc_id = 'test_doc'

    checks = {}

    # 1. Prompt contains document text
    chain = TrueDAGChain(edges, node_types, doc_text, doc_id)
    p0 = chain.build_prompt('n0')
    checks['doc_in_prompt'] = ('2024年4月24日' in p0
                               and '1000万元' in p0)

    # 2. Downstream consumes upstream (simulate)
    fake_outputs = {
        'n0': {'answer': '[{"fact":"证监会对ST西王罚款1000万元",'
                        '"date":"2024-04-24"}]',
               'finish_reason': 'stop'},
        'n1': {'answer': '[{"conclusion":"公司被处罚",'
                        '"evidence":"n0"}]',
               'finish_reason': 'stop'}}
    chain.outputs = fake_outputs
    p1 = chain.build_prompt('n1')
    checks['upstream_in_downstream_prompt'] = (
        '证监会对ST西王罚款' in p1)

    # 3. Fault propagation: if n0 is garbage, n1's prompt contains
    #    garbage
    chain.outputs['n0'] = {'answer': 'garbage_output'}
    p1_bad = chain.build_prompt('n1')
    checks['fault_propagates'] = ('garbage_output' in p1_bad)

    # 4. Repair propagation: if n0 is repaired, n1's prompt has the
    #    repaired output
    chain.outputs['n0'] = {'answer': '[{"fact":"修复后的正确事实"}]'}
    p1_fixed = chain.build_prompt('n1')
    checks['repair_propagates'] = ('修复后的正确事实' in p1_fixed)

    # 5. Evaluator detects quality difference
    good_answer = ('[{"fact":"2024年4月24日证监会罚款1000万元",'
                   '"evidence_doc_id":"test_doc"}]')
    bad_answer = '[{"fact":"完全无关的内容"}]'
    good_eval = eval_layered([good_answer], doc_text)
    bad_eval = eval_layered([bad_answer], doc_text)
    checks['evaluator_detects_difference'] = (
        good_eval['coverage'] is not None
        and good_eval['coverage'] > bad_eval['coverage'])

    # 6. Coverage != correctness (different dimensions)
    checks['coverage_ne_correctness'] = (
        good_eval['coverage'] != good_eval['correctness']
        or good_eval['coverage'] is None)

    # 7. Contract layer separately measurable
    checks['contract_layer'] = (
        eval_contract(good_answer) == 1.0
        and eval_contract('not json') == 0.0)

    # 8. Stale downstream tracking
    chain2 = TrueDAGChain(edges, node_types, doc_text, doc_id)
    chain2.outputs = {'n0': {'answer': 'a'}, 'n1': {'answer': 'b'},
                      'n2': {'answer': 'c'}}
    checks['stale_tracking'] = (
        chain2.stale_downstream('n0') == {'n1', 'n2'}
        and chain2.stale_downstream('n1') == {'n2'}
        and chain2.stale_downstream('n2') == set())

    print(json.dumps(checks, indent=1))
    all_pass = all(checks.values())
    print(f'\nE2E TEST: {"ALL PASS" if all_pass else "FAIL"}')
    return 0 if all_pass else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    if args.test:
        raise SystemExit(test_execution_chain())
    raise SystemExit(test_execution_chain())
