"""Upstream evidence-production diagnosis (zero calls).

For every gold fact x (task, rep from QP4 D-cell cached E outputs):
  DOC_LACKS        gold value not literally present in any doc page (derived)
  NEEDS_MULTI      composite value; single-quote grounding structurally impossible
  E_INCOMPLETE     a name/evidence-matched E entry exists but lacks doc/page/quote
                   or its quote fails verbatim/grounding
  DOC_HAS_E_MISSED doc literally carries the value (in gold span) but E produced
                   no usable entry for the fact
  PRODUCED         E produced a verbatim, grounded entry (evidence available)
Mechanism-addressable share = E_INCOMPLETE + DOC_HAS_E_MISSED.
"""
import json, sys, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
import qp4_factorial as F
import qp3_primitives as P3
import qp2_chain as CH
import scorer_qp1 as Q1
from qp4b_attribution import is_composite
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def doc_carries(contract, f):
    """Gold value literally grounded somewhere in the docs (own span first)."""
    for e in f.get('source_evidence') or []:
        if Q1.value_in_quote(f.get('value'), e.get('quote', '')):
            return True
    v = str(f.get('value', ''))
    if not v:
        return False
    for d in contract['source_pages'].values():
        for pg in d.get('pages', {}).values():
            if Q1.value_in_quote(v, pg.get('text', '')):
                return True
    return False


def e_entry_for(f, e_objs, contract):
    """Best E entry for the fact (name match or value-grounding)."""
    cands = []
    for obj in e_objs:
        for e in P3.normalize_stage(obj):
            q = e.get('quote', '') or ''
            pg = (contract['source_pages'].get(str(e.get('doc'))) or {}).get('pages', {}).get(str(e.get('page')))
            verbatim = bool(pg and q and Q1._norm(q) in Q1._norm(pg.get('text', '')))
            grounded = bool(q and Q1.value_in_quote(f.get('value'), q))
            named = P3.name_matches(e, f)
            if named or grounded:
                cands.append(dict(e=e, named=named, verbatim=verbatim, grounded=grounded,
                                  has_fields=bool(e.get('doc') is not None and e.get('page') is not None and q)))
    return cands


def classify_fact(contract, f, e_objs):
    if is_composite(f):
        return 'NEEDS_MULTI'
    if not doc_carries(contract, f):
        return 'DOC_LACKS'
    cands = e_entry_for(f, e_objs, contract)
    for c in cands:
        if c['verbatim'] and c['grounded']:
            return 'PRODUCED'
    if cands:
        return 'E_INCOMPLETE'
    return 'DOC_HAS_E_MISSED'


def main():
    led = {}
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        led[(p[1], p[2], p[3], p[4])] = x
    rows = []
    for t in F.TASKS:
        for rep in (1, 2):
            contract = F.load_contract(t)
            e0 = extract_any(led[(t, 'D', f'r{rep}', 'e0')]['text'])
            e1 = extract_any(led[(t, 'D', f'r{rep}', 'e1')]['text'])
            for f in contract['required_facts']:
                rows.append(dict(task=t, rep=rep, fact_id=f['fact_id'],
                                 cls=classify_fact(contract, f, (e0, e1))))
    json.dump(rows, open(f'{QP}/QP5C_EVIDENCE_DIAGNOSIS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"{'task':9s} " + ''.join(k[:12].rjust(14) for k in
          ('PRODUCED', 'E_INCOMPLETE', 'DOC_HAS_E_MISSED', 'NEEDS_MULTI', 'DOC_LACKS')) + '   addressable')
    agg = {}
    for t in F.TASKS:
        g = [r for r in rows if r['task'] == t]
        n = len(g)
        c = collections.Counter(r['cls'] for r in g)
        addr = (c['E_INCOMPLETE'] + c['DOC_HAS_E_MISSED']) / n
        agg[t] = dict(n=n, **{k: round(c[k] / n, 3) for k in
                              ('PRODUCED', 'E_INCOMPLETE', 'DOC_HAS_E_MISSED', 'NEEDS_MULTI', 'DOC_LACKS')},
                      addressable=round(addr, 3))
        print(f"{t:9s} " + ''.join(f"{c[k]/n:14.3f}" for k in
              ('PRODUCED', 'E_INCOMPLETE', 'DOC_HAS_E_MISSED', 'NEEDS_MULTI', 'DOC_LACKS')) + f"   {addr:.3f}")
    macro_addr = st.mean(v['addressable'] for v in agg.values())
    macro_prod = st.mean(v['PRODUCED'] for v in agg.values())
    print(f"\nmacro: produced={macro_prod:.3f} addressable={macro_addr:.3f} "
          f"structural={1-macro_prod-macro_addr:.3f}")
    m, z = agg['MVR1'], agg['ZEDA']
    print(f"MVR1 vs ZEDA: produced {m['PRODUCED']} vs {z['PRODUCED']}; "
          f"addressable {m['addressable']} vs {z['addressable']}")


if __name__ == '__main__':
    main()
