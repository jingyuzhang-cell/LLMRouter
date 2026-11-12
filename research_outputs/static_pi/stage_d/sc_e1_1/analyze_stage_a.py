#!/usr/bin/env python3
"""Zero-call analysis of a finished SC-E1.1 canary directory: reads the ledger and results, no network."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import sc_e1_runner as OLD  # noqa: E402
import sc_e1_scorer as SC  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402


def call_rows(done):
    rows = []
    for r in done:
        raw = r.get('raw_response') or {}
        blocks = raw.get('content') if isinstance(raw.get('content'), list) else []
        thinking = sum(len(b.get('thinking') or '') for b in blocks if isinstance(b, dict))
        rows.append(dict(arm=r['arm'], node=r['node'], backend=r['backend'], model=r.get('response_model'),
                         stop=r.get('stop'), tokens_in=r.get('in'), tokens_out=r.get('out'), lat_s=r.get('lat'),
                         yuan_accounting=r.get('yuan_accounting'), text_chars=len(r.get('text') or ''),
                         thinking_chars=thinking, fault=r.get('fault'), error=r.get('error')))
    return rows


def j2_values(j2_text):
    obj = OLD.extract_json(j2_text) or {}
    out = {}
    for item in (obj.get('verified') or []):
        if isinstance(item, dict) and item.get('fact_id'):
            out[item['fact_id']] = item.get('final_value')
    for item in (obj.get('derived') or []):
        if isinstance(item, dict) and item.get('fact_id'):
            out[item['fact_id']] = item.get('value')
    return out


def j1_stats(j1_text):
    obj = OLD.extract_json(j1_text) or {}
    rows = [r for r in (obj.get('party_matrix') or []) if isinstance(r, dict)]
    return dict(parties=len(rows), final_amounts=sum(bool(str(r.get('final_penalty') or '').strip()) for r in rows),
                backed_by_d2=sum(R._backed_by_d2(r) for r in rows))


def value_state(fact, value):
    if value is None or SC.is_abstention(value):
        return 'absent'
    return 'correct' if SC.value_correct(fact, value) else 'wrong'


def attribute(status, in_table, j2_state):
    if status == 'TP':
        return 'TP'
    if status == 'ABSENT':
        return 'SINK_ABSTAINED_WITH_EVIDENCE' if in_table else 'NO_EVIDENCE_ROW'
    if status in ('VALUE_WRONG', 'CONFLICT'):
        return 'WRONG_VALUE_FROM_J2' if j2_state == 'wrong' else 'WRONG_VALUE_AT_SINK'
    return 'VALUE_RIGHT_BAD_CITATION'


def analyze(out_dir):
    out_dir = Path(out_dir)
    contract = SC.load_contract()
    facts = contract['required_facts']
    results = json.loads((out_dir / 'RESULTS.json').read_text('utf-8'))
    done = [r for r in R.read_ledger(out_dir / 'LEDGER.jsonl') if r['phase'] == 'done']
    calls = call_rows(done)
    node_text = {(r['arm'], r['node']): r.get('text') or '' for r in done}

    e_texts = {n: node_text.get(('shared', n)) for n in ('E_D1', 'E_D2')}
    table, rejected = ([], 0)
    if all(e_texts.values()):
        table, rejected = R.evidence_rows(e_texts, SC.doc_index(contract))
    grounding = {f['fact_id']: sorted({r['row'] for r in table if r['doc'] in f['allowed_citation_docs']
                                       and SC.quote_grounds(f, r['quote'])}, key=lambda x: int(x[1:])) for f in facts}

    arms = [r['arm'] for r in results['records']]
    slots, per_arm = [], {}
    for rec in results['records']:
        arm = rec['arm']
        j2 = j2_values(node_text.get((arm, 'J2'), ''))
        rows = {x['fact_id']: x for x in rec['metrics']['rows']}
        labels = Counter()
        states = {}
        for f in facts:
            fid = f['fact_id']
            state = value_state(f, j2.get(fid))
            label = attribute(rows[fid]['status'], bool(grounding[fid]), state)
            labels[label] += 1
            states[fid] = dict(status=rows[fid]['status'], j2=state, attribution=label, value=rows[fid].get('value'),
                               doc=rows[fid].get('doc'), quote=rows[fid].get('quote'))
        m = rec['metrics']
        per_arm[arm] = dict(states=states, attribution=dict(labels), j1=j1_stats(node_text.get((arm, 'J1'), '')),
                            action=rec['trace'][0]['action'], obs=rec['trace'][0]['obs'],
                            **{k: m[k] for k in ('Q_all', 'Q_terminal', 'E_literal', 'F', 'E', 'C', 'error_rate', 'asserted',
                                                 'correct', 'tp', 'wrong', 'critical_tp', 'critical_total', 'critical_gate',
                                                 'out_of_contract', 'malformed_answers')})
    for f in facts:
        fid = f['fact_id']
        slots.append(dict(fact_id=fid, critical=bool(f.get('critical')), gold=f['value'], evidence_rows=grounding[fid],
                          by_arm={a: per_arm[a]['states'][fid]['status'] for a in arms},
                          j2_by_arm={a: per_arm[a]['states'][fid]['j2'] for a in arms}))
    tps = {a: {s['fact_id'] for s in slots if s['by_arm'][a] == 'TP'} for a in arms}
    noise = dict(q_all=[per_arm[a]['Q_all'] for a in arms],
                 q_all_range=round(max(per_arm[a]['Q_all'] for a in arms) - min(per_arm[a]['Q_all'] for a in arms), 6) if arms else None,
                 slots_differing=sorted({s['fact_id'] for s in slots if len(set(s['by_arm'].values())) > 1}, key=lambda x: int(x[1:])),
                 tp_all_arms=sorted(set.intersection(*tps.values()), key=lambda x: int(x[1:])) if tps else [])
    return dict(stopped=results['stopped'], used=results['used'], caps=results['caps'], models_reported=results['models_reported'],
                acceptance=results['acceptance'], rescore=json.loads((out_dir / 'RESCORE.json').read_text('utf-8'))['matches_online']
                if (out_dir / 'RESCORE.json').exists() else None,
                evidence_table=dict(rows=len(table), rejected=rejected, by_doc=dict(Counter(r['doc'] for r in table)),
                                    chars=len(R.evidence_block(table))),
                slots_with_evidence=sum(bool(v) for v in grounding.values()), calls=calls, arms=per_arm, slots=slots, noise=noise)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out_dir')
    args = ap.parse_args()
    a = analyze(args.out_dir)
    (Path(args.out_dir) / 'ANALYSIS.json').write_text(json.dumps(a, ensure_ascii=False, indent=1, default=str), 'utf-8')
    print('stopped:', a['stopped'])
    print('used:', a['used'], '| models:', a['models_reported'], '| ledger rescore matches:', a['rescore'])
    print('acceptance:', a['acceptance']['verdict'], {k: v for k, v in a['acceptance']['checks'].items() if not v} or 'all checks true')
    print('evidence table:', a['evidence_table'], '| slots with a groundable row:', a['slots_with_evidence'], '/ 20')
    print('\ncalls:')
    for c in a['calls']:
        print(f"  {c['arm']:<15}{c['node']:<7}{c['backend']:<4}{str(c['model']):<20}{str(c['stop']):<12}in={c['tokens_in']} out={c['tokens_out']} "
              f"lat={c['lat_s']} ¥={c['yuan_accounting']} text={c['text_chars']} thinking={c['thinking_chars']} {c['fault'] or ''}{c['error'] or ''}")
    print('\narms:')
    for arm, m in a['arms'].items():
        print(f"  {arm:<15}Q_all={m['Q_all']} Q_terminal={m['Q_terminal']} E_literal={m['E_literal']} asserted={m['asserted']} tp={m['tp']} "
              f"wrong={m['wrong']} critical={m['critical_tp']}/{m['critical_total']} action={m['action']} j1={m['j1']} cov={m['obs']['final_coverage']}")
        print(f"  {'':<15}{m['attribution']}")
    print('\nslots:')
    for s in a['slots']:
        print(f"  {s['fact_id']:<4}{'*' if s['critical'] else ' '} gold={str(s['gold']):<18} rows={len(s['evidence_rows']):<3}"
              f" {' '.join(f'{v:<12}' for v in s['by_arm'].values())} j2={list(s['j2_by_arm'].values())}")
    print('\nbetween-arm noise under identical configuration:', a['noise'])


if __name__ == '__main__':
    main()
