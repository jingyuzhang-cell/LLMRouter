#!/usr/bin/env python3
"""P2-B offline re-scoring under the corrected (g11) scoring rules -- SENSITIVITY ANALYSIS ONLY, zero model calls.

1. Pilot contracts (ZQ/CY/SL v1, frozen) get g11 specs + span repairs with the same builder functions as P2-C;
   written to p2b_rescore/ (not into the Gold space, not a Gold revision).
2. Each arm's terminal output is reconstructed deterministically from p2_runs/LEDGER.jsonl: G1 = G1 node,
   G2 = its SINK, G3-G6 = the arm's own successful SINK if any, else the G2 terminal (the runner's fallback on
   fault / no target); then the runner's M3 post-processing is re-applied with the shared-checkpoint evidence.
3. Validation: the ORIGINAL scorer on the reconstruction must reproduce PILOT_RESULTS.json exactly.
4. Re-score with p2c_scorer; report both. Original scores are left untouched.
"""
import json, sys
from pathlib import Path

HERE = Path('/root/research_outputs/static_pi/p2_confirm')
sys.path[:0] = [str(HERE), '/root/research_outputs/static_pi/stage_d/qs_confirm',
                '/root/research_outputs/static_pi/stage_d/sc_e1_1', '/root/research_outputs/static_pi/stage_d']
import p2_runner as P   # frozen P2-B runner (for TaskScorer, helpers, module aliases)
import p2c_scorer as S
import p2c_g11_build as B

OUT = HERE / 'p2b_rescore'
OUT.mkdir(exist_ok=True)

# ---- g11 for pilot contracts (negation kind handled here, outside the frozen P2-C adapter) ----
_value_ok, _support_ok = S.value_ok, S.support_ok
def value_ok(fact, g, value):
    if g['kind'] == 'negation':
        return not isinstance(value, bool) and S.QS.BASE._denies(value)
    return _value_ok(fact, g, value)
def support_ok(fact, g, quote):
    if g['kind'] == 'negation':
        return bool(S.QS.BASE._DENIAL_RE.search(S.nt(quote)))
    return _support_ok(fact, g, quote)
S.value_ok, S.support_ok = value_ok, support_ok

# pilot-only doc-number format without brackets (e.g. 粤调查字20137): sensitivity wrapper, P2-C adapter untouched
import re as _re
_doc_tokens = S.doc_tokens
_PLAIN = _re.compile(r'(?:调查字|调查通字|处罚字)\s*(\d{4,6})(?!\d)(?!\s*号)')
def doc_tokens(text):
    out = _doc_tokens(text)
    out |= {('plain', int(x)) for x in _PLAIN.findall(S.nt(text))}
    return out
S.doc_tokens = doc_tokens

def pilot_spec(task, c, f):
    rule = f['grounding']['rule']
    if rule == 'negation':
        return dict(kind='negation', support_docs=list(f['allowed_citation_docs']))
    if rule == 'text' and '禁入' in f['predicate']:
        g = dict(kind='ban', support_docs=list(f['allowed_citation_docs']))
        d = S.durations(str(f['value'])); assert len(d) == 1
        g['duration'] = d.pop(); g['subject_any'] = sorted(set(B.names_of(f['subject']) + B.alias_variants(c, B.names_of(f['subject']))))
        return g
    return B.make_spec(task, c, f)

def build_pilot(task, path):
    c = json.loads(Path(path).read_text()); docs = S.doc_index(c); log = []
    for f in c['required_facts']:
        if f['grounding']['rule'] in ('amount', 'penalty_line_sum') and not f.get('unit'):
            units = {u for e in f['source_evidence'] for n, u in S.all_amounts(e['quote']) if u and str(n) == str(S.Decimal(str(f['value'])))}
            if len(units) == 1:
                f['unit'] = units.pop(); f['unit_inferred_for_sensitivity'] = True
        g = pilot_spec(task, c, f); f['g11'] = g
        assert S.value_ok(f, g, f['value']), (task, f['fact_id'])
        B.repair_spans(f, g, docs, c, log, task)
        for e in f['source_evidence']:
            e['role'] = 'support' if (e['doc_id'] in g['support_docs'] and S.nt(e['quote']) in docs[e['doc_id']]
                                      and S.support_ok(f, g, e['quote'])) else 'context'
    perfect = [dict(fact_id=f['fact_id'], value=f['value'], quote=next(e for e in f['source_evidence'] if e['role'] == 'support')['quote'],
                    doc=next(e for e in f['source_evidence'] if e['role'] == 'support')['doc_id']) for f in c['required_facts']]
    assert S.score(dict(answers=perfect), c)['Q_all'] == 1.0, task
    (OUT / f'{task}_g11_sensitivity.json').write_text(json.dumps(c, ensure_ascii=False, indent=1), 'utf-8')
    return c, log

# ---- reconstruct terminal outputs from the ledger ----
def reconstruct(ct, task, rep, done):
    blk = [r for r in done if r['task'] == task and r['rep'] == rep]
    by = {}
    for r in blk:
        by.setdefault((r['arm'], r['node']), []).append(r)
    shared = {n: by.get(('shared', n), [None])[-1] for n in ('E_D1', 'E_D2', 'J1', 'J2')}
    if any(v is None or v.get('fault') for v in shared.values()):
        return None
    docs = {d: v['pages']['1']['text'] for d, v in ct['source_pages'].items()}
    e_texts = {'E_D1': shared['E_D1']['text'], 'E_D2': shared['E_D2']['text']}
    docs_norm = P.R.SC.doc_index(ct)
    rows, _ = P.R.evidence_rows(e_texts, docs_norm)
    base = P.BT.total(P.OLD.extract_json(e_texts['E_D2']), docs['D2'])
    parse = lambda r: P.OLD.extract_json(r['text']) if r and not r.get('fault') else None
    out = {'G1': parse(by.get(('G1', 'G1'), [None])[-1]), 'G2': parse(by.get(('G2', 'SINK'), [None])[-1])}
    for a in ('G3', 'G4', 'G5', 'G6'):
        sinks = [r for r in by.get((a, 'SINK'), []) if not r.get('fault')]
        faulted = any(r.get('fault') for r in blk if r['arm'] == a)
        out[a] = parse(sinks[-1]) if sinks and not faulted else out['G2']
    for arm, o in out.items():
        if o:
            m3 = P.D5.detect_m3([dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'])
                                 for f in ct['required_facts']], o, rows, base)
            viol = sorted((f for f, v in m3.items() if v['state'] == 'SELF_EVIDENCE_INCONSISTENT'), key=lambda x: int(x[1:]))
            if viol:
                o['answers'] = [x for x in o.get('answers', []) if not (isinstance(x, dict) and x.get('fact_id') in viol)]
                o['unknown_slots'] = sorted(set(map(str, o.get('unknown_slots', []))) | set(viol), key=lambda x: int(x[1:]))
    return out

def main():
    done = [json.loads(l) for l in open(HERE / 'p2_runs/LEDGER.jsonl')]
    done = [r for r in done if r.get('phase') == 'done']
    recorded = json.loads((HERE / 'p2_runs/PILOT_RESULTS.json').read_text())
    report, mismatches = {}, []
    for task, path, _ in P.TASKS:
        ct_old = json.loads(Path(path).read_text())
        ct_new, log = build_pilot(task, path)
        for rep in (1, 2):
            key = f'{task}_r{rep}'
            if 'arms' not in recorded.get(key, {}):
                report[key] = dict(stopped=recorded.get(key)); continue
            outs = reconstruct(ct_old, task, rep, done)
            row = {}
            for arm in P.ARMS:
                q_old = P.TaskScorer(ct_old).score(json.loads(json.dumps(outs[arm])) if outs[arm] else None)['Q_all']
                if abs(q_old - recorded[key]['arms'][arm]['Q']) > 1e-9:
                    mismatches.append((key, arm, q_old, recorded[key]['arms'][arm]['Q']))
                sc = S.score(json.loads(json.dumps(outs[arm])) if outs[arm] else None, ct_new)
                row[arm] = dict(Q_original=recorded[key]['arms'][arm]['Q'], Q_rescored=sc['Q_all'], TP=sc['TP'], N=sc['N'])
            report[key] = row
        report[f'{task}_span_repairs'] = len(log)
    res = dict(note='SENSITIVITY ANALYSIS ONLY; P2-B pilot is not part of the P2-C confirmatory sample; original scores unchanged',
               reconstruction_validated=not mismatches, mismatches=mismatches, blocks=report)
    (OUT / 'P2B_RESCORE_RESULTS.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), 'utf-8')
    print('reconstruction reproduces original scores exactly:', not mismatches, mismatches[:6])
    for k, v in report.items():
        if isinstance(v, dict) and 'G2' in v:
            print(f'{k:14}', ' '.join(f"{a}:{v[a]['Q_original']:.2f}->{v[a]['Q_rescored']:.2f}" for a in P.ARMS))
        else:
            print(f'{k:14}', v)

if __name__ == '__main__':
    main()
