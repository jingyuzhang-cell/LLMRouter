"""QP5-D Study 1: item-by-item error attribution for C2 evidence entries.

Executed merge semantics (original + retry facts). Universe = verified entries
(the supply table). For every entry: bind to gold fact, A-J taxonomy with
primary/secondary causes, and the full chain entry -> m-fact -> SINK answer ->
terminal verdict. Also builds the empirical transfer table used (clearly
labeled as projection) by Study 2.
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
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def load_ledger():
    led = {}
    for path in (f'{QP}/QP5C_LEDGER.jsonl', f'{QP}/QP4_LEDGER.jsonl'):
        for line in open(path):
            x = json.loads(line)
            led.setdefault(x['purpose'], x)
    return led


def merged_e_texts(led, t, rep):
    """Executed semantics: flat originals merged with retry facts."""
    out = []
    for node in ('e0', 'e1'):
        orig = led.get(f'qp5c|{t}|C2|r{rep}|{node}')
        rty = led.get(f'qp5c|{t}|C2|R|r{rep}|{node}')
        if not orig:
            return None
        if not rty:
            out.append(orig['text'])
            continue
        o = extract_any(orig['text'])
        r = extract_any(rty['text'])
        of = o.get('facts') if isinstance(o, dict) else None
        rf = r.get('facts') if isinstance(r, dict) else None
        if of is None and rf is None:
            out.append(orig['text'])
        else:
            out.append(json.dumps({'facts': (of or []) + (rf or [])}, ensure_ascii=False))
    return out


def value_correct_anyway(v, f):
    return bool(v not in (None, '')) and P3.value_equal_anyway(v, f)[0]


def diagnose(entry, f, contract, seen_values):
    """A-J tags for one bound entry. Returns (primary, secondary[], correct)."""
    v = entry.get('raw') or entry.get('value')
    q = entry.get('quote', '') or ''
    tags = []
    correct = value_correct_anyway(v, f)
    gold_ev = (f.get('source_evidence') or [{}])[0]
    # entity/mis-bind: quote grounds another gold fact's value but not this one
    other_grounds = any(
        Q1.value_in_quote(g.get('value'), q) for g in contract['required_facts']
        if g['fact_id'] != f['fact_id'])
    self_grounds = Q1.value_in_quote(f.get('value'), q)
    doc_ok = str(entry.get('doc')) == str(gold_ev.get('doc_id'))
    page_ok = str(entry.get('page')) == str(gold_ev.get('page'))
    verbatim = True  # verified entries passed verbatim by construction
    if not correct:
        primary = 'VALUE_ERROR'
        if other_grounds and not self_grounds:
            tags.append('ENTITY_ERROR')
        if not doc_ok:
            tags.append('DOCUMENT_ERROR')
        elif not page_ok:
            tags.append('PAGE_ERROR')
    else:
        primary = 'CORRECT'
        if not doc_ok:
            tags.append('DOCUMENT_ERROR_MILD')
        if not self_grounds:
            primary = 'QUOTE_ERROR'   # value right but quote does not ground it
    nv = P3._norm(v)
    if nv in seen_values:
        tags.append('DUPLICATE_ERROR')
    return primary, tags, correct


def main():
    led = load_ledger()
    # terminal statuses recomputed deterministically from the ledger (frozen scorer)
    sink_status = {}
    for t in F.TASKS:
        for rep in (1, 2):
            rec = led.get(f'qp5c|{t}|C2|r{rep}|p')
            if not rec:
                continue
            contract_ = F.load_contract(t)
            sink_ = extract_any(rec['text'])
            res_ = Q1.score_task(contract_, sink_)
            sink_status[(t, rep)] = {r['fact_id']: r['status'] for r in res_['rows']}

    entries_out = []
    transfer = collections.Counter()
    conflict_facts = 0
    covered_facts = 0
    per_task = collections.defaultdict(lambda: collections.Counter())
    for t in F.TASKS:
        for rep in (1, 2):
            texts = merged_e_texts(led, t, rep)
            if not texts:
                continue
            contract = F.load_contract(t)
            entries = []
            for tx in texts:
                entries += P3.normalize_stage(extract_any(tx))
            ver_all, _ = CH.verify_evidence(entries, contract)
            m = extract_any(led[f'qp5c|{t}|C2|r{rep}|m']['text'])
            m_facts = {}
            for e in P3.normalize_stage(m):
                k = PP.fact_key(e)
                if k and e.get('value') not in (None, ''):
                    m_facts.setdefault(k, e.get('value'))
            ev_map = PP.match_evidence(m_facts, ver_all, contract)
            supplied = set(ev_map.keys())

            for f in contract['required_facts']:
                fid = f['fact_id']
                key = f.get('bucket') or fid
                bound = [e for e in ver_all if P3.name_matches(e, f) or
                         Q1.value_in_quote(f.get('value'), e.get('quote', ''))]
                has_any_correct = any(value_correct_anyway(e.get('raw') or e.get('value'), f) for e in bound)
                vals = [P3._norm(e.get('raw') or e.get('value')) for e in bound]
                # equivalence classes via pairwise value_equal_anyway
                classes = []
                for vv in vals:
                    placed = False
                    for cls in classes:
                        if P3.value_equal_anyway(vv, f)[0] and cls == vv:
                            placed = True
                            break
                    if not placed and vv not in classes:
                        classes.append(vv)
                conflict = len(set(vals)) > 1
                if bound:
                    covered_facts += 1
                if conflict:
                    conflict_facts += 1

                seen = set()
                first_idx = {}
                for i, e in enumerate(bound):
                    primary, tags, correct = diagnose(e, f, contract, seen)
                    nv = P3._norm(e.get('raw') or e.get('value'))
                    seen.add(nv)
                    row = dict(task=t, rep=rep, fact_id=fid, idx=i, primary=primary,
                               secondary=tags, correct=correct,
                               value=str(e.get('raw') or e.get('value'))[:60],
                               supplied=key in supplied, composite=is_composite(f))
                    entries_out.append(row)
                    per_task[t][primary] += 1
                    per_task[t]['SUPPLIED_WRONG' if (row['supplied'] and not correct and not has_any_correct) else 'SUPPLIED_OK'] += 0

                # terminal outcome + supply category
                status = sink_status.get((t, rep), {}).get(fid)
                cat = ('correct_avail' if has_any_correct else
                       'wrong_only' if bound else 'none')
                outc = ('TP' if status == 'TP' else
                        'WRONG' if status and status != 'ABSENT' else
                        'ABSENT' if status == 'ABSENT' else 'NA')
                transfer[(cat, outc)] += 1
                per_task[t][f'chain:{cat}->{outc}'] += 1

    json.dump(dict(batch='QP5D_ERROR_ATTRIBUTION', model_calls=0, entries=entries_out,
                   transfer={f'{k[0]}|{k[1]}': v for k, v in transfer.items()},
                   summary=dict(covered_facts=covered_facts, conflict_facts=conflict_facts,
                                per_task={k: dict(v) for k, v in per_task.items()})),
              open(f'{QP}/QP5D_ENTRIES.json', 'w'), ensure_ascii=False, indent=1)

    prim = collections.Counter(e['primary'] for e in entries_out)
    print('entries diagnosed:', len(entries_out))
    for k, v in prim.most_common():
        print(f'  {k:14s} {v:4d} ({v/len(entries_out)*100:.1f}%)')
    sec = collections.Counter(s for e in entries_out for s in e['secondary'])
    print('secondary:', dict(sec))
    print(f'\ncovered facts={covered_facts}, conflict facts={conflict_facts}')
    print('\ntransfer (supply category -> terminal outcome), C2 cells:')
    for (cat, outc), n in sorted(transfer.items()):
        print(f'  {cat:13s} -> {outc:7s} {n}')


if __name__ == '__main__':
    main()
