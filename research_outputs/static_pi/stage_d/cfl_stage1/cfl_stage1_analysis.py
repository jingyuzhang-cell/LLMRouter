"""CFL Stage-1: offline evaluation of gold-blind correctness signals (ZERO calls).

Signals (all gold-blind, computed on the PRIMARY=DS side):
  S0 fact answered (node-level = completeness fraction)      [QP7/QP9 trigger]
  S1 cross-model disagreement: both models extracted a value for the fact
     and the two values do not agree under frozen value_equal_anyway levels
  S2 evidence-support fail: value not grounded in its own cited quote,
     or quote missing / not verbatim in the cited page       [value_in_quote reuse]
  S3 = S1 OR S2

Gold is used ONLY post-hoc to label facts into six categories and score signals.

Frozen corpora (request bodies reconstructed & sha-verified in inventory step):
  E-node pairs   : E06/MVR1/KANGMEI (QP8R DS+GLM) ; ZEDA/ZIJING (QP9 DS + QP4-B GLM)
  SINK (QP9)     : per task 6 identical-prompt DS first-pass outputs;
                   GLM switch partners: ZEDA r1, ZIJING r1/r2;
                   60 DS-DS same-prompt pairs as the S1 noise baseline.
"""
import json, sys, os, hashlib

SD = '/root/research_outputs/static_pi/stage_d'
sys.path.insert(0, f'{SD}/quality_phase_v1')
sys.path.insert(0, f'{SD}/qp3')
sys.path.insert(0, f'{SD}/v2')
sys.path.insert(0, SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import qp3_primitives as P3
import scorer_qp1 as Q1
import terminal_quality as TQ

OUT = f'{SD}/cfl_stage1'
TASKS_E = ['E06', 'MVR1', 'KANGMEI', 'ZEDA', 'ZIJING']
TASKS_SINK = ['MVR1', 'KANGMEI', 'ZEDA', 'ZIJING']


def load_contract(t):
    p = [x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if x['event_key'] == t][0]['contract']
    if not os.path.isabs(p): p = f'{SD}/v23a/{p}'
    return json.load(open(p))


def ledger(path):
    d = {}
    for l in open(path):
        x = json.loads(l)
        d[x['purpose']] = x
    return d


QP8R = ledger(f'{SD}/qp8/QP8R_STAGE1_LEDGER.jsonl')
QP4 = ledger(f'{SD}/quality_phase_v1/QP4_LEDGER.jsonl')
QP9 = ledger(f'{SD}/qp9/QP9_LEDGER.jsonl')


def facts_of(contract):
    return [f for f in contract.get('required_facts', [])
            if f.get('status') not in ('EXCLUDED', 'NOT_APPLICABLE')]


# ---------- binding an entry to a fact (label side; Gold allowed here) ----------
# Reuses frozen QP3 primitives only (name_matches / value_equal_anyway /
# scorer_qp1.value_in_quote, i.e. the documented entry_has_info branches).

def bind_fact(entries, fact):
    """Best parser_v2 entry for fact by name_matches; status + stored fields.
    QUOTE_GROUNDED = no explicit value but the gold value is grounded in the
    entry's quote (QP3 entry_has_info value-less branch)."""
    cands = [e for e in entries if P3.name_matches(e, fact)]
    if not cands:
        return dict(status='NO_MATCH')
    def rank(e):
        v = e.get('raw') or e.get('value')
        ok, level = (P3.value_equal_anyway(v, fact) if v not in (None, '') else (False, None))
        qg = bool(e.get('quote')) and Q1.value_in_quote(fact.get('value'), e.get('quote', ''))
        return (ok, v not in (None, ''), qg, level or '')
    best = max(cands, key=rank)
    v = best.get('raw') or best.get('value')
    if v not in (None, ''):
        ok, level = P3.value_equal_anyway(v, fact)
        st = 'CORRECT' if ok and level in ('strict', 'tolerant') else \
             ('FORMAT_DIFF' if ok else 'SEMANTIC_ERROR')
        return dict(status=st, level=level, value=str(v), quote=best.get('quote', ''),
                    doc=best.get('doc'), page=best.get('page'), entry=best)
    qg = bool(best.get('quote')) and Q1.value_in_quote(fact.get('value'), best.get('quote', ''))
    if qg:
        return dict(status='QUOTE_GROUNDED', value=None, quote=best.get('quote', ''),
                    doc=best.get('doc'), page=best.get('page'), entry=best)
    return dict(status='NO_MATCH', entry=best)


def entry_key(e):
    return Q1._norm(f"{e.get('bucket') or ''}|{e.get('field') or e.get('predicate') or ''}")


def key_view(entries):
    """key -> representative entry (prefer entries with explicit values)."""
    view = {}
    for e in entries:
        k = entry_key(e)
        cur = view.get(k)
        if cur is None or ((e.get('value') not in (None, '')) and
                           (cur.get('value') in (None, ''))):
            view[k] = e
    return view


# ---------- gold-blind signal primitives ----------

def values_agree(a, b):
    """Cross-model value agreement under frozen levels (no Gold)."""
    if a in (None, '') or b in (None, ''):
        return None  # not comparable
    if Q1._norm(a) == Q1._norm(b):
        return True
    ok, level = P3.value_equal_anyway(a, {'value': b, 'value_kind': None})
    return bool(ok and level in ('strict', 'tolerant', 'decorated'))


def s2_fire(rec):
    """Evidence-support check on the primary-side record (Gold-blind)."""
    q = rec.get('quote') or ''
    v = rec.get('value')
    if not q:
        return True, 'no_quote'
    if not Q1.value_in_quote(v, q):
        return True, 'value_not_in_quote'
    return False, None


def s2_fire_sink(ans, contract):
    q = ans.get('quote') or ''
    v = ans.get('value')
    if not q:
        return True, 'no_quote'
    if not Q1.value_in_quote(v, q):
        return True, 'value_not_in_quote'
    doc = contract.get('source_pages', {}).get(str(ans.get('doc')))
    pg = (doc or {}).get('pages', {}).get(str(ans.get('page')))
    if pg is None:
        return True, 'page_missing'
    if Q1._norm(q) not in Q1._norm(pg.get('text', '')):
        return True, 'quote_not_in_page'
    return False, None


# ---------- E-level build ----------

def e_entries(task, model):
    ents = []
    for node in ('e0', 'e1'):
        if model == 'DS':
            r = QP8R.get(f'qp8r|{task}|DS|r1|{node}') or QP9.get(f'qp9|{task}|E|deepseek|{node}')
        else:
            r = QP8R.get(f'qp8r|{task}|GLM|r1|{node}') or QP4.get(f'qp4|{task}|B|r1|{node}')
        ents += parse2(extract_any(r['text']) or {})
    return ents


def build_e_level():
    samples = []
    for task in TASKS_E:
        contract = load_contract(task)
        ds_ents, glm_ents = e_entries(task, 'DS'), e_entries(task, 'GLM')
        ds_keys, glm_keys = key_view(ds_ents), key_view(glm_ents)
        for f in facts_of(contract):
            ds, glm = bind_fact(ds_ents, f), bind_fact(glm_ents, f)
            # runtime S1: compare same-key values across models (gold-blind)
            bound_entry = ds.get('entry') or glm.get('entry')
            k = entry_key(bound_entry) if bound_entry is not None else None
            s1 = False; comp = False
            if k and k in ds_keys and k in glm_keys:
                dv, gv = ds_keys[k].get('value'), glm_keys[k].get('value')
                ag = values_agree(dv, gv)
                if ag is not None:
                    comp = True
                    s1 = (ag is False)
            s2, s2why = (s2_fire(ds) if ds['status'] in ('CORRECT', 'FORMAT_DIFF',
                                                        'SEMANTIC_ERROR') else (False, None))
            # S1c (variant): DS asserts a value; the alternative model's evidence
            # for the same key does not ground it (cross-grounding disagreement)
            s1c = False; comp_c = False
            if k and ds.get('value') and k in glm_keys:
                gq = ' '.join(e.get('quote', '') for e in glm_ents if entry_key(e) == k)
                if gq.strip():
                    comp_c = True
                    s1c = not Q1.value_in_quote(ds['value'], gq)
            # six categories, primary = DS (format-recoverable = cat5)
            if ds['status'] == 'CORRECT':
                cat = 1
            elif ds['status'] in ('FORMAT_DIFF', 'QUOTE_GROUNDED'):
                cat = 5
            elif glm['status'] == 'CORRECT':
                cat = 2
            elif ds['status'] == 'NO_MATCH' and glm['status'] == 'NO_MATCH':
                cat = 3
            else:
                cat = 4
            samples.append(dict(
                level='E', task=task, fact_id=f['fact_id'], critical=bool(f.get('critical')),
                gold=str(f.get('value')), ds_status=ds['status'], glm_status=glm['status'],
                ds_value=ds.get('value'), glm_value=glm.get('value'), key=k,
                ds_quote=(ds.get('quote') or '')[:80], category=cat,
                S0_answered=ds['status'] != 'NO_MATCH',
                S1_disagree=s1, comparable=comp, S1c_cross_ground=s1c, comparable_c=comp_c,
                S2_unsupported=s2, s2_reason=s2why, S3=s1 or s2, S3c=s1c or s2))
    return samples


# ---------- SINK-level build (QP9) ----------

def sink_answers(task, arm, rep, which='p'):
    r = QP9.get(f'qp9|{task}|{arm}|r{rep}|{which}')
    if r is None:
        return None
    obj = extract_any(r['text'])
    return {a.get('fact_id'): a for a in (obj or {}).get('answers', [])
            if isinstance(a, dict) and a.get('fact_id')} if isinstance(obj, dict) else {}


def sink_value_ok(ans, fact):
    return bool(TQ._value_equal({'value': ans.get('value'),
                                 'value_kind': fact.get('value_kind')}, dict(fact)))


def build_sink_level():
    samples, noise, pair_samples = [], [], []
    for task in TASKS_SINK:
        contract = load_contract(task)
        fl = {f['fact_id']: f for f in facts_of(contract)}
        ds_cells = [(a, r) for a in ('A_static', 'B_r_only', 'C_r_pi') for r in (1, 2)]
        glm_cells = dict(ZEDA=[('C_r_pi', 1)], ZIJING=[('C_r_pi', 1), ('C_r_pi', 2)]).get(task, [])
        ds_maps = {(a, r): sink_answers(task, a, r) for a, r in ds_cells}
        glm_maps = {(a, r): sink_answers(task, a, r, 'p_switch') for a, r in glm_cells}
        for fid, f in fl.items():
            row = dict(level='SINK', task=task, fact_id=fid, critical=bool(f.get('critical')),
                       gold=str(f.get('value')), ds_cells={}, glm_cells={})
            # primary DS view: majority over the 6 first-pass cells
            vok, answered, s2f = 0, 0, 0
            for cell, amap in ds_maps.items():
                a = (amap or {}).get(fid)
                if a and a.get('value') not in (None, ''):
                    answered += 1
                    vok += sink_value_ok(a, f)
                    f2, why = s2_fire_sink(a, contract)
                    s2f += f2
                    row['ds_cells'][f'{cell[0][-7:]}_r{cell[1]}'] = dict(
                        value=str(a.get('value')), v_ok=sink_value_ok(a, f),
                        S2=f2, why=why)
                else:
                    row['ds_cells'][f'{cell[0][-7:]}_r{cell[1]}'] = dict(value=None)
            n = len(ds_maps)
            ds_answered = answered >= n / 2
            ds_vok = vok >= n / 2
            # S1: per-cell partner comparison — the GLM switch cell's own DS
            # first-pass is the comparison partner (runtime-realistic pairing)
            s1 = False; comp = False
            for cell, gmap in glm_maps.items():
                a_ds = (ds_maps.get(cell) or {}).get(fid)
                a_g = (gmap or {}).get(fid)
                v_ds = a_ds.get('value') if a_ds else None
                v_g = a_g.get('value') if a_g else None
                ag = values_agree(v_ds, v_g)
                if ag is not None:
                    comp = True
                    s1 = s1 or (ag is False)
                    row['glm_cells'][f'r{cell[1]}'] = dict(value=str(v_g),
                                                           v_ok=sink_value_ok(a_g, f),
                                                           partner_ds=str(v_ds))
                elif v_g is not None:
                    row['glm_cells'][f'r{cell[1]}'] = dict(value=str(v_g),
                                                           v_ok=sink_value_ok(a_g, f))
            s2 = (s2f > 0) if ds_answered else False
            gvals = [c['value'] for c in row['glm_cells'].values() if c.get('value')]
            glm_ok = bool(gvals) and all(sink_value_ok({'value': g}, f) for g in gvals)
            if ds_vok:
                cat = 1
            elif not ds_answered and not gvals:
                cat = 3
            elif glm_ok:
                cat = 2
            elif not ds_answered:
                cat = 3 if not gvals else 4
            else:
                cat = 4
            row.update(ds_answered=ds_answered, ds_vok=ds_vok, glm_has=gvals[:2],
                       glm_ok=glm_ok, category=cat,
                       S0_answered=ds_answered, S1_disagree=s1, comparable=comp,
                       S2_unsupported=s2, S3=s1 or s2)
            samples.append(row)
        # pair-level eval: each GLM cell vs its own DS first-pass partner
        for cell in glm_cells:
            m_ds, m_g = ds_maps[cell], glm_maps[cell]
            for fid, f in fl.items():
                a1 = (m_ds or {}).get(fid)
                a2 = (m_g or {}).get(fid)
                v1 = a1.get('value') if a1 else None
                v2 = a2.get('value') if a2 else None
                ag = values_agree(v1, v2)
                s1 = (ag is False)
                ok1 = (v1 not in (None, '')) and sink_value_ok(a1, f)
                ok2 = (v2 not in (None, '')) and sink_value_ok(a2, f)
                s2p, why = (s2_fire_sink(a1, contract) if v1 not in (None, '')
                            else (False, None))
                if ok1:
                    cat = 1
                elif v1 in (None, '') and v2 in (None, ''):
                    cat = 3
                elif ok2:
                    cat = 2
                else:
                    cat = 4
                pair_samples.append(dict(
                    task=task, cell=f"{cell[0]}_r{cell[1]}", fact_id=fid,
                    ds_value=str(v1) if v1 not in (None, '') else None,
                    glm_value=str(v2) if v2 not in (None, '') else None,
                    ds_ok=ok1, glm_ok=ok2, S0_answered=v1 not in (None, ''),
                    S1_disagree=s1, comparable=ag is not None,
                    S2_unsupported=s2p, S3=s1 or s2p,
                    category=cat, tgt_wrong=(v1 not in (None, '')) and not ok1))
        # DS-DS noise pairs (same prompt): 15 per task
        cells = [(a, r) for a in ('A_static', 'B_r_only', 'C_r_pi') for r in (1, 2)]
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                m1, m2 = ds_maps[cells[i]], ds_maps[cells[j]]
                for fid, f in fl.items():
                    a1 = (m1 or {}).get(fid); a2 = (m2 or {}).get(fid)
                    v1 = a1.get('value') if a1 else None
                    v2 = a2.get('value') if a2 else None
                    ag = values_agree(v1, v2)
                    if ag is None:
                        continue
                    noise.append(dict(task=task, fact_id=fid,
                                      agree=ag, v_ok=sink_value_ok(a1, f)))
    return samples, noise, pair_samples


# ---------- metrics ----------

def pr(rows, pred, target):
    tp = sum(1 for r in rows if r[pred] and r[target])
    fp = sum(1 for r in rows if r[pred] and not r[target])
    fn = sum(1 for r in rows if not r[pred] and r[target])
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    return dict(tp=tp, fp=fp, fn=fn, precision=round(prec, 3) if prec is not None else None,
                recall=round(rec, 3) if rec is not None else None)


def main():
    os.makedirs(OUT, exist_ok=True)
    E = build_e_level()
    S, noise, PS = build_sink_level()

    def wrong_any(r):
        # E rows: DS asserted a value that is not correct.
        # SINK rows: majority DS view. Pair rows: the DS partner cell.
        if 'ds_status' in r:
            return r['ds_status'] == 'SEMANTIC_ERROR'
        if 'ds_vok' in r:
            return r['ds_answered'] and not r['ds_vok']
        return bool(r['S0_answered']) and not r['ds_ok']

    def add_targets(rows):
        for r in rows:
            r['tgt_wrong'] = wrong_any(r)
            r['tgt_recoverable'] = r['category'] == 2
            r['tgt_unrecoverable'] = r['category'] in (3, 4)
        return rows
    E, S, PS = add_targets(E), add_targets(S), add_targets(PS)

    metrics = {}
    sigs = ('S0_answered', 'S1_disagree', 'S2_unsupported', 'S3')
    EZ = [r for r in E if r['task'] != 'ZIJING']
    for rows, name in ((E, 'E_level'), (EZ, 'E_level_excl_ZIJING_binder_artifact'),
                       (S, 'SINK_level'), (PS, 'SINK_pair_level')):
        use = sigs if not name.startswith('E_level') else sigs + ('S1c_cross_ground', 'S3c')
        metrics[name] = {
            sig: {
                'detect_ds_value_wrong': pr(rows, sig, 'tgt_wrong'),
                'detect_recoverable': pr(rows, sig, 'tgt_recoverable'),
                'n_cat': {str(c): sum(1 for r in rows if r['category'] == c) for c in (1, 2, 3, 4, 5)},
                'n_comparable': sum(1 for r in rows if r.get('comparable', False) or r.get('comparable_c', False)),
                'fire_rate_on_correct_cat1': round(sum(1 for r in rows if r[sig] and r['category'] == 1)
                                                   / max(1, sum(1 for r in rows if r['category'] == 1)), 3),
                'fire_rate_on_unrecoverable_cat34': round(sum(1 for r in rows if r[sig] and r['tgt_unrecoverable'])
                                                          / max(1, sum(1 for r in rows if r['tgt_unrecoverable'])), 3),
                'fire_rate_on_format_cat5': round(sum(1 for r in rows if r[sig] and r['category'] == 5)
                                                  / max(1, sum(1 for r in rows if r['category'] == 5)), 3),
                'miss_rate_on_recoverable': round(sum(1 for r in rows if not r[sig] and r['tgt_recoverable'])
                                                  / max(1, sum(1 for r in rows if r['tgt_recoverable'])), 3),
            } for sig in use}

    # S1 noise baseline
    dis = [p for p in noise if not p['agree']]
    metrics['S1_noise_baseline_DS_DS'] = dict(
        pairs_facts=len(noise), disagreements=len(dis),
        disagreement_rate=round(len(dis) / max(1, len(noise)), 3),
        disagreement_rate_on_correct=round(sum(1 for p in dis if p['v_ok']) / max(1, sum(1 for p in noise if p['v_ok'])), 3),
        disagreement_rate_on_wrong=round(sum(1 for p in dis if not p['v_ok']) / max(1, sum(1 for p in noise if not p['v_ok'])), 3))

    # error-localization trace: where does the terminal wrongness enter?
    e_by = {(r['task'], r['fact_id']): r for r in E}
    loc = {}
    for task in ('KANGMEI', 'MVR1', 'ZEDA', 'ZIJING'):
        cnt = dict(n=len([r for r in S if r['task'] == task]),
                   E_ok_SINK_ok=0, E_fmt_SINK_fixed=0,
                   SINK_localized_error=0, E_localized_error=0,
                   E_bad_SINK_ok=0, sink_abstained=0)
        for r in [x for x in S if x['task'] == task]:
            er = e_by.get((task, r['fact_id']))
            e_ok = er is not None and er['ds_status'] == 'CORRECT'
            e_fmt = er is not None and er['ds_status'] in ('FORMAT_DIFF', 'QUOTE_GROUNDED')
            s_ok = r['ds_vok']
            if not r['ds_answered']:
                cnt['sink_abstained'] += 1
            elif e_ok and s_ok:
                cnt['E_ok_SINK_ok'] += 1
            elif e_fmt and s_ok:
                cnt['E_fmt_SINK_fixed'] += 1
            elif (e_ok or e_fmt) and not s_ok:
                cnt['SINK_localized_error'] += 1
            elif not (e_ok or e_fmt) and not s_ok:
                cnt['E_localized_error'] += 1
            else:
                cnt['E_bad_SINK_ok'] += 1
        loc[task] = cnt
    metrics['error_localization_E_vs_SINK'] = loc

    # S2 on SINK-localized wrongs, per task (KANGMEI case study core)
    per_task_s2 = {}
    for task in ('MVR1', 'KANGMEI', 'ZEDA', 'ZIJING'):
        rows = [r for r in S if r['task'] == task]
        w = [r for r in rows if r['ds_answered'] and not r['ds_vok']]
        per_task_s2[task] = dict(
            answered_wrong=len(w),
            S2_on_wrong=sum(1 for r in w if r['S2_unsupported']),
            answered_correct=sum(1 for r in rows if r['ds_vok']),
            S2_on_correct=sum(1 for r in rows if r['ds_vok'] and r['S2_unsupported']))
    metrics['S2_SINK_per_task'] = per_task_s2

    km = [r for r in E if r['task'] == 'KANGMEI']
    metrics['KANGMEI_E_special'] = dict(
        n=len(km), ds_correct=sum(1 for r in km if r['ds_status'] == 'CORRECT'),
        ds_format_or_grounded=sum(1 for r in km if r['ds_status'] in ('FORMAT_DIFF', 'QUOTE_GROUNDED')),
        ds_semantic_error=sum(1 for r in km if r['ds_status'] == 'SEMANTIC_ERROR'),
        ds_no_match=sum(1 for r in km if r['ds_status'] == 'NO_MATCH'),
        S1_on_wrong=sum(1 for r in km if r['S1_disagree'] and r['tgt_wrong']),
        S1c_on_wrong=sum(1 for r in km if r['S1c_cross_ground'] and r['tgt_wrong']),
        S2_on_wrong=sum(1 for r in km if r['S2_unsupported'] and r['tgt_wrong']),
        wrong_total=sum(1 for r in km if r['tgt_wrong']))
    zj_e = [r for r in E if r['task'] == 'ZIJING']
    zj_contract = load_contract('ZIJING')
    zj_doc_text = Q1._norm(''.join(p.get('text', '') for d in zj_contract['source_pages'].values()
                                   for p in d.get('pages', {}).values()))
    gim = []
    for r in zj_e:
        if r['ds_status'] == 'NO_MATCH':
            gv = Q1._norm(r['gold'])
            gim.append(bool(gv) and gv in zj_doc_text)
    zj_s = [r for r in S if r['task'] == 'ZIJING']
    metrics['ZIJING_special'] = dict(
        E_level=dict(n=len(zj_e),
                     ds_semantic=sum(1 for r in zj_e if r['ds_status'] == 'SEMANTIC_ERROR'),
                     ds_no_match=sum(1 for r in zj_e if r['ds_status'] == 'NO_MATCH'),
                     ds_no_match_gold_in_docs=sum(gim),
                     S1_fire=sum(1 for r in zj_e if r['S1_disagree']),
                     S1c_fire=sum(1 for r in zj_e if r['S1c_cross_ground']),
                     S2_fire=sum(1 for r in zj_e if r['S2_unsupported'])),
        SINK_level=dict(n=len(zj_s), abstain_majority=sum(1 for r in zj_s if not r['ds_answered']),
                        S1_fire=sum(1 for r in zj_s if r['S1_disagree']),
                        S2_fire=sum(1 for r in zj_s if r['S2_unsupported'])))

    json.dump(dict(samples_E=E, samples_SINK=S, pairs_SINK=PS),
              open(f'{OUT}/CFL_STAGE1_SIGNALS.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(metrics, open(f'{OUT}/CFL_STAGE1_METRICS.json', 'w'), ensure_ascii=False, indent=1)

    from collections import Counter
    for rows, name in ((E, 'E'), (S, 'SINK'), (PS, 'SINK-pairs')):
        print(f"== {name}: {len(rows)} fact-samples; categories:",
              dict(sorted(Counter(r['category'] for r in rows).items())))
    print(json.dumps(metrics, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
