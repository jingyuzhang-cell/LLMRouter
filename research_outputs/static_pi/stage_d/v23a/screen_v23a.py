"""Phase V2.3-A / A2: S0 + S1 non-substitutability screening for all candidates.

Mechanical and uniform: entities are auto-extracted from the target slots' gold
quotes (distinctive numeric tokens), so no per-task tuning of what counts as the
carried information. T1 runs as the negative control and must fail.

S0 (structural): entities carried by the target field must not occur outside the
    gold spans of the affected slots in ANY document of the group.
S1 (deterministic): ablate the whole sentence(s) containing the affected gold
    spans; the entities must not survive anywhere in the remaining text.
"""
import json, re, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23')
import validate_task_set_v23 as V

NUM = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{5,}(?:\.\d+)?')

TASKS = {
 'ZIJING': dict(contract='tasks/TASK_CONTRACT_ZIJING_SILVER.json',
   target_slots=['D1','D2','D3','D4','D5','D6','D7'], field='penalty_amounts',
   node='E_处罚决定书', extra_entities=[], keywords=['罚款','处以']),
 'ZEDA': dict(contract='tasks/TASK_CONTRACT_ZEDA_SILVER.json',
   target_slots=['D1','D2','D3','D4','D5','D6'], field='penalty_amounts',
   node='E_处罚决定书', extra_entities=[], keywords=['罚款','处以']),
 'ZHANGZIDAO': dict(contract='tasks/TASK_CONTRACT_ZHANGZIDAO_SILVER.json',
   target_slots=['D1','D2','D3','D4','D5','D6'], field='penalty_amounts',
   node='E_处罚决定书', extra_entities=[], keywords=['罚款','禁入','处以'],
   slot_entities={'D4': ['终身市场禁入'], 'D5': ['10 年市场禁入'], 'D6': ['5 年证券市场禁入']}),
 'KANGMEI': dict(contract='tasks/TASK_CONTRACT_KANGMEI_SILVER.json',
   target_slots=['D1','D2','D3','D4','D5'], field='penalty_amounts',
   node='E_处罚决定书', extra_entities=[], keywords=['罚款','处以','禁入'],
   slot_entities={'D5': ['终身证券市场禁入']}),
 'KDX': dict(contract='tasks/TASK_CONTRACT_KDX_SILVER.json',
   target_slots=['C1','C2','C3','C4','C5'], field='penalty_amounts',
   node='E_处罚决定书', extra_entities=[], keywords=['罚款','处以','禁入'],
   slot_entities={'C5': ['终身证券市场']}),
 'YJT': dict(contract='tasks/TASK_CONTRACT_YJT_SILVER.json',
   target_slots=['A1','A2','A3','A4','A5'], field='occupation_amounts',
   node='E_事先告知书', extra_entities=[], keywords=['占用','净资产比例']),
 'SJZG': dict(contract='tasks/TASK_CONTRACT_SJZG_SILVER.json',
   target_slots=['C1','A1','A2'], field='regulatory_actions',
   node='E_恢复服务公告', extra_entities=[], keywords=['罚款','约谈','处罚'],
   slot_entities={'C1': ['津网信罚决字','三十万'], 'A1': ['敏感有害信息','天津市互联网信息办公室'],
                  'A2': ['关于公司网站暂停服务的公告']}),
 'GUOEN': dict(contract='tasks/TASK_CONTRACT_GUOEN_SILVER.json',
   target_slots=['B1','B2','B3','B4','B5','B6','B7'], field='payment_schedule',
   node='E_收购公告', extra_entities=['79,240.00','60,160.00','11,000.00','1,000.00'], keywords=['交易价款','共管账户','定金']),
 'MVR2': dict(contract='/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR2_yuandao/TASK_CONTRACT_MVR2_v1.json',
   target_slots=['FA1','FA2','FA3','FB1','FB2','FB3','FB4','FB5','FC1','FC2'], field='penalty_amounts',
   node='E_处罚决定书', extra_entities=[], keywords=['罚款','处以']),
 'E04': dict(contract='/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2/TASK_CONTRACT_PHASE2_E04_v1.json',
   target_slots=['M1','M2','M3','M4','M5','M6','DV1','DV2','DV3'], field='inflated_financials',
   node='E_进展公告', extra_entities=[], keywords=['虚增']),
 'E06': dict(contract='/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2/TASK_CONTRACT_PHASE2_E06_v1.json',
   target_slots=['G1','G2','G3','G4','G5','G6','G7','DV1','DV2','DV3','DV4'], field='forecast_figures',
   node='E_业绩预告', extra_entities=[], keywords=['净利润','营业收入','每股收益']),
 'MVR1': dict(contract='/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR1_shuntian/TASK_CONTRACT_MVR1_v1.json',
   target_slots=['F1','F2','F3','F4','F5','F6','F7'], field='penalty_amounts',
   node='E_处罚决定书', extra_entities=[], keywords=['罚款','处以']),
 'E08': dict(contract='/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/E08_zhongtie/TASK_CONTRACT_E08_SILVER_DRAFT.json',
   target_slots=['F4','F6','F7','F8','F9','F10'], field='notice_details',
   node='E_立案公告', extra_entities=['证监立案字'], keywords=['立案','涉嫌']),
 'T1_NEGCTRL': dict(contract='/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/TASK_CONTRACT_PHASE2B_v2_1.json',
   target_slots=['A1','A2','A5'], field='positions',
   node='E2', extra_entities=['俞发祥'], keywords=['实际控制人','个人','立案'],
   slot_entities={'A1': ['俞发祥'], 'A2': ['俞发祥'], 'A5': ['实际控制人']},
   expect='MUST_FAIL'),
}


def entities_from(contract, slots):
    ents = set()
    for f in contract.get('required_facts', []):
        if f.get('fact_id') not in slots:
            continue
        for ev in f.get('source_evidence') or []:
            for m in NUM.findall(str(ev.get('quote', ''))):
                if len(m.replace(',', '').replace('.', '')) >= 4:
                    ents.add(m)
    return sorted(ents)


def norm_find(text, entity):
    """Normalized (whitespace/full-width) containment."""
    return V.norm(entity) in V.norm(text)


def s0(contract, slots, entities):
    """Entity occurrences outside the affected gold spans, in any document."""
    spans = V._affected_spans(contract, slots)
    outside = []
    for doc_id, doc in (contract.get('source_pages') or {}).items():
        for page, rec in (doc.get('pages') or {}).items():
            text = rec.get('text', '') if isinstance(rec, dict) else ''
            if not text:
                continue
            for e in entities:
                nt = V.norm(text)
                ne = V.norm(e)
                start = 0
                while True:
                    i = nt.find(ne, start)
                    if i < 0:
                        break
                    # find raw approx position by ratio mapping (report-only)
                    outside.append(dict(doc_id=doc_id, page=page, entity=e, approx_norm_pos=i))
                    break  # one hit per entity per page is enough for the verdict
                # if not found on this page, nothing to record
    # recompute properly: which entities occur in docs at all (any position)
    hits = []
    for doc_id, doc in (contract.get('source_pages') or {}).items():
        for page, rec in (doc.get('pages') or {}).items():
            text = rec.get('text', '') if isinstance(rec, dict) else ''
            if not text:
                continue
            for e in entities:
                if norm_find(text, e):
                    inside = any(s['doc_id'] == doc_id and s['page'] == str(page) for s in spans)
                    if not (inside and _within_span(text, e, spans, doc_id, str(page))):
                        hits.append(dict(doc_id=doc_id, page=page, entity=e))
    return hits


def _within_span(text, entity, spans, doc_id, page):
    """True if EVERY occurrence of entity on this page lies inside an affected span."""
    rel = [s for s in spans if s['doc_id'] == doc_id and s['page'] == str(page)]
    if not rel:
        return False
    nt, ne = V.norm(text), V.norm(entity)
    # walk raw text with norm mapping to find all raw occurrences
    occ = []
    m = {}
    ni = 0
    import unicodedata
    for ri, ch in enumerate(text):
        c = unicodedata.normalize('NFKC', ch)
        if c.strip() == '':
            continue
        for k in range(len(c)):
            m[ni + k] = ri
        ni += len(c)
    i = nt.find(ne)
    while i >= 0:
        s_raw = m.get(i)
        e_raw = m.get(i + len(ne) - 1)
        if s_raw is not None and e_raw is not None:
            occ.append((s_raw, e_raw))
        i = nt.find(ne, i + 1)
    if not occ:
        return True
    return all(any(s['start'] <= a and b <= s['end'] for s in rel) for a, b in occ)


def s1(contract, slots, entities, keywords):
    """Sentence-ablate the affected spans; entities must not survive anywhere."""
    spec = dict(affected_slots=slots, entities=entities, relation_keywords=keywords)
    survivors = V.s1_scan(contract, spec)
    # keep only survivors whose keyword is meaningful or entity is an amount
    return survivors


def main():
    report = {}
    for ev, cfg in TASKS.items():
        contract = json.load(open(cfg['contract']))
        ents = sorted(set(entities_from(contract, cfg['target_slots']) + cfg.get('extra_entities', [])))
        s0h = s0(contract, cfg['target_slots'], ents)
        s1h = s1(contract, cfg['target_slots'], ents, cfg['keywords'])
        s0_pass, s1_pass = not s0h, not s1h
        verdict = 'S2_ELIGIBLE' if (s0_pass and s1_pass) else ('S0_FAIL' if not s0_pass else 'S1_FAIL')
        if cfg.get('expect') == 'MUST_FAIL':
            ok = (not s0_pass) or (not s1_pass)
            verdict = 'NEGCTRL_OK' if ok else 'NEGCTRL_BROKEN'
        report[ev] = dict(
            contract=cfg['contract'], target_field=cfg['field'], target_node=cfg['node'],
            target_slots=cfg['target_slots'], n_entities=len(ents), entities=ents[:12],
            s0=dict(pass_=s0_pass, hits=s0h[:8], n_hits=len(s0h)),
            s1=dict(pass_=s1_pass, survivors=s1h[:6], n_surv=len(s1h)),
            verdict=verdict)
        print(f"{ev:12s} slots={len(cfg['target_slots']):2d} ents={len(ents):2d} "
              f"S0={'PASS' if s0_pass else 'FAIL(' + str(len(s0h)) + ')':>10s} "
              f"S1={'PASS' if s1_pass else 'FAIL(' + str(len(s1h)) + ')':>10s} -> {verdict}")
        if not s0_pass:
            for h in s0h[:4]:
                print(f"    S0 hit: {h['entity']} also in {h['doc_id']} p{h['page']}")
        if not s1_pass:
            for h in s1h[:3]:
                print(f"    S1 survivor: {h['entity']}+{h['keyword']} in {h['doc_id']} p{h['start']}")
    json.dump(dict(batch='PHASE_V23A_S0_S1_SCREENING', model_calls=0, tasks=report),
              open('/root/research_outputs/static_pi/stage_d/v23a/S0_S1_SCREENING.json', 'w'),
              ensure_ascii=False, indent=1)
    n_pass = sum(1 for r in report.values() if r['verdict'] == 'S2_ELIGIBLE')
    print(f"\nS2-eligible tasks: {n_pass}/{len(report) - 1} (excluding negative control)")


if __name__ == '__main__':
    main()
