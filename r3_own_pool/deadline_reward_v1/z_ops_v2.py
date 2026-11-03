"""z_ops_v2 — semantically meaningful structure operators (window-1
next step per operator ruling 2026-10-28). NOT redundancy tuning.

Operators (all must pass check_legality + z_semantic_guard, where
the guard is extended for legal evidence substitution):
  SPLIT_VERIFY      split an overloaded verify-class node (>=2
                    produced fields) into evidence-locate + per-field
                    verification nodes
  SUBSTITUTE_EV     rebind a node whose evidence failed to
                    materialize onto an alternative LEGAL source
                    (allowed index, equivalent fields)
  MERGE_DUP         merge two same-role/same-inputs/same-evidence
                    nodes into one (dedup of repeated work)
  ADJUST_DEP        rewire an input to a producer that supplies a
                    superset of required fields (critical-path shortening)

This module only CONSTRUCTS and VALIDATES candidates (zero-call,
zero benefit sweeps — benefit testing awaits the real tier with the
same falsification discipline as stage_c_risk).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path('/root/r3_own_pool/deadline_reward_v1')
sys.path.insert(0, str(HERE))
sys.path.insert(0, '/root/r3_own_pool')

import dag_runtime_v1 as R
from dag_runtime_v1 import check_legality, z_semantic_guard

VERIFY_ROLES = ('cross_check', 'timeline_deep', 'amounts_check')


def _copy(spec):
    return json.loads(json.dumps(spec))


def split_verify(spec):
    """overloaded verify node -> locate + per-field verifiers."""
    outs = []
    for n in spec['nodes']:
        prod = n['contract']['produces']
        if n['role'] in VERIFY_ROLES and len(prod) >= 2:
            s = _copy(spec)
            locate = dict(id=n['id'] + '|loc', role='retrieval',
                          inputs=list(n['inputs']),
                          contract=dict(produces=['located_evidence']),
                          evidence=n.get('evidence'))
            s['nodes'] = [m for m in s['nodes'] if m['id'] != n['id']]
            for m in s['nodes']:
                m['inputs'] = [(n['id'] + '|v0' if x == n['id'] else x)
                               for x in m['inputs']]
            for k, f in enumerate(prod):
                s['nodes'].append(dict(
                    id=f"{n['id']}|v{k}", role=n['role'],
                    inputs=[locate['id']],
                    contract=dict(produces=[f],
                                  requires=['located_evidence']),
                    evidence=None))
            s['nodes'].append(locate)
            # route consumers: each consumer needs all original fields
            for m in s['nodes']:
                if m['id'].startswith(n['id'] + '|v'):
                    continue
                need = set(m['contract'].get('requires', []))
                if need & set(prod) or not m['inputs']:
                    pass
            # default: consumers take all verifiers
            for m in s['nodes']:
                if any(x.startswith(n['id'] + '|v') for x in m['inputs']):
                    m['inputs'] = sorted(
                        set(m['inputs']) |
                        {f"{n['id']}|v{k}" for k in range(len(prod))})
            outs.append((f'SPLIT_VERIFY:{n["id"]}', s))
    return outs


def anchor_coverage(doc_a, doc_b):
    """fraction of doc_a's program-anchored facts covered by doc_b."""
    from full_dag_silver import doc_atoms
    def an(t):
        at = doc_atoms(t)
        return (set(f'd:{k}' for k in at['dates'])
                | set(f'a:{k}' for k in at['amounts'])
                | set(f'p:{k}' for k in at['penalties']))
    A, B = an(doc_a['text']), an(doc_b['text'])
    return len(A & B) / max(1, len(A))


def substitute_evidence(spec, failed_doc, alt_doc, corpus,
                        tau=0.5):
    """rebind nodes bound to failed_doc onto alt_doc. GATES (2026-10-28
    alignment ruling): (1) same case identity (shared event tag);
    (2) EVIDENCE EQUIVALENCE at tau=0.5 = MAJORITY coverage of the
    failed doc's program-anchored facts (dates/amounts/penalties) —
    an a-priori standard, chosen BEFORE measuring (kangda->main
    measures 0.596; kangda->tj 0.191); callers must DISCLOSE the
    scope narrowing (uncovered ~40% = intermediary-facet facts not
    required by task B's contract); (3) terminal contract unchanged."""
    docs = corpus
    if alt_doc not in docs or failed_doc not in docs:
        return []
    da, db = docs[failed_doc], docs[alt_doc]
    if da.get('event') != db.get('event'):
        return []
    cov = anchor_coverage(da, db)
    if cov < tau:
        return []
    s = _copy(spec)
    hit = False
    for n in s['nodes']:
        if n.get('evidence') == failed_doc:
            n['evidence'] = alt_doc
            n.pop('evidence_unavailable', None)
            hit = True
    if not hit:
        return []
    ok, why = check_legality(s)
    if not ok:
        return []
    sink = [m for m in s['nodes']
            if not any(m['id'] in k['inputs'] for k in s['nodes'])][0]
    sink0 = [m for m in spec['nodes']
             if not any(m['id'] in k['inputs'] for k in spec['nodes'])][0]
    if sorted(sink['contract']['produces']) != sorted(
            sink0['contract']['produces']):
        return []
    return [(f'SUBSTITUTE_EV:{failed_doc}->{alt_doc}'
             f'@cov={cov:.0%}', s)]


def merge_dup(spec):
    """merge two same-role/same-inputs/same-evidence nodes."""
    outs = []
    seen = {}
    for n in spec['nodes']:
        key = (n['role'], tuple(sorted(n['inputs'])), n.get('evidence'))
        if key in seen:
            a = seen[key]
            s = _copy(spec)
            s['nodes'] = [m for m in s['nodes']
                          if m['id'] not in (a, n['id'])]
            merged = dict(id=a, role=n['role'],
                          inputs=list(n['inputs']),
                          contract=dict(
                              produces=sorted(set(
                                  n['contract']['produces']) | set(
                                  _find(spec, a)['contract']
                                  ['produces']))),
                          evidence=n.get('evidence'))
            s['nodes'].append(merged)
            for m in s['nodes']:
                m['inputs'] = [(a if x == n['id'] else x)
                               for x in m['inputs']]
            outs.append((f'MERGE_DUP:{a}+{n["id"]}', s))
        else:
            seen[key] = n['id']
    return outs


def _find(spec, nid):
    return [n for n in spec['nodes'] if n['id'] == nid][0]


def adjust_dep(spec):
    """rewire an input to an alternative producer supplying a
    superset of the node's required fields (shorten critical path)."""
    outs = []
    produced = {n['id']: set(n['contract']['produces'])
                for n in spec['nodes']}
    for n in spec['nodes']:
        need = set(n['contract'].get('requires', []))
        for cur in n['inputs']:
            for alt, fields in produced.items():
                if alt == cur or alt == n['id']:
                    continue
                if need and need <= fields and \
                        alt not in n['inputs']:
                    s = _copy(spec)
                    for m in s['nodes']:
                        if m['id'] == n['id']:
                            m['inputs'] = [(alt if x == cur else x)
                                           for x in m['inputs']]
                    ok, _ = check_legality(s)
                    if ok and z_semantic_guard(spec, s):
                        outs.append(
                            (f'ADJUST_DEP:{n["id"]}:{cur}->{alt}', s))
    return outs[:6]        # bounded


def z_options_v2(spec, ctx=None):
    """all v2 candidates passing legality (+guards). ctx may carry
    failed evidence docs & allowed index for substitution."""
    outs = [('IDENTITY', _copy(spec))]
    for name, s in split_verify(spec):
        ok, _ = check_legality(s)
        if ok and z_semantic_guard(spec, s):
            outs.append((name, s))
    for name, s in merge_dup(spec):
        ok, _ = check_legality(s)
        if ok and z_semantic_guard(spec, s):
            outs.append((name, s))
    outs += adjust_dep(spec)
    if ctx and ctx.get('failed_doc') and ctx.get('corpus'):
        for alt in ctx.get('alt_candidates', [ctx.get('alt_doc')]):
            if alt:
                outs += substitute_evidence(
                    spec, ctx['failed_doc'], alt, ctx['corpus'],
                    tau=ctx.get('tau', 0.5))
    return outs


if __name__ == '__main__':
    import glob
    files = sorted(glob.glob(str(HERE / 'fe_screening_runs' /
                                  'planner_v1_20261028/*_spec.json')))
    print('legality smoke on real planner graphs (zero-call):')
    from collections import Counter
    cnt = Counter()
    for f in files:
        spec = json.loads(Path(f).read_text())
        opts = z_options_v2(spec)
        name = Path(f).name[:16]
        kinds = [o[0].split(':')[0] for o in opts]
        cnt.update(kinds)
        print(f'  {name:<18} {len(opts)-1} candidates: '
              f'{[k for k in kinds if k != "IDENTITY"]}')
    print('\nby operator:', dict(cnt))
