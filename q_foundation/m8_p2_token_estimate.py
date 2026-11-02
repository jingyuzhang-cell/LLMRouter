"""M8-P2 token budget arithmetic (ZERO model calls) — frozen artifact.

Recomputes the offline token estimate in M8_P2_PROTOCOL.md §五 from the
real E04 document character counts and the V1.1 node execution contract
(template 500 chars/node, parent-output truncation 1500 chars/parent,
per-kind output token caps). Run: python3 m8_p2_token_estimate.py
"""
import json
import re
import subprocess

DOCS = {
    'doc1': 'E04-zhuoran_20260910.txt',
    'doc2': 'E04-zhuoran_20261009.txt',
    'doc3': 'E04-zhuoran_20261013.txt',
}
DOCS_DIR = '/root/cap_eval_bench_v1/evidence/texts'

TPL = 500        # kind template chars per node
TRUNC = 1500     # parent-output truncation chars per parent
OUT = {'extracts': 900, 'timeline': 800, 'reasoning': 600,
       'verification': 500, 'report': 1200}

# C-group reference DAG (E04_reference_dag.json): (kind, doc_refs, n_parents)
C_NODES = [('extracts', ['doc2'], 0), ('timeline', ['doc1', 'doc2'], 0),
           ('extracts', ['doc3'], 0), ('reasoning', [], 1),
           ('verification', [], 3), ('report', [], 2)]
# Worst-case raw DAG hypothesis: 8 nodes
RAW_NODES = ([('extracts', ['doc2'], 0)] * 4 + [('timeline', ['doc1', 'doc2'], 0),
             ('reasoning', [], 2), ('verification', [], 3), ('report', [], 2)])
GEN = 3 * 1500


def doc_chars():
    out = {}
    for k, f in DOCS.items():
        t = open(f'{DOCS_DIR}/{f}', encoding='utf-8').read()
        out[k] = len(re.sub(r'\s+', '', t))
    return out


def node_tokens(kind, doc_refs, n_parents, tok_per_char, doc):
    inch = TPL + sum(doc[d] for d in doc_refs) + n_parents * TRUNC
    return int(inch * tok_per_char) + OUT[kind]


def main():
    doc = doc_chars()
    result = {'doc_stripped_chars': doc, 'tpl': TPL, 'trunc': TRUNC,
              'out_caps': OUT, 'scenarios': {}}
    for label, tpc in (('expected_0.65', 0.65), ('worst_1.0', 1.0)):
        c_run = sum(node_tokens(k, d, p, tpc, doc) for k, d, p in C_NODES)
        raw_run = sum(node_tokens(k, d, p, tpc, doc) for k, d, p in RAW_NODES)
        total = 3 * raw_run * 2 + 3 * c_run + GEN
        result['scenarios'][label] = {
            'C_run': c_run, 'worst_raw_run': raw_run,
            '3C': 3 * c_run, '3A': 3 * raw_run, '3B_le': 3 * raw_run,
            'generation': GEN, 'total_ceiling': total}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    exp = result['scenarios']['expected_0.65']['total_ceiling']
    worst = result['scenarios']['worst_1.0']['total_ceiling']
    assert exp == 206274 and worst == 285396, 'drift vs protocol §五'
    print(f"\nprotocol check OK: expected-ceiling {exp}, worst {worst}; "
          f"request = 70 calls / 220K tokens (covers expected ceiling)")


if __name__ == '__main__':
    main()
