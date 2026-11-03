"""Task 2 (revised): silver facts via program-authored candidates + AI cross-verification.

The first attempt used two GLM-5.3 extraction calls; both hit the max_tokens cap
and returned truncated JSON (8043 tokens spent, 0 usable facts — kept in the ledger
as failed attempts). Revision: candidates are authored deterministically from the
evidence text with verbatim quotes, then verified by (a) deterministic grounding
checks against the FULL document text and (b) one independent GLM-5.3-Flash call.
Silver labels only — NOT human-confirmed gold.
"""
import json
import re

from pilot_common import PILOT_DIR, Meter, fenced_json, norm, all_dates

CUTOFF = '2024-07-10'
TXT = PILOT_DIR / 'evidence' / 'text'
FULL = {d: ''.join((TXT / f'{d}.txt').read_text().split()) for d in
        ['csrc_penalty_2024_41', 'st_announce_2024_020', 'st_announce_2024_021', 'st_advance_notice_2023']}
EXCERPTS = json.loads((PILOT_DIR / 'evidence' / 'excerpts.json').read_text())
DOC_TITLES = {
    'csrc_penalty_2024_41': '证监会行政处罚决定书〔2024〕41号（签发2024-04-24，网站发布2024-04-25）',
    'st_announce_2024_020': '江苏舜天临2024-020公告（2024-07-06）',
    'st_announce_2024_021': '江苏舜天临2024-021公告（2024-07-06）',
    'st_advance_notice_2023': '江苏舜天临2023-039公告·行政处罚事先告知（2023-07-03上海证券报电子版）',
}
PUBLIC_DATE = {'csrc_penalty_2024_41': '2024-04-25', 'st_announce_2024_020': '2024-07-06',
               'st_announce_2024_021': '2024-07-06', 'st_advance_notice_2023': '2023-07-03'}

# Candidates authored from the evidence text (quotes verbatim; see deterministic grounding below).
CANDIDATES = [
    ('date', '公司收到证监会《立案告知书》的日期是哪一天？', '2022-11-04', 'st_announce_2024_020',
     '于2022年11月4日收到中国证券监督管理委员会下发的《立案告知书》'),
    ('date', '公司收到《行政处罚及市场禁入事先告知书》（处罚字〔2023〕37号）的日期是哪一天？', '2023-06-30',
     'st_advance_notice_2023', '2023年6月30日，公司收到中国证券监督管理委员会出具的《行政处罚及市场禁入事先告知书》'),
    ('date', '证监会行政处罚决定书〔2024〕41号的落款（签发）日期是哪一天？', '2024-04-24',
     'csrc_penalty_2024_41', '中国证监会2024年4月24日'),
    ('amount', '处罚决定书对江苏舜天股份有限公司处以的罚款金额是多少？', '1,000万元', 'csrc_penalty_2024_41',
     '对江苏舜天股份有限公司责令改正,给予警告,并处以1,000万元罚款'),
    ('amount', '2009年至2021年年度报告共计虚增营业收入的金额是多少？', '10,333,448,392.98元',
     'csrc_penalty_2024_41', '2009年至2021年年度报告共计虚增营业收入10,333,448,392.98元'),
    ('text', '江苏舜天参与的专网通信业务被认定为何种性质的违法业务？', '隋某力主导的专网通信虚假自循环业务，无商业实质',
     'csrc_penalty_2024_41', '实质是合同、资金、票据流转构成闭环的虚假自循环业务,无商业实质'),
    ('date', '公司股票实施其他风险警示前的停牌日期是哪一天？', '2024-07-08', 'st_announce_2024_021',
     '停牌日期为2024年7月8日'),
    ('date', '公司股票实施其他风险警示的起始日期是哪一天？', '2024-07-09', 'st_announce_2024_021',
     '实施其他风险警示的起始日：2024年7月9日'),
    ('text', '实施其他风险警示后，公司A股股票简称变更为什麼？', 'ST舜天', 'st_announce_2024_021',
     'A股股票简称由“江苏舜天”变更为“ST舜天”'),
    ('amount', '实施其他风险警示后股票价格的日涨跌幅限制是多少？', '5%', 'st_announce_2024_021',
     '实施其他风险警示后股票价格的日涨跌幅限制为5%'),
]


def deterministic_checks(fact):
    problems = []
    doc = fact['evidence_doc']
    quote_ok_full = norm(fact['quote']) in norm(FULL[doc]) if doc in FULL else False
    quote_ok_excerpt = norm(fact['quote']) in norm(EXCERPTS[doc]['excerpt']) if doc in EXCERPTS else False
    if not quote_ok_full:
        problems.append('quote_not_in_full_evidence_text')
    ans = fact['answer']
    if not ans or len(ans) > 120:
        problems.append('answer_invalid')
    for d in all_dates(str(ans)):
        if d > CUTOFF:
            problems.append('answer_date_after_cutoff')
    if PUBLIC_DATE.get(doc, '9999-99-99') > CUTOFF:
        problems.append('evidence_public_after_cutoff')
    return {'quote_grounded_full_text': quote_ok_full, 'quote_grounded_excerpt': quote_ok_excerpt,
            'problems': problems, 'pass': not problems}


def main():
    meter = Meter()
    facts = []
    for i, (typ, q, a, doc, quote) in enumerate(CANDIDATES):
        facts.append({'fact_id': f'F{i+1}', 'answer_type': typ, 'question': q, 'answer': a,
                      'evidence_doc': doc, 'quote': quote, 'public_date': PUBLIC_DATE[doc],
                      'evidence_title': DOC_TITLES[doc]})
    for f in facts:
        f['deterministic_check'] = deterministic_checks(f)

    # independent cross-model verification (one Flash call)
    short = [{'fact_id': f['fact_id'], 'question': f['question'], 'answer': f['answer'],
              'evidence_doc': f['evidence_doc'], 'quote': f['quote']} for f in facts]
    digest = '\n\n'.join(f'【材料 doc_id={d}】\n{EXCERPTS[d]["excerpt"][:1100]}'
                         for d in ['csrc_penalty_2024_41', 'st_announce_2024_020',
                                   'st_announce_2024_021', 'st_advance_notice_2023'])
    rec, txt = meter.call(
        'glm53flash',
        '你是独立事实核验员。给你候选事实和原始材料摘录。只输出JSON：'
        '{"results":[{"fact_id":"F1","verdict":"SUPPORTED|UNSUPPORTED|WRONG_VALUE",'
        '"corrected_answer":null,"note":"<=25字"}]}。逐条判断answer是否被quote与材料精确支持（日期、金额、名称必须一致）。',
        '候选事实：\n' + json.dumps(short, ensure_ascii=False) + '\n\n材料摘录：\n' + digest,
        max_tokens=560, purpose='facts_independent_verification')
    verdicts = {}
    try:
        for r in fenced_json(txt).get('results', []):
            verdicts[r.get('fact_id')] = r
    except Exception as e:
        verdicts = {'_parse_error': str(e)}

    for f in facts:
        v = verdicts.get(f['fact_id'], {})
        f['independent_ai_verification'] = {'model': 'GLM-5.3-Flash', 'verdict': v.get('verdict', 'NOT_REACHED'),
                                            'corrected_answer': v.get('corrected_answer'), 'note': v.get('note'),
                                            'call_id': rec['call_id']}
        if f['deterministic_check']['pass'] and v.get('verdict') == 'SUPPORTED':
            f['verification_status'] = 'verified'
        elif f['deterministic_check']['pass'] and v.get('verdict') == 'WRONG_VALUE' and v.get('corrected_answer'):
            cand = dict(f)
            cand['answer'] = v['corrected_answer']
            f['answer'] = v['corrected_answer'] if deterministic_checks(cand)['pass'] else f['answer']
            f['verification_status'] = 'verified_corrected' if deterministic_checks(cand)['pass'] else 'unresolved'
        else:
            f['verification_status'] = 'unresolved'

    verified = [f for f in facts if f['verification_status'].startswith('verified')]
    out = {
        'event': '江苏舜天(600287)信息披露违法违规事件', 'information_cutoff': CUTOFF,
        'label_type': 'silver_auto_verified (deterministic grounding + cross-model AI check; NOT human gold)',
        'method': {
            'candidate_authoring': 'program-authored from evidence full text with verbatim quotes '
                                   '(revision after 2 truncated model-extraction calls, see model_call_ledger call_id 1-2)',
            'deterministic_checks': ['quote_grounded_in_full_evidence_text', 'answer_format',
                                     'answer_dates<=cutoff', 'evidence_public_date<=cutoff'],
            'independent_verification': 'GLM-5.3-Flash verdict against excerpts (call_id %d)' % rec['call_id']},
        'counts': {'candidates': len(facts), 'verified': len(verified), 'unresolved': len(facts) - len(verified)},
        'facts': facts,
    }
    (PILOT_DIR / 'facts_silver.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"facts: candidates={len(facts)} verified={len(verified)}")
    for f in facts:
        print(f"  {f['fact_id']} [{f['verification_status']}] det={f['deterministic_check']['pass']} "
              f"ai={f['independent_ai_verification']['verdict']} {f['question'][:30]} -> {str(f['answer'])[:40]}")
    print('meter:', json.dumps(meter.summary(), ensure_ascii=False))


if __name__ == '__main__':
    main()
