"""Phase V2.3-A / A2: PER-SLOT S0 + S1 non-substitutability screening.

Operator rule (2026-11-02 Phase V2.3-A §4): only SLOTS whose answer cannot be
uniquely determined from the remaining materials qualify for S2. A task enters
S2 iff it declares a target field with >= 2 qualifying slots (matching the
pre-registered S2 pass threshold of ">= 2 affected slots").

Per slot X (with gold span S_X and entities E_X auto-extracted from X's quote):
  S0(X): no entity in E_X occurs outside S_X in any document of the group.
  S1(X): after ablating the sentence(s) containing S_X, no entity in E_X
         survives anywhere in the remaining text.
Slot qualifies iff S0(X) and S1(X). No per-task tuning; entities are mechanical
numeric tokens plus preregistered symbolic entities.
"""
import json, re, sys, unicodedata
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23')
import validate_task_set_v23 as V
from screen_v23a import TASKS, NUM, _within_span, norm_find


def slot_entities(quote, extra):
    ents = set(extra)
    for m in NUM.findall(str(quote)):
        if len(m.replace(',', '').replace('.', '')) >= 4:
            ents.add(m)
    return sorted(ents)


def screen_slot(contract, fact, ents, keywords):
    fid = fact['fact_id']
    spans = [dict(doc_id=ev['doc_id'], page=str(ev['page']), start=ev['start'], end=ev['end'])
             for ev in fact.get('source_evidence') or []]
    if not spans:
        return dict(fact_id=fid, s0=None, s1=None, verdict='NO_SPAN')
    s0h = []
    for doc_id, doc in (contract.get('source_pages') or {}).items():
        for page, rec in (doc.get('pages') or {}).items():
            text = rec.get('text', '') if isinstance(rec, dict) else ''
            if not text:
                continue
            for e in ents:
                if norm_find(text, e):
                    if not _within_span(text, e, spans, doc_id, str(page)):
                        s0h.append(dict(doc_id=doc_id, page=page, entity=e))
    s1h = V.s1_scan(contract, dict(affected_slots=[fid], entities=ents,
                                   relation_keywords=keywords))
    ok0, ok1 = not s0h, not s1h
    return dict(fact_id=fid,
                s0=dict(pass_=ok0, hits=s0h[:4], n=len(s0h)),
                s1=dict(pass_=ok1, survivors=s1h[:3], n=len(s1h)),
                verdict='QUALIFIED' if (ok0 and ok1) else
                        ('S0_FAIL' if not ok0 else 'S1_FAIL'))


def main():
    report = {}
    for ev, cfg in TASKS.items():
        contract = json.load(open(cfg['contract']))
        facts = {f['fact_id']: f for f in contract.get('required_facts', [])}
        slots = []
        n_q = 0
        for fid in cfg['target_slots']:
            f = facts.get(fid)
            if f is None:
                slots.append(dict(fact_id=fid, verdict='MISSING_IN_CONTRACT'))
                continue
            extras = (cfg.get('slot_entities', {}) or {}).get(fid, [])
            ents = slot_entities((f.get('source_evidence') or [{}])[0].get('quote', ''), extras)
            r = screen_slot(contract, f, ents, cfg['keywords'])
            n_q += r['verdict'] == 'QUALIFIED'
            slots.append(r)
        eligible = n_q >= 2
        verdict = 'S2_ELIGIBLE' if eligible else 'NOT_ELIGIBLE'
        if cfg.get('expect') == 'MUST_FAIL':
            verdict = 'NEGCTRL_OK' if n_q < 2 else 'NEGCTRL_BROKEN'
        report[ev] = dict(contract=cfg['contract'], target_field=cfg['field'],
                          target_node=cfg['node'], slots=slots,
                          n_slots=len(cfg['target_slots']), n_qualified=n_q,
                          verdict=verdict)
        marks = ''.join('Y' if s.get('verdict') == 'QUALIFIED' else
                        ('n' if s.get('verdict') == 'MISSING_IN_CONTRACT' else 'x')
                        for s in slots)
        print(f"{ev:12s} {marks}  qualified {n_q}/{len(cfg['target_slots'])} -> {verdict}")
        for s in slots:
            if s.get('verdict') not in ('QUALIFIED', 'MISSING_IN_CONTRACT'):
                det = s['s0']['hits'][:2] if s['verdict'] == 'S0_FAIL' else s['s1']['survivors'][:2]
                print(f"    {s['fact_id']:5s} {s['verdict']:8s} {json.dumps(det, ensure_ascii=False)[:110]}")
    json.dump(dict(batch='PHASE_V23A_S0_S1_PER_SLOT', model_calls=0, tasks=report),
              open('/root/research_outputs/static_pi/stage_d/v23a/S0_S1_PER_SLOT.json', 'w'),
              ensure_ascii=False, indent=1)
    n = sum(1 for r in report.values() if r['verdict'] == 'S2_ELIGIBLE')
    print(f"\nS2-eligible tasks: {n}/{len(report) - 1} (T1 is the negative control)")


if __name__ == '__main__':
    main()
