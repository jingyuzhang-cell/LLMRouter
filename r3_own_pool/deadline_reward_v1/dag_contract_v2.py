"""dag_contract_v2.py — Fact-pass-through DAG contract (structural fix, zero-call).

OLD CONTRACT (information bottleneck):
  n_main/n_sup1/n_sup2 → merge → verify → sink
  verify output: {item, doc_a, doc_b, verdict, note}
  sink consumes ONLY verify output → facts not in verify are LOST

  Measured loss (Flash verify): 18/20 key facts dropped (pass-through = 10%).

NEW CONTRACT (fact bypass):
  n_main/n_sup1/n_sup2 → merge ─────────────────→ sink (full fact set)
                         ↓
                      verify ───────────────────→ sink (verdicts only)
  verify output: {fact_ids_checked, verdict, evidence, note}
  sink consumes BOTH merge facts AND verify verdicts

  DAG edges: merge→verify, merge→sink, verify→sink
  (sink depends on BOTH; verify no longer blocks fact flow)

Recovery semantics:
  - closure(n_sup2) = {n_sup2, merge, verify, sink} (unchanged dependency)
  - If verify FAILS: sink consumes merge facts + UNVERIFIED marker (legal degradation)
  - If n_sup2 FAILS: merge has placeholder, verify checks remaining facts,
    sink gets facts + partial verdicts
  - Cache: merge output cached by input hash (all 3 extractions); verify cached
    separately by merge version; sink depends on both merge+verify versions
"""
import hashlib
import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Fact:
    fact_id: str
    content: str
    doc_id: str
    quote: str
    date: str = ''
    amount: str = ''


@dataclass
class MergeOutput:
    """Complete fact set with provenance — the single source of truth."""
    facts: list = field(default_factory=list)
    version: int = 0

    def add(self, fact: Fact):
        self.facts.append(fact)
        self.version += 1

    def fact_ids(self):
        return {f.fact_id for f in self.facts}

    def by_doc(self, doc_id):
        return [f for f in self.facts if f.doc_id == doc_id]

    def hash(self):
        return hashlib.sha256(
            json.dumps([f.fact_id for f in sorted(self.facts, key=lambda x: x.fact_id)]).encode()
        ).hexdigest()[:12]


@dataclass
class VerifyOutput:
    """Verdicts only — does NOT carry facts (they flow merge→sink directly)."""
    verdicts: list = field(default_factory=list)  # [{fact_id, verdict, note}]
    unverified_facts: list = field(default_factory=list)  # fact_ids not checked
    merge_version: str = ''

    def verdict_for(self, fact_id):
        for v in self.verdicts:
            if v['fact_id'] == fact_id:
                return v['verdict']
        return 'UNCHECKED'


@dataclass
class SinkInput:
    """Sink receives BOTH the full fact set AND verification verdicts."""
    merge: MergeOutput = None
    verify: VerifyOutput = None

    def all_facts(self):
        return self.merge.facts if self.merge else []

    def fact_with_verdict(self):
        out = []
        for f in (self.merge.facts if self.merge else []):
            v = self.verify.verdict_for(f.fact_id) if self.verify else 'UNVERIFIED'
            out.append({**f.__dict__, 'verify_status': v})
        return out

    def fact_pass_through(self):
        """How many facts from merge reach sink (should be 100% in new contract)."""
        return len(self.all_facts())


# DAG structure (new)
NEW_EDGES = {
    'n_main': ['merge'],
    'n_sup1': ['merge'],
    'n_sup2': ['merge'],
    'merge': ['verify', 'sink'],      # KEY CHANGE: merge→sink direct edge
    'verify': ['sink'],
    'sink': [],
}

OLD_EDGES = {
    'n_main': ['merge'],
    'n_sup1': ['merge'],
    'n_sup2': ['merge'],
    'merge': ['verify'],
    'verify': ['sink'],               # OLD: verify blocks all flow to sink
    'sink': [],
}


def closure_new(node, edges=NEW_EDGES):
    """Recovery closure under new contract."""
    desc = set()
    stack = [node]
    while stack:
        u = stack.pop()
        for v in edges.get(u, []):
            if v not in desc:
                desc.add(v)
                stack.append(v)
    return desc


def closure_old(node, edges=OLD_EDGES):
    return closure_new(node, edges)


# Verify-failure degradation
def verify_failed_sink_input(merge_output):
    """When verify fails: sink gets facts + UNVERIFIED marker for all."""
    vo = VerifyOutput(verdicts=[], unverified_facts=merge_output.fact_ids(),
                      merge_version=merge_output.hash())
    return SinkInput(merge=merge_output, verify=vo)


# Prompt templates for new contract
MERGE_PROMPT = None  # Program node, zero LLM calls

VERIFY_PROMPT_NEW = """你是一个资本市场事件调查助手。
## 节点任务类型：verify（跨公告一致性核验）
## 上游合并事实集（唯一信息来源）：
{facts_json}

## 任务要求：核验事实集中跨文档的事实关系（同一事件在不同公告中的一致性/互补性/冲突）。
输出每条含 fact_id, verdict(CONSISTENT|COMPLEMENT|CONFLICT|UNRESOLVED), note。
只核验需要跨文档比较的事实；不需要核验的标记为 SINGLE_DOC。
## 输出要求：JSON数组，禁止输出任何非JSON文本。"""

SINK_PROMPT_NEW = """你是一个资本市场事件调查助手。
## 节点任务类型：synthesis（最终事件分析）
## 完整事实集（来自merge节点，直接传入）：
{facts_json}

## 核验判定（来自verify节点，仅含判定结果）：
{verdicts_json}

## 任务要求：综合事实集与核验判定输出事件调查结论。
每个结论条目须引用具体的 fact_id 和 evidence_doc_id。
金额、日期等具体数值必须来自事实集原文，不得虚构。
未核验事实标注 UNVEROLVED。
## 输出要求：JSON数组，禁止输出任何非JSON文本。"""
