"""Diagnostic semantic audit (NOT a scorer; never feeds back into any score).

Purpose: classify each frozen-scorer failure into
  - FORMAT_REJECTED : answer is materially consistent with the frozen gold
                      value but not lexically equal to it (symbolic gold token
                      or missing/extra prefix), so exact-match scoring rejects it
  - CONTRADICTION   : answer materially disagrees with gold (wrong number,
                      wrong subject, negation, substitutes another entity)
  - ABSENT          : slot not answered at all
Families are hand-written once and applied uniformly to all six arms; no
arm-specific tuning. Frozen terminal_quality output is carried alongside and
is never replaced by this classification.
"""
import json, statistics as st

FIDS = ['A1', 'A2', 'A3', 'A4', 'A5', 'B1', 'B2', 'B3', 'B3b', 'B4', 'C1', 'C2',
        'D_1', 'D_2', 'D_3', 'D_4', 'E1', 'E2', 'E3', 'F1', 'F2', 'F3', 'F4']


def n(x):
    return str(x if x is not None else '').replace(' ', '').replace('\u3000', '')


def _has_any(v, *keys):
    return any(k in v for k in keys)


def material(fid, gold, got):
    """True = materially consistent with gold; False = contradicts/absent; None = unclassifiable."""
    if got is None:
        return False
    g, v = n(gold), n(got)
    if fid in ('A1', 'A2'):
        return v.startswith('PERSON_ONLY_') and '俞发祥' in v and 'BOTH_' not in v and 'COMPANY_ONLY_' not in v
    if fid == 'A3':
        return v.startswith('BOTH_') and '王勇' in v
    if fid == 'A4':
        return v.startswith('COMPANY_ONLY_') and '纳川' in v
    if fid == 'A5':
        return _has_any(v, '无职务', '仅实际控制人', '均为实际控制人', '两家上市公司均为实际控制人') \
            and '董事长' not in v and '董事' not in v.replace('董事会', '')
    if fid in ('B1', 'B2', 'B4'):
        return '01120260037' in v or '0262026012' in v
    if fid == 'B3':
        return '0042026002' in v and '0042026003' in v
    if fid == 'B3b':
        return '0042026002' in v and '0042026003' in v and ('公司' in v and '王勇' in v)
    if fid == 'C1':
        return '2023年年报' in v and '信息披露违法违规' in v
    if fid == 'C2':
        return v.startswith('GENERIC_') and '未指明' not in v and '不可判定' not in v
    if fid == 'D_1':
        return v.startswith('SAME_PERSON') or (_has_any(v, '同一人', '同一自然人') and '不' not in v)
    if fid == 'D_2':
        return v.startswith('SAME_NOTICE_INSTANCE') or ('同一份' in v and _has_any(v, '告知书', '文书'))
    if fid == 'D_3':
        return v.startswith('SAME_RECEIPT_EVENT') or '同一收到事件' in v
    if fid == 'D_4':
        return v.startswith('DIFFERENT_COMPANY') or _has_any(v, '非同一公司', '不同公司', '两家不同')
    if fid == 'E1':
        return v.split('(')[0].split('（')[0] == '1'
    if fid == 'E2':
        return v.split('(')[0].split('（')[0] == '2'
    if fid == 'E3':
        return v.split('(')[0].split('（')[0] == '2' and '王勇' in v
    if fid in ('F1', 'F2', 'F3'):
        return g.replace('-', '') in v.replace('-', '').replace('年', '').replace('月', '').replace('日', '')
    if fid == 'F4':
        return '收到' in v and '同一' in v and '落款日' in v and _has_any(v, '不同', '差', '10-10', '10月10日')
    return None


def main():
    d = json.load(open('/root/research_outputs/static_pi/stage_d/v2/ATTRIBUTION_V2.json'))
    cells = d['cells']
    ARMS = ['Static-GLM', 'Static-DS', 'Retry-only', 'Z-only', 'pi-only', 'Joint']
    SCEN = ['S1', 'S1b']

    per_cell = {}
    for c in cells:
        rows = []
        for s in c['slots']:
            fid = s['fact_id']
            m = material(fid, s['gold_value'], s['got_value'])
            if not s['answered']:
                cls = 'ABSENT'
            elif s['value_correct']:
                cls = 'TP'
            elif m:
                cls = 'FORMAT_REJECTED'
            else:
                cls = 'CONTRADICTION'
            rows.append(dict(fact_id=fid, cls=cls, status=s['status'],
                             material=bool(m), value_correct=s['value_correct'],
                             evidence_ok=s['evidence_ok'],
                             loc=s['evidence_localization']['state'],
                             got=s['got_value'], gold=s['gold_value']))
        per_cell[(c['scenario'], c['repeat'], c['arm'])] = rows

    def counts(keys):
        agg = {}
        for k in keys:
            for r in per_cell[k]:
                a = agg.setdefault(r['fact_id'], {'TP': 0, 'FORMAT_REJECTED': 0, 'CONTRADICTION': 0, 'ABSENT': 0})
                a[r['cls']] += 1
        return agg

    arm_tbl = {}
    for arm in ARMS:
        keys = [(sc, rep, arm) for sc in SCEN for rep in (1, 2, 3)]
        agg = counts(keys)
        tot = {k: sum(v[k] for v in agg.values()) for k in ('TP', 'FORMAT_REJECTED', 'CONTRADICTION', 'ABSENT')}
        per_exec = []
        for k in keys:
            rows = per_cell[k]
            per_exec.append(dict(
                tp=sum(1 for r in rows if r['cls'] == 'TP'),
                material=sum(1 for r in rows if r['material']),
                evidence_ok=sum(1 for r in rows if r['evidence_ok']),
                absent=sum(1 for r in rows if r['cls'] == 'ABSENT'),
                format_rejected=sum(1 for r in rows if r['cls'] == 'FORMAT_REJECTED'),
            ))
        arm_tbl[arm] = dict(per_slot=agg, totals=tot, per_exec=per_exec,
                            tp_median=st.median([e['tp'] for e in per_exec]),
                            material_median=st.median([e['material'] for e in per_exec]),
                            evidence_median=st.median([e['evidence_ok'] for e in per_exec]),
                            material=dict(n=tot['TP'] + tot['FORMAT_REJECTED'],
                                          median=st.median([e['material'] for e in per_exec])),
                            material_rate=round((tot['TP'] + tot['FORMAT_REJECTED']) / 138, 4))

    # paired contrasts on MATERIAL correctness (diagnostic) and frozen TP
    def pair(a_arm, b_arm, field):
        ds = []
        for sc in SCEN:
            for rep in (1, 2, 3):
                ka = (sc, rep, a_arm)
                kb = (sc, rep, b_arm)
                fa = sum(1 for r in per_cell[ka] if r['material']) if field == 'material' else \
                    sum(1 for r in per_cell[ka] if r['cls'] == 'TP')
                fb = sum(1 for r in per_cell[kb] if r['material']) if field == 'material' else \
                    sum(1 for r in per_cell[kb] if r['cls'] == 'TP')
                ds.append(fa - fb)
        return dict(median_delta=st.median(ds), mean_delta=round(st.mean(ds), 3),
                    wins=sum(1 for x in ds if x > 0), ties=sum(1 for x in ds if x == 0),
                    losses=sum(1 for x in ds if x < 0), deltas=ds)

    contrasts = {}
    for a, b in (('Z-only', 'Retry-only'), ('Joint', 'pi-only'), ('Joint', 'Z-only'),
                 ('pi-only', 'Retry-only'), ('Z-only', 'Static-GLM'), ('Joint', 'Static-GLM')):
        contrasts[f'{a} - {b}'] = dict(
            material=pair(a, b, 'material'), tp=pair(a, b, 'tp'))

    out = dict(batch='PHASE_PI_V2_SEMANTIC_DIAGNOSTIC (not a scorer)',
               rules='hand-written per-slot families, applied uniformly to all arms',
               arms=arm_tbl, contrasts=contrasts,
               per_cell={f'{k[0]}|r{k[1]}|{k[2]}': v for k, v in per_cell.items()})
    json.dump(out, open('/root/research_outputs/static_pi/stage_d/v2/SEMANTIC_DIAGNOSTIC_V2.json', 'w'),
              ensure_ascii=False, indent=1)

    print('arm        TPmed  materialMed  evidMed  totals(TP/FR/CON/ABS)  material_rate')
    for arm in ARMS:
        t = arm_tbl[arm]['totals']
        print(f"{arm:11s} {arm_tbl[arm]['tp_median']:5} {arm_tbl[arm]['material_median']:11} "
              f"{arm_tbl[arm]['evidence_median']:8}   {t['TP']:2d}/{t['FORMAT_REJECTED']:2d}/{t['CONTRADICTION']:2d}/{t['ABSENT']:2d}"
              f"            {arm_tbl[arm]['material_rate']:.3f}")
    print('\npaired contrasts (material | frozen TP):')
    for k, v in contrasts.items():
        m, t = v['material'], v['tp']
        print(f"  {k:26s} material md={m['median_delta']:+.1f} W{m['wins']}/T{m['ties']}/L{m['losses']}"
              f"   TP md={t['median_delta']:+.1f} W{t['wins']}/T{t['ties']}/L{t['losses']}")


if __name__ == '__main__':
    main()
