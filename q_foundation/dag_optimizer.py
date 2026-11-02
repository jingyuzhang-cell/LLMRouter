"""Programmatic DAG Structure Optimizer (zero model calls).

Consumes LLM-generated DAG JSON, applies rule-based structural optimization,
produces optimized DAG + change log. No LLM calls — all rules are programmatic.

Optimization actions: MERGE_NODES, SPLIT_NODE, REMOVE_EDGE, ADD_EDGE,
REMOVE_NODE, ADD_NODE.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class DAGNode:
    node_id: str
    task: str
    kind: str          # extracts | reasoning | verification | report
    doc_refs: Tuple[str, ...]


@dataclass
class DAG:
    nodes: List[DAGNode]
    edges: List[Tuple[str, str]]

    def get_node(self, nid) -> Optional[DAGNode]:
        return next((n for n in self.nodes if n.node_id == nid), None)

    def get_parents(self, nid) -> List[str]:
        return [f for f, t in self.edges if t == nid]

    def get_children(self, nid) -> List[str]:
        return [t for f, t in self.edges if f == nid]

    def get_upstream_docs(self, nid, visited=None) -> set:
        if visited is None:
            visited = set()
        if nid in visited:
            return set()
        visited.add(nid)
        docs = set(self.get_node(nid).doc_refs) if self.get_node(nid) else set()
        for p in self.get_parents(nid):
            docs |= self.get_upstream_docs(p, visited)
        return docs

    def is_terminal(self, nid) -> bool:
        return len(self.get_children(nid)) == 0

    def depth(self) -> int:
        """Longest path from any source to any sink."""
        memo = {}
        def d(nid):
            if nid in memo:
                return memo[nid]
            parents = self.get_parents(nid)
            if not parents:
                memo[nid] = 1
            else:
                memo[nid] = 1 + max(d(p) for p in parents)
            return memo[nid]
        return max(d(n.node_id) for n in self.nodes) if self.nodes else 0

    def max_parallel_width(self) -> int:
        """Maximum number of nodes at any depth level."""
        levels = {}
        memo = {}
        def d(nid):
            if nid in memo:
                return memo[nid]
            parents = self.get_parents(nid)
            memo[nid] = 1 if not parents else 1 + max(d(p) for p in parents)
            return memo[nid]
        for n in self.nodes:
            level = d(n.node_id)
            levels[level] = levels.get(level, 0) + 1
        return max(levels.values()) if levels else 0

    def to_dict(self):
        return {
            'nodes': [{'node_id': n.node_id, 'task': n.task, 'kind': n.kind,
                       'doc_refs': list(n.doc_refs)} for n in self.nodes],
            'edges': [{'from': f, 'to': t} for f, t in self.edges]
        }

    def stats(self):
        return {'n_nodes': len(self.nodes), 'n_edges': len(self.edges),
                'depth': self.depth(), 'max_parallel_width': self.max_parallel_width()}


def parse_llm_dag(dag_json: dict) -> DAG:
    nodes = [DAGNode(
        node_id=n['id'], task=n.get('task', ''),
        kind=n.get('kind', 'other'),
        doc_refs=tuple(n.get('doc_refs', []))
    ) for n in dag_json.get('nodes', [])]
    edges = [(e['from'], e['to']) for e in dag_json.get('edges', [])]
    return DAG(nodes=nodes, edges=edges)


def _task_similarity(t1, t2) -> float:
    """Duplicate-detection similarity for mixed CJK/English task text.

    Character bigrams fragment when an LLM reorders words ('提取财务数据 from
    doc2' vs '提取doc2财务数据'), so score CJK char-unigrams + whole
    alphanumeric tokens instead (reordering- and filler-robust). Quantity /
    time-range expressions are significant: a mismatch in digit-bearing
    tokens ('2023年' vs '2024年', 'doc2' vs 'doc5') or in CJK numeral runs
    ('近三年' vs '近五年', '第四次' vs '首次') vetoes the merge outright.

    Known limitation (operator P1 acceptance note): entity-level and
    target-fact-level equivalence is not checked; same-kind + same-docs +
    numeral consistency + >0.7 similarity are necessary, not sufficient.
    All merges are logged and auditable; false merges surface as optimizer
    findings, never silently dropped.
    """
    NUMERAL = '零一二三四五六七八九十百千万两首末初'
    sig_re = re.compile('[' + NUMERAL + ']+')

    def toks(s):
        s = s.lower()
        cjk = set(re.findall(r'[\u4e00-\u9fff]', s))
        alnum = set(re.findall(r'[a-z0-9]+', s))
        return cjk, alnum
    c1, a1 = toks(t1)
    c2, a2 = toks(t2)
    sig1 = ({t for t in a1 if any(c.isdigit() for c in t)}
            | set(sig_re.findall(t1)))
    sig2 = ({t for t in a2 if any(c.isdigit() for c in t)}
            | set(sig_re.findall(t2)))
    if sig1 != sig2:
        return 0.0
    t1_all, t2_all = c1 | a1, c2 | a2
    return len(t1_all & t2_all) / max(len(t1_all | t2_all), 1)


def optimize_dag(dag: DAG, available_docs: List[str]) -> Tuple[DAG, List[dict]]:
    """Apply rule-based structural optimization. Returns (optimized_dag, changes)."""
    changes = []
    nodes = list(dag.nodes)
    edges = list(dag.edges)

    # === Rule 1: MERGE_NODES — duplicate task + same docs ===
    i = 0
    while i < len(nodes):
        j = i + 1
        while j < len(nodes):
            n1, n2 = nodes[i], nodes[j]
            if (n1.kind == n2.kind and
                    set(n1.doc_refs) == set(n2.doc_refs) and
                    _task_similarity(n1.task, n2.task) > 0.7):
                # Merge: keep n1, redirect n2's edges to n1
                changes.append({
                    'action': 'MERGE_NODES',
                    'detail': f'Merged {n2.node_id} into {n1.node_id} '
                              f'(same kind+docs, task similarity >0.7)'})
                edges = [(f if f != n2.node_id else n1.node_id,
                          t if t != n2.node_id else n1.node_id) for f, t in edges]
                # Remove self-loops and dedup parallel edges created by redirect
                edges = [(f, t) for f, t in edges if f != t]
                edges = list(dict.fromkeys(edges))
                nodes.pop(j)
            else:
                j += 1
        i += 1

    # === Rule 2: REMOVE_EDGE — false dependency (no doc/data flow) ===
    valid_node_ids = {n.node_id for n in nodes}
    new_edges = []
    for f, t in edges:
        if f not in valid_node_ids or t not in valid_node_ids:
            continue
        parent = dag.get_node(f) if dag else None
        child = dag.get_node(t) if dag else None
        # Check if parent produces anything the child actually needs
        parent_node = next((n for n in nodes if n.node_id == f), None)
        child_node = next((n for n in nodes if n.node_id == t), None)
        if parent_node and child_node:
            parent_docs = set(parent_node.doc_refs)
            child_needs = set(child_node.doc_refs)
            # If child doesn't reference any of parent's docs AND child's kind
            # doesn't inherently depend on parent's kind, edge may be false
            # Children that consume upstream *outputs* (not raw docs) are
            # inherently dependent on any parent: reasoning, timeline,
            # verification, report. Only doc-grounded children (extracts)
            # can have a provably false parent edge.
            kind_dep = child_node.kind in ('reasoning', 'timeline',
                                           'verification', 'report')
            if not kind_dep and not (parent_docs & child_needs):
                changes.append({
                    'action': 'REMOVE_EDGE',
                    'detail': f'Removed {f}→{t} (no doc flow, no kind dependency)'})
                continue
        new_edges.append((f, t))
    edges = new_edges

    # === Rule 3: REMOVE_NODE — orphan (no consumers, not terminal/report) ===
    terminal_ids = {n.node_id for n in nodes
                    if n.kind == 'report' or n.node_id.startswith('final') or
                    n.node_id.startswith('terminal')}
    node_ids = {n.node_id for n in nodes}
    has_children = {f for f, t in edges}
    orphan_ids = [nid for nid in node_ids
                  if nid not in has_children and nid not in terminal_ids]
    for oid in orphan_ids:
        changes.append({
            'action': 'REMOVE_NODE',
            'detail': f'Removed {oid} (no downstream consumer, not terminal)'})
        nodes = [n for n in nodes if n.node_id != oid]
        edges = [(f, t) for f, t in edges if f != oid and t != oid]

    # === Rule 4: ADD_EDGE — missing dependency (only for extracts→reasoning/verification) ===
    for child in nodes:
        # Only reasoning/verification/report nodes need upstream extracts
        if child.kind not in ('reasoning', 'verification', 'report'):
            continue
        # Find extracts nodes that have docs the child references but can't access
        for parent in nodes:
            if parent.node_id == child.node_id or parent.kind != 'extracts':
                continue
            if (parent.node_id, child.node_id) in edges:
                continue
            # Only add if child actually references parent's docs
            parent_docs = set(parent.doc_refs)
            child_docs = set(child.doc_refs)
            if not (parent_docs & child_docs):
                continue
            # Check no existing path (avoid cycles)
            existing_upstream = set()
            for p in [f for f, t in edges if t == child.node_id]:
                node = next((n for n in nodes if n.node_id == p), None)
                if node:
                    existing_upstream |= set(node.doc_refs)
                    # Also check transitively
                    for pp in [f for f, t in edges if t == p]:
                        pn = next((n for n in nodes if n.node_id == pp), None)
                        if pn:
                            existing_upstream |= set(pn.doc_refs)
            # Only add if child can't already access parent's docs via existing edges
            if not (parent_docs & child_docs - existing_upstream):
                continue
            # Check this edge doesn't create a cycle (parent not downstream of child)
            if would_create_cycle(parent.node_id, child.node_id, edges):
                continue
            changes.append({
                'action': 'ADD_EDGE',
                'detail': f'Added {parent.node_id}→{child.node_id} '
                          f'(child {child.kind} needs docs from {parent_docs & child_docs})'})
            edges.append((parent.node_id, child.node_id))

    optimized = DAG(nodes=nodes, edges=edges)
    return optimized, changes


def evaluate_dag_structure(dag: DAG, reference: Optional[DAG] = None) -> dict:
    """Programmatic DAG structure evaluation."""
    stats = dag.stats()
    result = {'structure': stats}

    if reference:
        ref_stats = reference.stats()
        result['vs_reference'] = {
            'node_diff': stats['n_nodes'] - ref_stats['n_nodes'],
            'depth_diff': stats['depth'] - ref_stats['depth'],
            'width_diff': stats['max_parallel_width'] - ref_stats['max_parallel_width'],
        }

    # Structural quality checks
    issues = []
    if stats['depth'] > 6:
        issues.append('DEEP_DAG: depth>6 may indicate unnecessary serialization')
    if stats['max_parallel_width'] < 2:
        issues.append('NO_PARALLELISM: no independent branches detected')
    if stats['n_nodes'] > 12:
        issues.append('OVER_SPLIT: >12 nodes may indicate over-splitting')
    if stats['n_nodes'] < 3:
        issues.append('UNDER_SPLIT: <3 nodes may under-utilize parallelism')
    result['issues'] = issues

    return result


def would_create_cycle(from_id, to_id, edges):
    """Check if adding edge from_id→to_id creates a cycle."""
    # If to_id can already reach from_id, adding creates cycle
    visited = set()
    stack = [to_id]
    while stack:
        current = stack.pop()
        if current == from_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        for f, t in edges:
            if f == current:
                stack.append(t)
    return False
