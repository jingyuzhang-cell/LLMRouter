#!/usr/bin/env python3
"""Build P2-C v1.1 contracts: add frozen per-slot `g11` scoring specs + repair evidence spans (G-4/G-5).

Invariants enforced (build aborts otherwise): Gold values, value_kind, critical flags, UNKNOWN set and N are
identical to the frozen source version; every scored slot's Gold value passes its own g11 value rule; every
scored slot has >= 1 evidence span in its support docs that passes g11 support. Spans are only ever ADDED
(original spans kept); an added span is a verbatim slice of the normalised source text, recorded with
`repair_of` (the original quote it extends) or `repair: sentence_search`.
Usage: p2c_g11_build.py MANIFEST OUT_LOG   (writes TASK_CONTRACT_<task>_v1.1.json, KJ -> v1.2)
"""
import hashlib, json, os, re, stat, sys
from pathlib import Path

sys.path.insert(0, '/root/research_outputs/static_pi/p2_confirm')
import p2c_scorer as S  # noqa: E402

GOLD = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
DRY = bool(os.environ.get('DRY'))
UNCHANGED = ['无变化', '零变化', '未变化', '没有变化', '不变', '一致']
CHANGE_WORDS = ['下调', '上调', '减少', '增加', '撤销', '调整为', '减为', '降为', '降至', '减至', '从轻', '加重', '有变化', '发生变化', '存在变化']
NR_WORDS = ['未再载明', '未载明', '未列明', '未列入', '未出现', '未提及', '没有载明', '没有记载', '未记载', '未再记载', '未包括', '未包含']
NR_FORBID = ['撤销', '免除', '免予', '免于', '不予处罚', '未处罚', '不处罚', '未被处罚', '不再处罚', '为0', '为零', '零元', '终罚0', '罚款0', '处以0', '豁免']
NOFENBIE = ['无分别', '没有分别', '未写分别', '缺少分别', '缺分别', '不含分别', '未含分别', '未使用分别', '未注明分别', '未载分别', '未用分别']
NEG_QUAL = ['不构成', '未构成', '不存在虚假', '未发现', '无违法', '不属于违法']

QUAL = {  # 违法行为定性类：2-4 项必要要素（每项为可接受的原文表述）
    ('KR_002072', 'F14'): [['出售子公司股权', '出售子公司'], ['关联交易']],
    ('BQ_600074', 'F11'): [['关联方'], ['关联交易'], ['未按规定披露', '未披露']],
    ('DG_002715', 'F16'): [['IPO', '首次公开发行'], ['虚假记载'], ['重大遗漏']],
    ('YS_300376', 'F12'): [['虚假贸易'], ['虚增营业收入', '虚增收入']],
    ('SW_000755', 'F9'): [['环境保护', '环保'], ['行政处罚', '排污超标'], ['不符', '不实', '虚假']],
    ('JG_300093', 'F14'): [['虚增营业收入', '虚增收入'], ['利息收入'], ['虚假记载']],
    ('JD_000922', 'F15'): [['业绩承诺'], ['财务调整', '调整安排', '财务处理'], ['虚假记载']],
    ('HZE_000693', 'F15'): [['关联方'], ['非经营性占用资金', '非经营性资金占用', '资金占用'], ['未披露', '未在相关年报中披露', '未按规定披露']],
    ('SK_002278', 'F11'): [['预开发票', '预开销售发票'], ['提前确认'], ['虚假记载']],
    ('JZ_002470', 'F16'): [['虚构贸易'], ['虚增收入', '虚增营业收入']],
    ('WL_300367', 'F10'): [['对外担保'], ['重大合同', '回购协议']],
    ('RY_002193', 'F16'): [['非经营性资金占用', '资金占用'], ['维信基金'], ['关联交易']],
    ('FH_002743', 'F10'): [['报告书'], ['中科视界'], ['虚假记载']],
    ('RSK_603803', 'F10'): [['专网通信'], ['自循环'], ['虚假记载']],
    ('WC_300089', 'F14'): [['2018年年度报告', '2018年年报', '2018年度报告'], ['虚增营业收入', '虚增收入'], ['虚假记载']],
    ('HZ_002122', 'F14'): [['徐茂栋'], ['关联关系']],
    ('FR_600781', 'F17'): [['2015'], ['2016'], ['虚假记载'], ['重大遗漏']],
    ('HW_600360', 'F18'): [['非经营性资金占用', '资金占用'], ['重大遗漏']],
    ('HY_002700', 'F13'): [['8000万'], ['担保'], ['资金占用', '占用']],
    ('HX_300427', 'F14'): [['2017'], ['2022'], ['虚假记载']],
    ('HX_300427', 'F15'): [['发行股份'], ['欺诈发行']],
    ('JB_600609', 'F12'): [['年度报告', '年报'], ['债券'], ['银行间'], ['未按规定及时披露', '未及时披露']],
}
ONEOFF = {  # 其余描述性命题：elements / forbidden / quote_any
    ('KR_002072', 'F13'): dict(elements=[['119号'], ['减免', '减轻']], forbidden=[], quote_any=['119']),
    ('DG_002715', 'F13'): dict(elements=[['逝世', '去世', '死亡'], ['不再追究', '不追究']], forbidden=['罚款'], quote_any=['王玉枢']),
    ('HX_300427', 'F11'): dict(elements=[['未披露', '没有披露', '未载明', '未列明', '未给出'], ['不同金额', '具体数字', '具体金额']],
                               forbidden=['告知书原文未', '原告知书未', '拟罚合计为', '不存在拟罚'], quote_any=['不同金额']),
    ('HW_600360', 'F12'): dict(elements=[['另行处理'], ['公告送达', '无法取得联系', '无法联系']], forbidden=NR_FORBID, quote_any=['另行处理']),
    ('SK_002278', 'F10'): dict(elements=[['申辩'], ['处罚幅度']], forbidden=['不予采纳'], quote_any=['申辩']),
    ('JZ_002470', 'F14'): dict(elements=[['禁入'], ['调整'], ['不影响', '未影响'], ['罚款']],
                               forbidden=['罚款下调', '罚款调整', '降低罚款', '减少罚款', '罚款减少'], quote_any=['调整']),
}
FACT_CORRECTIONS = {  # 冻结版 Gold 值与原文不符，经原文逐字核对后改正（正式修订，逐条入修订记录）
    ('GD_839680', 'F13'): dict(new='2025-06-13', doc='D1', quote='2025年6月13日,公司收到中国证券监督管理委员会深圳监管局下发的《行政处罚事先告知书》',
                               reason='冻结值2025-06-17为D1所载股票复牌日；原文载明2025年6月13日收到《行政处罚事先告知书》'),
    ('KJ_600806', 'F16'): dict(new='2017-11-14', doc='D1', quote='2017年11月14日,沈机集团昆明机床股份有限公司(本公司)',
                               reason='冻结值2017-11-16为D2所载告知书公告刊登日；D1原文载明2017年11月14日公司及28名当事人收到《行政处罚及市场禁入事先告知书》'),
}
D1_ONLY_BANS = {  # D2为处罚决定书、全文无禁入决定：命题限定为D1拟禁入，值不变，终局UNKNOWN（同凯瑞德F12/F21口径）
    ('KJ_600806', 'F20'): '限定为D1拟市场禁入措施；D2（【2018】9号处罚决定书）未载禁入决定，终局UNKNOWN，不得以D1推定终局',
    ('KJ_600806', 'F21'): '限定为D1拟市场禁入措施；D2（【2018】9号处罚决定书）未载禁入决定，终局UNKNOWN，不得以D1推定终局',
}
FINAL_PRED = ('行政处罚罚款金额', '单人行政处罚罚款金额', '罚款合计')


def names_of(subject):
    s = re.sub(r'[（(]([^）)]*)[）)]', r'、\1、', subject)
    out = []
    for part in re.split(r'[、，,；;]', s):
        part = re.sub(r'等\d+人$', '', part).strip()
        if part and not re.search(r'项|组$|^第', part) and part not in ('全部当事人', '全部处罚事项', '本案当事人', '本决定书载明的全部当事人', '当前D2转述文本载明的全部当事人'):
            out.append(part)
    return out


def alias_variants(contract, names):
    out = []
    for a in contract.get('entity_correspondence', {}).get('aliases', []):
        if a['canonical'] in names or any(n in a['canonical'] or a['canonical'] in n for n in names):
            out += [re.sub(r'（[^）]*）', '', v) for v in a['variants'] if v not in ('公司',)]
    return out


def make_spec(task, contract, f):
    rule, pred, val = f['grounding']['rule'], f['predicate'], str(f['value'])
    kind = {'amount': 'amount', 'penalty_line_sum': 'sum', 'date': 'date', 'doc_number': 'docno'}.get(rule)
    if rule == 'title_set':
        kind = 'text'
    if kind is None:
        kind = 'ban' if '禁入措施' in pred and '终局' not in pred and '调整' not in pred else 'text'
    allowed = list(f['allowed_citation_docs'])
    if '阶段变化' in pred or '条款表述' in pred or '披露情况' in pred:
        support = allowed
    elif '拟' in pred:
        support = ['D1']
    elif (kind in ('amount', 'sum') and pred.startswith(FINAL_PRED)) or (kind == 'ban' and pred.startswith('市场禁入措施')):
        support = ['D2']
    else:
        support = allowed
    if (task, f['fact_id']) in D1_ONLY_BANS:
        support = ['D1']
    g = dict(kind=kind, support_docs=support)
    if (task, f['fact_id']) in D1_ONLY_BANS:
        g['semantic'] = D1_ONLY_BANS[(task, f['fact_id'])]
    names = names_of(f['subject'])
    if kind == 'amount':
        g['subject_any'] = sorted(set(names + alias_variants(contract, names) + [x for x in (f['grounding'].get('subject_anchor'),) if x]))
        if not pred.startswith(FINAL_PRED) and '拟处罚' not in pred and '罚款' not in pred:
            pa = f['grounding'].get('predicate_anchor')
            g['subject_any'] = sorted(set(g['subject_any'] + ([pa] if pa else [])))
    elif kind == 'ban':
        d = S.durations(val)
        assert len(d) == 1, (task, f['fact_id'], val)
        g['duration'] = d.pop()
        g['subject_any'] = sorted(set(names + alias_variants(contract, names)))
    elif kind == 'date':
        g['precision'] = 'month' if len(val.split('-')) == 2 else 'day'
        if '调查' in pred or '立案' in pred:
            kw = ['调查通知书', '立案告知书', '立案']
        elif '告知书' in pred:
            kw = ['告知书']
        elif '决定书' in pred and '落款' not in pred:
            kw = ['决定书']
        elif '通知' in pred:
            kw = ['通知']
        elif '落款' in pred:
            kw = ['中国证券监督管理委员会']
        else:
            raise ValueError((task, f['fact_id'], pred))
        g['doc_kw_any'] = kw
    elif kind == 'text':
        key = (task, f['fact_id'])
        if rule == 'title_set':
            g.update(elements=[[val]], forbidden=[], quote_any=[val], subject_any=names)
        elif key in QUAL:
            g.update(elements=QUAL[key], forbidden=NEG_QUAL)
        elif key in ONEOFF:
            g.update(ONEOFF[key])
        elif '阶段变化' in pred:
            g.update(elements=[UNCHANGED, ['罚款', '处罚', '金额']], forbidden=CHANGE_WORDS, quote_any=['罚款'])
        elif pred == '拟处罚记录与D2载明情况':
            amt = re.search(r'(\d+(?:\.\d+)?)万', val).group(1)
            g.update(elements=[[f'{amt}万'], NR_WORDS], forbidden=NR_FORBID, quote_any=names)
        elif '条款表述' in pred:
            els = [NOFENBIE, ['D2', '决定书']]
            fb = []
            if (task, f['fact_id']) == ('SK_002278', 'F6'):
                els.append(['拆', '分列', '单列', '两项', '分开'])
                fb = ['下调', '降至', '减至', '减为', '降为']
            g.update(elements=els, forbidden=fb, quote_any=names)
        else:
            raise ValueError(('no text spec', task, f['fact_id'], pred))
    return g


def repair_spans(f, g, docs, contract, log, task):
    ok = [e for e in f['source_evidence'] if e['doc_id'] in g['support_docs'] and S.nt(e['quote']) in docs[e['doc_id']]
          and S.support_ok(f, g, e['quote'])]
    if ok:
        return
    meta = {d: contract['source_documents'][d]['pdf_sha256'] for d in docs}
    for e in f['source_evidence']:                       # 1) extend an existing span
        d = e['doc_id']
        if d not in g['support_docs']:
            continue
        q = S.nt(e['quote']); i = docs[d].find(q)
        if i < 0:
            continue
        for mode in ('forward', 'backward', 'both'):   # prefer extending past the end (keeps the span's own start)
            for L in range(1, 500):
                a, b = {'forward': (i, i + len(q) + L), 'backward': (max(0, i - L), i + len(q)),
                        'both': (max(0, i - L), i + len(q) + L)}[mode]
                cand = docs[d][a:b]
                if S.support_ok(f, g, cand):
                    f['source_evidence'].append(dict(doc_id=d, page=1, quote=cand, pdf_sha256=meta[d], repair_of=e['quote']))
                    log.append(dict(task=task, fact_id=f['fact_id'], doc=d, mode='extend_' + mode, old=e['quote'], new=cand))
                    return
    for d in g['support_docs']:                          # 2) shortest supporting sentence in a support doc
        sents = [s for s in re.split(r'(?<=[。；;])', docs[d]) if s]
        hits = sorted((s for s in sents if len(s) >= S.MIN_QUOTE_CHARS and S.support_ok(f, g, s)), key=len)
        if hits:
            cand = hits[0]
            f['source_evidence'].append(dict(doc_id=d, page=1, quote=cand, pdf_sha256=meta[d], repair='sentence_search'))
            log.append(dict(task=task, fact_id=f['fact_id'], doc=d, mode='sentence_search', old=None, new=cand))
            return
    raise RuntimeError(f'NO SUPPORTING SPAN: {task} {f["fact_id"]} {f["predicate"]} support_docs={g["support_docs"]}')


def main(manifest_path, log_path):
    man = json.loads(Path(manifest_path).read_text())
    log, results = [], []
    for r in man['contracts']:
        src = Path(r['file']); task = r['task']
        new_ver = 'v1.2' if r['version'] == 'v1.1' else 'v1.1'
        out = (Path(os.environ['DRY_DIR']) if DRY else GOLD) / f'TASK_CONTRACT_{task}_{new_ver}.json'
        if out.exists() and not DRY:
            sys.exit(f'REFUSE: {out} exists')
        c = json.loads(src.read_text()); orig = json.loads(src.read_text())
        docs = S.doc_index(c)
        for f in c['required_facts']:
            if f['status'] == 'GOLD_DRAFT_UNKNOWN':
                continue
            corr = FACT_CORRECTIONS.get((task, f['fact_id']))
            if corr:
                assert S.nt(corr['quote']) in docs[corr['doc']], ('correction quote not verbatim', task, f['fact_id'])
                f['value_corrected_from'] = f['value']; f['value'] = corr['new']; f['correction_reason'] = corr['reason']
                f['source_evidence'].append(dict(doc_id=corr['doc'], page=1, quote=corr['quote'],
                                                 pdf_sha256=c['source_documents'][corr['doc']]['pdf_sha256'], repair='fact_correction'))
                log.append(dict(task=task, fact_id=f['fact_id'], doc=corr['doc'], mode='FACT_CORRECTION',
                                old=f['value_corrected_from'], new=corr['new'], reason=corr['reason']))
            g = make_spec(task, c, f)
            f['g11'] = g
            assert S.value_ok(f, g, f['value']), ('gold fails own value rule', task, f['fact_id'], f['value'])
            repair_spans(f, g, docs, c, log, task)
            for e in f['source_evidence']:   # role: only spans that themselves support the slot count as support
                e['role'] = 'support' if (e['doc_id'] in g['support_docs'] and S.nt(e['quote']) in docs[e['doc_id']]
                                          and len(S.nt(e['quote'])) >= S.MIN_QUOTE_CHARS and S.support_ok(f, g, e['quote'])) else 'context'
            assert any(e['role'] == 'support' for e in f['source_evidence'])
        for a, b in zip(orig['required_facts'], c['required_facts']):
            for k in ('fact_id', 'value', 'value_kind', 'critical', 'status', 'subject', 'predicate', 'unit', 'allowed_citation_docs'):
                if k == 'value' and (task, a['fact_id']) in FACT_CORRECTIONS:
                    assert b['value_corrected_from'] == a['value']
                    continue
                assert a.get(k) == b.get(k), (task, a['fact_id'], k)
            assert [{k: v for k, v in e.items() if k != 'role'} for e in b['source_evidence'][:len(a['source_evidence'])]] == a['source_evidence'], (task, a['fact_id'], 'span removed/changed')
        assert c['critical_fact_ids'] == orig['critical_fact_ids'] and c['unknown_items'] == orig['unknown_items']
        c['contract_version'] = new_ver
        c['scoring'] = dict(c['scoring'], scorer='p2c_scorer.py (g11 per-slot specs)', N_excludes_unknown=True)
        corrs = [dict(fact_id=k[1], **v) for k, v in FACT_CORRECTIONS.items() if k[0] == task]
        c['revision'] = dict(supersedes=r['version'], supersedes_sha256=r['sha256'], date='2026-11-08',
                             basis='operator P2-C ruling: G-4 scoring-interface repair, G-5 evidence spans, text scheme A',
                             facts_changed=bool(corrs), fact_corrections=corrs,
                             semantic_restrictions=[dict(fact_id=k[1], note=v) for k, v in D1_ONLY_BANS.items() if k[0] == task],
                             n_spans_added=sum(1 for x in log if x['task'] == task and x['mode'] != 'FACT_CORRECTION'))
        body = (json.dumps(c, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
        out.write_bytes(body)
        if not DRY:
            os.chmod(out, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        sha = hashlib.sha256(body).hexdigest()
        results.append(dict(task=task, from_version=r['version'], from_sha256=r['sha256'], to_version=new_ver, file=str(out), to_sha256=sha))
        print(f'{task:11} {r["version"]}->{new_ver} spans_added={c["revision"]["n_spans_added"]:2} {sha[:16]}')
    Path(log_path).write_text(json.dumps(dict(span_repairs=log, contracts=results), ensure_ascii=False, indent=1) + '\n', 'utf-8')
    if DRY:
        print('DRY RUN: nothing written except log'); print('total span repairs:', len(log)); return
    with open('/root/research_outputs/static_pi/p2_confirm/P2C_GOLD_REVISIONS.jsonl', 'a') as fh:
        for x in results:
            fh.write(json.dumps(dict(date='2026-11-08', task=x['task'], from_version=x['from_version'], to_version=x['to_version'],
                                     from_sha256=x['from_sha256'], to_sha256=x['to_sha256'], kind='g11_specs_and_span_repair',
                                     facts_changed=any(k[0] == x['task'] for k in FACT_CORRECTIONS)), ensure_ascii=False) + '\n')
    print('total span repairs:', len(log))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
