"""QP5-A v2: PURE evidence-provision contrast — prep audit (zero calls).

Design P2: both arms share the IDENTICAL fact set (m's full facts, same
fact_ids / values / types). The only intervention is whether verified
evidence is PROVIDED to the SINK:
  B1: facts rendered without evidence fields.
  B2: same facts; the verified subset additionally carries doc/page/quote
      (in-fact and in a table); copy-rule applies ONLY to listed facts;
      NO abstention-policy change (unlisted facts answered as usual).

Audits:
  A1 fact-set identity   both prompts carry the same fact_ids+values+types
  A2 single-intervention diff confined to evidence fields/table/copy-rule
  A3 treatment validity  per-pair table size, evidence-bearing share, fires
  A4 budget              measured p-node costs x 24 SINK calls
"""
import json, sys, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
import qp4_factorial as F
import qp2_chain as CH
import qp1_prompts as P1
import qp3_primitives as P3
import scorer_qp1 as Q1
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'

COPY_RULE = ('证据复用规则（仅适用于下表列出的槽位）：answers 中这些槽位的 doc、page、quote '
             '必须逐字复制下表对应条目（含标点与空格）；未在下表列出的槽位照常作答，不受本规则影响。')


def fact_key(e):
    return str(e.get('field') or e.get('fact_id'))


def strict(v, f):
    return bool(v not in (None, '')) and Q1.TQ._value_equal(
        {'value': v, 'value_kind': f.get('value_kind')}, dict(f))


def match_evidence(m_facts, verified, contract):
    """Attach each verified entry to an m-fact by name, then by value-grounding."""
    out = {}
    for e in verified:
        cands = [k for k in m_facts if P3.name_matches(e, dict(bucket=k))]
        if not cands:
            q = e.get('quote', '')
            cands = [k for k, v in m_facts.items()
                     if v not in (None, '') and (Q1.value_in_quote(v, q) or
                                                 str(v)[:8] in str(e.get('raw') or e.get('value') or ''))]
        if cands:
            out.setdefault(cands[0], e)
    return out


def render(contract, r, m_facts, evidence_map, with_evidence):
    facts_out = []
    table = []
    for k in m_facts:
        v = m_facts[k]
        entry = dict(field=k, value=v)
        ev = evidence_map.get(k)
        if with_evidence and ev is not None:
            entry.update(doc=ev.get('doc'), page=ev.get('page'), quote=ev.get('quote', ''))
            table.append(f"{k} | doc={ev.get('doc')} | page={ev.get('page')} | quote={ev.get('quote', '')}")
        facts_out.append(entry)
    u = P1.p_user(contract, {'facts': facts_out}, r, [], 'E1') + '\n\n' + F.VALUE_FORM_RULES
    if with_evidence and table:
        u += ('\n\n已核验证据表（仅下列槽位）：\n' + '\n'.join(table) + '\n\n' + COPY_RULE)
    return u


def main():
    led = {}
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        led[(p[1], p[2], p[3], p[4])] = x
    p_costs = collections.defaultdict(list)
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        if len(p) == 5 and p[4] == 'p':
            p_costs[p[1]].append(x['accounting_yuan'])

    pairs = []
    for t in F.TASKS:
        for rep in (1, 2):
            contract = F.load_contract(t)
            e0 = extract_any(led[(t, 'D', f'r{rep}', 'e0')]['text'])
            e1 = extract_any(led[(t, 'D', f'r{rep}', 'e1')]['text'])
            m = extract_any(led[(t, 'D', f'r{rep}', 'm')]['text'])
            r = extract_any(led[(t, 'D', f'r{rep}', 'r')]['text'])
            entries = P3.normalize_stage(e0) + P3.normalize_stage(e1)
            verified, _ = CH.verify_evidence(entries, contract)
            m_facts = {}
            for e in P3.normalize_stage(m):
                k = fact_key(e)
                if k and e.get('value') not in (None, ''):
                    m_facts.setdefault(k, e.get('value'))
            ev_map = match_evidence(m_facts, verified, contract)
            b1 = render(contract, r, m_facts, ev_map, with_evidence=False)
            b2 = render(contract, r, m_facts, ev_map, with_evidence=True)
            n_facts = len(m_facts)
            pairs.append(dict(task=t, rep=rep, n_facts=n_facts,
                              table_entries=len(ev_map),
                              evidence_share=round(len(ev_map) / max(1, n_facts), 3),
                              fires=len(ev_map) > 0,
                              b1_chars=len(b1), b2_chars=len(b2)))
    est = sum(st.mean(p_costs[t]) for t in F.TASKS) * 2 * 2
    out = dict(batch='QP5A_V2_PREP_AUDIT', model_calls=0,
               design='P2 pure evidence provision: identical fact set; only evidence fields+table+copy-rule differ',
               pairs=pairs,
               fact_set_identity='by construction: same m-facts dict rendered by the same function, with_evidence flag only',
               intervention='evidence fields on matched facts + verified table + copy-rule LIMITED to listed facts; NO abstention-policy change',
               treatment_fires=f"{sum(1 for p in pairs if p['fires'])}/{len(pairs)}",
               mean_evidence_share=round(st.mean(p['evidence_share'] for p in pairs), 3),
               budget=dict(new_sink_calls=24, est_yuan=round(est, 4),
                           cap=dict(calls=30, yuan=0.60)))
    json.dump(out, open(f'{QP}/QP5A_V2_PREP_AUDIT.json', 'w'), ensure_ascii=False, indent=1)
    for p in pairs:
        print(f"  {p['task']:9s} r{p['rep']} m_facts={p['n_facts']:2d} evidence={p['table_entries']:2d} "
              f"share={p['evidence_share']:.2f} fires={p['fires']} b1={p['b1_chars']} b2={p['b2_chars']}")
    print('fires:', out['treatment_fires'], '| mean evidence share:', out['mean_evidence_share'])
    print('budget:', out['budget'])


if __name__ == '__main__':
    main()
