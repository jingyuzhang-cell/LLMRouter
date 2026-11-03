"""QP6 Study 1: taxonomy of the 100 both-wrong (F1 x F2 both non-TP) facts.

Per (task, rep, fact): classify the PRIMARY failure mechanism A-H using
gold structure (composite/derived flags, multi-evidence), upstream E-layer
evidence availability, and cross-document indicators. Multi-label allowed but
one primary cause assigned.

A SINGLE_EVIDENCE   single evidence could support; model failed to use it
B MULTI_EVIDENCE    >=2 evidence pieces jointly required
C DERIVED_FACT      computation/ratio/difference required
D CROSS_DOCUMENT    cross-document linkage required
E CONFLICTING       genuine evidence conflict
F TEMPORAL          time/state distinction required
G ENTITY_LINKAGE    subject linkage required
H INSUFFICIENT      documents genuinely cannot support the conclusion
"""
import json, sys, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp4_factorial as F
import qp3_primitives as P3
import qp2_chain as CH
import qp5a_pure_prep as PP
import scorer_qp1 as Q1
from qp4b_attribution import is_composite
from qp5d_attribution import merged_e_texts, load_ledger
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def n_evidence(f):
    return len(f.get('source_evidence') or [])


def is_derived(f):
    v = str(f.get('value', ''))
    b = str(f.get('bucket', '')) + str(f.get('predicate', ''))
    d = any(k in b for k in ('倍数', '比例', '变化率', '差', '合计', '倍', '率', '增长'))
    return d or f['fact_id'].startswith('DV')


def cross_doc(f):
    docs = {e.get('doc_id') for e in f.get('source_evidence') or []}
    return len(docs) > 1


def temporal(f):
    b = str(f.get('bucket', '')) + str(f.get('predicate', ''))
    return any(k in b for k in ('日期', '时点', '时间', '披露日', '收到日', '落款'))


def entity_link(f):
    b = str(f.get('bucket', '')) + str(f.get('predicate', ''))
    return any(k in b for k in ('关系', '同一', '对应', '是否', '主体', '对象', '职务'))


def e_has_evidence(f, ver_entries, contract):
    """Does the E-layer verified table carry an entry for this fact?"""
    for e in ver_entries:
        if P3.name_matches(e, f) or Q1.value_in_quote(f.get('value'), e.get('quote', '')):
            return True
    return False


def doc_supports(f, contract):
    """Does any document page literally ground the gold value?"""
    v = f.get('value')
    if not v:
        return False
    for e in f.get('source_evidence') or []:
        if Q1.value_in_quote(v, e.get('quote', '')):
            return True
    for d in contract['source_pages'].values():
        for pg in d.get('pages', {}).values():
            if Q1.value_in_quote(v, pg.get('text', '')):
                return True
    return False


def classify(f, ver_entries, contract, has_e_evidence):
    labels = []
    if is_derived(f):
        labels.append('C_DERIVED')
    if is_composite(f):
        labels.append('B_MULTI')
    if cross_doc(f):
        labels.append('D_CROSS_DOC')
    if temporal(f):
        labels.append('F_TEMPORAL')
    if entity_link(f):
        labels.append('G_ENTITY')
    if not doc_supports(f, contract):
        if is_derived(f):
            primary = 'C_DERIVED'
        elif is_composite(f):
            primary = 'B_MULTI'
        else:
            primary = 'H_INSUFFICIENT'
    elif n_evidence(f) >= 2 or is_composite(f):
        primary = 'B_MULTI'
    elif is_derived(f):
        primary = 'C_DERIVED'
    elif cross_doc(f):
        primary = 'D_CROSS_DOC'
    elif has_e_evidence:
        primary = 'A_SINGLE'          # evidence existed but model failed
    else:
        primary = 'A_SINGLE_NO_EV'    # single evidence in doc but E layer missed it
    return primary, labels


def main():
    led = load_ledger()
    res = json.load(open(f'{QP}/QP5D_RESULTS.json'))
    by = {}
    for r in res['results']:
        if not r.get('error'):
            by[(r['task'], r['rep'], r['arm'])] = r

    rows = []
    prim_count = collections.Counter()
    per_task = collections.defaultdict(collections.Counter)
    for t in F.TASKS:
        for rep in (1, 2):
            f1, f2 = by.get((t, rep, 'F1')), by.get((t, rep, 'F2'))
            if not f1 or not f2:
                continue
            contract = F.load_contract(t)
            texts = merged_e_texts(led, t, rep)
            entries = []
            for tx in texts:
                entries += P3.normalize_stage(extract_any(tx))
            ver, _ = CH.verify_evidence(entries, contract)
            s1 = {x['fact_id']: x['status'] for x in f1['rows']}
            s2 = {x['fact_id']: x['status'] for x in f2['rows']}
            for f in contract['required_facts']:
                fid = f['fact_id']
                if s1.get(fid) == 'TP' or s2.get(fid) == 'TP':
                    continue
                has_ev = e_has_evidence(f, ver, contract)
                primary, labels = classify(f, ver, contract, has_ev)
                rows.append(dict(task=t, rep=rep, fact_id=fid, kind=f.get('value_kind'),
                                 bucket=f.get('bucket'), primary=primary, labels=labels,
                                 has_e_evidence=has_ev, n_evidence=n_evidence(f),
                                 gold=str(f.get('value'))[:60]))
                prim_count[primary] += 1
                per_task[t][primary] += 1
    json.dump(dict(batch='QP6_FAILURE_TAXONOMY', model_calls=0, rows=rows,
                   primary_counts=dict(prim_count),
                   per_task={k: dict(v) for k, v in per_task.items()}),
              open(f'{QP}/QP6_FAILURE_TAXONOMY.json', 'w'), ensure_ascii=False, indent=1)
    total = len(rows)
    print(f'both-wrong facts: {total}')
    for k, v in prim_count.most_common():
        print(f'  {k:18s} {v:4d} ({v/total*100:.1f}%)')
    print('\nper task:')
    for t in F.TASKS:
        print(f'  {t:9s}', dict(per_task[t]))


if __name__ == '__main__':
    main()
