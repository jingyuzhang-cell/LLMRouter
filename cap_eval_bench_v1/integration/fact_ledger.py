"""Stage-C-R4 fact ledger: structured, provenance-carrying information
transfer for the DAG execution chain (operator ruling 2026-10-30, item III).

Repairs the terminal information bottleneck WITHOUT touching the frozen
scheduling decisions (R / pi / Z rules unchanged in six_arm_scheduler.py):

  * every fact is a structured record: content, source doc_id, text span
    offset, parent node + version, and an explicit four-state status
    (confirmed / unconfirmed / insufficient_evidence / upstream_missing);
  * truncation is ACCOUNTED, never silent: input assembly over the cap
    records exactly which facts were dropped and why;
  * 'not mentioned' is never conflated with UNKNOWN: facts lost in transit
    surface as upstream_missing at the terminal, and un-verifiable facts
    keep status unconfirmed rather than disappearing.
"""
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

# evidence texts are newline-fragmented (e.g. "2020\n年\n6\n月"): the
# patterns tolerate inter-token whitespace; stored content is whitespace-
# stripped so downstream matching (norm-based) stays exact
DATE = re.compile(r'\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?')
AMT = re.compile(r'[\d,]{2,}(?:\.\d+)?\s*(?:万元|亿元|元)')
DOCID = re.compile(r'[a-z]{2,5}_[a-z_]+_\d{4}')

STATUSES = ('confirmed', 'unconfirmed', 'insufficient_evidence',
            'upstream_missing')


@dataclass
class Fact:
    fid: str                      # stable id: f{seq}
    content: str                  # the fact text (date/amount/entity/statement)
    kind: str                     # date | amount | entity | statement
    source_doc: Optional[str]     # doc_id the fact was extracted from
    span: Optional[List[int]]     # [start, end) in the source doc text
    parent_node: Optional[str]    # producing node id
    parent_version: Optional[int]
    status: str = 'unconfirmed'

    def compact(self):
        return (f"{self.fid}|{self.kind}|{self.content}|src={self.source_doc}"
                f"|{self.status}")


class FactLedger:
    """Per-node structured fact set + non-silent truncation accounting."""

    def __init__(self):
        self.facts: Dict[str, Fact] = {}
        self._seq = 0
        self.truncation_log: List[dict] = []   # every dropped fact, recorded

    def _next_fid(self) -> str:
        # collision-safe allocation: directly-inherited facts keep their
        # original fids (inserted into self.facts without add()), so the
        # sequence must skip every occupied id — otherwise a new fact can
        # SILENTLY OVERWRITE an inherited one (exact information-loss bug
        # class this ledger exists to prevent)
        while True:
            self._seq += 1
            fid = f'f{self._seq}'
            if fid not in self.facts:
                return fid

    def add(self, content, kind, source_doc=None, span=None, parent_node=None,
            parent_version=None, status='unconfirmed') -> Fact:
        f = Fact(self._next_fid(), content, kind, source_doc,
                 list(span) if span else None, parent_node, parent_version,
                 status)
        self.facts[f.fid] = f
        return f

    def merge(self, other: 'FactLedger', via_node, via_version):
        """Inherit a parent's facts with lineage updated; never drops."""
        for f in other.facts.values():
            if f.fid not in self.facts:
                self.facts[f.fid] = Fact(
                    f.fid, f.content, f.kind, f.source_doc, f.span,
                    via_node, via_version, f.status)

    def merge_fact(self, f: Fact, via_node):
        if f.fid not in self.facts:
            self.facts[f.fid] = Fact(f.fid, f.content, f.kind, f.source_doc,
                                     f.span, via_node, 1, f.status)

    def verify_against(self, evidence_text, norm):
        """Promote facts whose content is grounded in the evidence."""
        ev = norm(evidence_text)
        for f in self.facts.values():
            if f.status == 'upstream_missing':
                continue
            if norm(f.content) in ev:
                f.status = 'confirmed'
            elif f.status == 'unconfirmed':
                f.status = 'insufficient_evidence'
        return self

    def serialize(self, cap_chars=None):
        txt, n, _ = self.serialize3(cap_chars)
        return txt, n

    def serialize3(self, cap_chars=None):
        """Compact one-line-per-fact serialization -> (text, n_dropped,
        kept_fids). Overflow facts are recorded in truncation_log and their
        ids returned as NOT visible; downstream they become
        upstream_missing placeholders (loss is itself propagated)."""
        lines = [f.compact() for f in self.facts.values()]
        if cap_chars is None or sum(len(l) + 1 for l in lines) <= cap_chars:
            return '\n'.join(lines), 0, set(self.facts.keys())
        kept, kept_fids, used, dropped = [], [], 0, []
        for f, l in zip(self.facts.values(), lines):
            if used + len(l) + 1 <= cap_chars:
                kept.append(l)
                kept_fids.append(f.fid)
                used += len(l) + 1
            else:
                dropped.append(f)
        for f in dropped:
            self.truncation_log.append(dict(fid=f.fid, content=f.content,
                                            source_doc=f.source_doc,
                                            reason='input_cap'))
        kept.append(f'[TRUNCATED {len(dropped)} facts — recorded, '
                    f'not silently dropped]')
        return '\n'.join(kept), len(dropped), set(kept_fids)

    def stats(self):
        from collections import Counter
        c = Counter(f.status for f in self.facts.values())
        return dict(n=len(self.facts), **{s: c.get(s, 0) for s in STATUSES})


def extract_facts_from_text(text, source_doc, ledger: FactLedger,
                            parent_node=None, parent_version=None,
                            kinds=('date', 'amount')):
    """Deterministic fact extraction from an evidence text (used by the
    zero-call faithful adapter and available to real parsing alike)."""
    spans = []
    if 'date' in kinds:
        spans += [(m.start(), m.end(), m.group(0), 'date')
                  for m in DATE.finditer(text)]
    if 'amount' in kinds:
        spans += [(m.start(), m.end(), m.group(0), 'amount')
                  for m in AMT.finditer(text)]
    for s, e, val, kind in spans:
        content = re.sub(r'\s+', '', val)
        ledger.add(content, kind, source_doc=source_doc, span=[s, e],
                   parent_node=parent_node, parent_version=parent_version)
    return ledger
