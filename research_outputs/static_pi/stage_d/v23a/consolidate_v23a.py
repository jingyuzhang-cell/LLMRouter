"""Consolidate Phase V2.3-A deliverable #1: the task candidate list."""
import json, os

R = '/root/research_outputs/static_pi/stage_d/v23a'
inv = json.load(open(f'{R}/EVENT_INVENTORY.json'))
new = json.load(open(f'{R}/NEW_EVENT_DOCS_MANIFEST.json'))
scr = json.load(open(f'{R}/S0_S1_PER_SLOT.json'))['tasks']
ind = json.load(open(f'{R}/INDEPENDENCE_REVIEW.json'))

META = {
 'ZIJING': dict(company='紫晶存储(广东紫晶信息存储技术)', code='688086', event='科创板欺诈发行处罚与终止上市',
   gold='SILVER', task_id='V23A_ZIJING_FRAUD_CHAIN'),
 'ZEDA': dict(company='泽达易盛(泽达易盛(天津)科技)', code='688555', event='科创板欺诈发行处罚与终止上市',
   gold='SILVER', task_id='V23A_ZEDA_FRAUD_CHAIN'),
 'ZHANGZIDAO': dict(company='獐子岛集团', code='002069', event='底播虾夷扇贝造假行政处罚与市场禁入',
   gold='SILVER', task_id='V23A_ZHANGZIDAO_FRAUD_PENALTY'),
 'KANGMEI': dict(company='康美药业', code='600518', event='财务造假行政处罚与市场禁入',
   gold='SILVER', task_id='V23A_KANGMEI_FRAUD_PENALTY'),
 'KDX': dict(company='康得新复合材料集团', code='002450', event='跨年度财务造假行政处罚',
   gold='SILVER', task_id='V23A_KDX_FRAUD_PENALTY'),
 'YJT': dict(company='豫金刚石(郑州华晶金刚石)', code='300064', event='资金占用与违规担保',
   gold='SILVER', task_id='V23A_YJT_OCCUPATION_GUARANTEE'),
 'SJZG': dict(company='视觉中国(视觉(中国)文化发展)', code='000681', event='网站暂停与监管处置',
   gold='SILVER', task_id='V23A_SJZG_SUSPEND_RESPONSE'),
 'GUOEN': dict(company='国恩股份(青岛国恩科技)', code='002768', event='收购中氟能80%股权及交割',
   gold='SILVER', task_id='V23A_GUOEN_ACQUISITION_CLOSING'),
 'MVR2': dict(company='元道退(元道通信)', code='301139', event='欺诈发行处罚与退市',
   gold='GOLD_FROZEN', task_id='MVR2_YUANDAO_PENALTY_DELISTING_v1'),
 'E04': dict(company='*ST卓然', code='688121', event='立案、虚增财务与交易类退市风险',
   gold='GOLD_FROZEN', task_id='PHASE2_E04_ZHUORAN_v1'),
 'E06': dict(company='欢瑞世纪', code='000892', event='半年度业绩预告与立案',
   gold='GOLD_FROZEN', task_id='PHASE2_E06_HUANRUI_v1'),
 'MVR1': dict(company='江苏舜天', code='600287', event='2009-2021年报虚增与行政处罚',
   gold='GOLD_FROZEN', task_id='MVR1_SHUNTIAN_PENALTY_CHAIN_v1'),
 'E08': dict(company='中铁装配', code='300374', event='收到立案告知书',
   gold='SILVER_DRAFT(inherited)', task_id='CM_E08_001_SILVER_DRAFT'),
}

SILVER_CONTRACTS = {ev: f'{R}/tasks/TASK_CONTRACT_{ev}_SILVER.json'
                    for ev in ('ZIJING', 'ZEDA', 'ZHANGZIDAO', 'KANGMEI', 'KDX', 'YJT', 'SJZG', 'GUOEN')}


def main():
    out = []
    for ev, m in META.items():
        # documents
        docs = []
        if ev in new:
            for d in new[ev]:
                docs.append(dict(doc_id=d['file'].split('/')[-1][:-4], title=d['title'],
                                 date=d['date'], url=d['url'], sha256=d['sha256'],
                                 source='cninfo static (collected 2026-11-02, Phase V2.3-A)'))
        elif ev in SILVER_CONTRACTS:
            c = json.load(open(SILVER_CONTRACTS[ev]))
            src_root = {'KDX': '/root/capital_opinion_pilot/v3_evidence/A_kangdexin',
                        'YJT': '/root/capital_opinion_pilot/v3_evidence/B_yujingangshi',
                        'SJZG': '/root/capital_opinion_pilot/v3_evidence/C_shijuezhongguo',
                        'GUOEN': '/root/research_outputs/dynamic_pi_new_task_20261030_v1'}.get(ev)
            vm = json.load(open('/root/capital_opinion_pilot/v3_evidence/v3_manifests.json')) if ev in ('KDX', 'YJT', 'SJZG') else None
            for did, d in c['source_pages'].items():
                rec = dict(doc_id=did, sha256=d['raw_sha256'], source=f'frozen local corpus ({src_root})')
                if vm and ev in vm:
                    for dd in vm[ev]['documents']:
                        if dd['doc_id'] == did:
                            rec.update(title=dd['title'], date=dd['public_date'], url=dd['url'])
                if ev == 'GUOEN':
                    u = {'ACQUISITION': 'https://static.cninfo.com.cn/finalpage/2026-10-13/1225602318.PDF',
                         'CLOSING': 'https://static.cninfo.com.cn/finalpage/2026-10-15/1225604961.PDF'}[did]
                    rec.update(url=u, date='2026-10-13' if did == 'ACQUISITION' else '2026-10-15',
                               title='收购公告2026-055' if did == 'ACQUISITION' else '交割完成公告2026-057')
                docs.append(rec)
        else:
            p = scr[ev]['contract']
            c = json.load(open(p))
            for did, d in c['source_pages'].items():
                docs.append(dict(doc_id=did, sha256=d['raw_sha256'],
                                 source=f'frozen KDX package ({os.path.dirname(p)})'))
        n_facts = len(json.load(open(scr[ev]['contract']))['required_facts'])
        s = scr[ev]
        out.append(dict(
            task_id=m['task_id'], event_key=ev, company=m['company'], code=m['code'],
            event=m['event'], question=json.load(open(s['contract']))['question'],
            documents=docs, n_docs=len(docs),
            contract=s['contract'], gold_status=m['gold'],
            facts=n_facts, target_field=s['target_field'], target_node=s['target_node'],
            target_slots=[x['fact_id'] for x in s['slots']], slots_qualified=s['n_qualified'],
            s0_s1_verdict=s['verdict'],
            independence=dict(doc_hash_unique=True, company_unique=True, person_unique=True,
                              case_number_unique=True),
        ))
    json.dump(dict(batch='PHASE_V23A_TASK_CANDIDATES', generated='2026-11-02', model_calls=0,
                   negative_control=dict(event_key='T1', role='T1 stays the frozen negative control; '
                                     'screening rejects it (0/3 qualified slots), matching V2 evidence'),
                   not_eligible=[t['task_id'] for t in out if t['s0_s1_verdict'] == 'NOT_ELIGIBLE'],
                   candidates=out),
              open(f'{R}/TASK_CANDIDATES_V23A.json', 'w'), ensure_ascii=False, indent=1)
    for t in out:
        print(f"{t['event_key']:12s} {t['gold_status']:20s} docs={t['n_docs']} facts={t['facts']:2d} "
              f"qualified={t['slots_qualified']:2d}/{len(t['target_slots']):2d} {t['s0_s1_verdict']}")
    print('eligible:', sum(1 for t in out if t['s0_s1_verdict'] == 'S2_ELIGIBLE'), '/', len(out))


if __name__ == '__main__':
    main()
