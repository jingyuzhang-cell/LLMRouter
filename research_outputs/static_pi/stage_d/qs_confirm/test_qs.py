"""Offline checks for the Qianshan Gold, scorer and DAG inputs (zero model calls; network patched to fail)."""
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SD = HERE.parent
sys.path[:0] = [str(HERE), str(SD / 'sc_e1_1'), str(SD)]
for key in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY'):
    os.environ.pop(key, None)
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network attempted'))

import qs_scorer as Q  # noqa: E402
import detectors_v2 as D  # noqa: E402
import safety_metrics as S  # noqa: E402
import build_contract_qs as B  # noqa: E402

CT = Q.load_contract()
FACTS = {f['fact_id']: f for f in CT['required_facts']}
RES = []


def chk(name, cond, detail=''):
    RES.append(dict(name=name, ok=bool(cond), detail=str(detail)[:300]))
    print(f'  {name:<84} {"PASS" if cond else "FAIL"} {"" if cond else detail}')


def canon(fid):
    f = FACTS[fid]
    e = f['source_evidence'][0]
    value = f['value'] + (f.get('unit') or '') if f['value_kind'] == 'number' else f['value']
    return dict(fact_id=fid, value=value, doc=e['doc_id'], quote=e['quote'])


def status(fid, value=None, doc=None, quote=None):
    a = canon(fid)
    a.update({k: v for k, v in (('value', value), ('doc', doc), ('quote', quote)) if v is not None})
    return next(r for r in Q.score(dict(answers=[a]), CT)['rows'] if r['fact_id'] == fid)['status']


def gold_checks():
    print('G. Gold and contract')
    Q.verify_pins()
    chk('G1 contract is the pinned v1, 20 slots, 12 critical, approved', len(FACTS) == 20 and len(CT['critical_fact_ids']) == 12
        and CT['status'] == 'GOLD_APPROVED')
    draft = json.loads(Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/QS_300216/TASK_CONTRACT_QS_v1_DRAFT.json').read_text('utf-8'))
    chk('G1 v1 changes no Gold value or evidence quote relative to the reviewed draft',
        [(f['fact_id'], f['value'], [e['quote'] for e in f['source_evidence']]) for f in draft['required_facts']]
        == [(f['fact_id'], f['value'], [e['quote'] for e in f['source_evidence']]) for f in CT['required_facts']])
    chk('G1 F18 records required titles and the separate legal identity',
        FACTS['F18']['grounding']['required_titles'] == ['董事长', '总经理'] and FACTS['F18']['grounding']['additional_identity'] == '法定代表人')
    idx = Q.doc_index(CT)
    bad = [(f['fact_id'], e['doc_id']) for f in CT['required_facts'] for e in f['source_evidence']
           if Q.norm_text(e['quote']) not in idx[e['doc_id']]]
    chk('G2 every evidence quote is verbatim in its source document', not bad, bad)
    raw_ok = []
    for f in CT['required_facts']:
        for e in f['source_evidence']:
            raw = CT['source_pages'][e['doc_id']]['pages']['1']['text'][e['char_start']:e['char_end']]
            raw_ok.append(Q.norm_text(raw) == Q.norm_text(e['quote']))
    chk('G3 recorded char offsets reproduce each quote from the raw text', all(raw_ok))
    chk('G4 every evidence doc is in the slot whitelist', all(e['doc_id'] in f['allowed_citation_docs']
                                                              for f in CT['required_facts'] for e in f['source_evidence']))
    for d, src in CT['source_documents'].items():
        pdf = B.RAW / B.DOCS[d][0]
        chk(f'G5 {d} PDF and text hashes match the recorded source', hashlib.sha256(pdf.read_bytes()).hexdigest() == src['pdf_sha256']
            and hashlib.sha256(CT['source_pages'][d]['pages']['1']['text'].encode()).hexdigest() == src['text_sha256'])
    ec = CT['entity_correspondence']
    chk('G6 totals recompute from the source: final 14 parties 179, proposed 25 parties 320',
        ec['final_total_wan'] == 179 and ec['proposed_total_wan'] == 320 and len(ec['parties']) == 25
        and sum(p['final_wan'] is not None for p in ec['parties']) == 14 and FACTS['F19']['value'] == '179')
    chk('G7 entity correspondence: 11 parties not penalized at D2, 12 adjusted, 2 unchanged',
        [sum(p['change'] == c for p in ec['parties']) for c in ('not penalized in D2', 'adjusted', 'unchanged')] == [11, 12, 2])
    slot_text = ' '.join(f"{f['subject']} {f['predicate']}" for f in CT['required_facts'])
    leaks = [f['fact_id'] for f in CT['required_facts'] if f['value'] not in ('是',) and Q.norm_text(f['value']) in Q.norm_text(slot_text)]
    chk('G8 no Gold value appears in any slot subject or predicate shown to models', not leaks, leaks)


def scorer_checks():
    print('A. scorer')
    perfect = Q.score(dict(answers=[canon(f) for f in FACTS]), CT)
    chk('A1 gold self-test: 20 TP, Q_all = 1', perfect['tp'] == 20 and perfect['Q_all'] == 1.0,
        [(r['fact_id'], r['status']) for r in perfect['rows'] if r['status'] != 'TP'])
    traps = [('F2', '90万元'), ('F4', '20万元'), ('F5', '20万元'), ('F6', '5万元'), ('F7', '5万元'), ('F19', '320万元'),
             ('F19', '239万元'), ('F8', '9166.2万元'), ('F8', '9166.23亿元'), ('F9', '13246.90万元'), ('F10', '8974.36万元'),
             ('F10', '13733.16万元'), ('F11', '14.8%'), ('F12', '2019-11-29'), ('F13', '2020-08-06'), ('F14', '2020-01-08'),
             ('F15', '[2020]10号'), ('F16', '[2020]32号'), ('F17', '湘稽调查字0528号'), ('F18', '董事长'), ('F18', '董事长、副总经理'),
             ('F20', '否'), ('F20', '未触及'), ('F1', '拟60万元，终60万元以外另罚30万元'),
             ('F18', '法定代表人'), ('F18', '董事长、法定代表人'), ('F18', '法定代表人、总经理'), ('F8', '91,662,350元')]
    miss = [(f, v, status(f, v)) for f, v in traps if status(f, v) != 'VALUE_WRONG']
    chk(f'A2 {len(traps)} wrong values rejected, including every notice-stage amount', not miss, miss)
    rights = [('F1', 60), ('F1', '60万'), ('F1', '600,000元'), ('F2', '每人30万元'), ('F6', '4万元/人'), ('F8', '91,662,331.39元'),
              ('F8', '9,166.23万元'), ('F9', '116,561,038.31元'), ('F9', '11656.1万元'), ('F10', '224,358,974.36元'),
              ('F11', '14.83%'), ('F12', '2018年1月16日'), ('F13', '2019/11/29'), ('F14', '2020年8月6日'), ('F15', '【2020】32号'),
              ('F17', '处罚字【2019】149号'), ('F18', '董事长、法定代表人、总经理'), ('F18', '董事长兼总经理'), ('F19', '179'),
              ('F20', '是'), ('F20', '已触及重大违法强制退市情形'), ('F20', True),
              ('F18', '法定代表人、董事长、总经理'), ('F18', '董事长、总经理（法定代表人）'), ('F8', '91,662,250元')]
    miss = [(f, v, status(f, v)) for f, v in rights if status(f, v) != 'TP']
    chk(f'A3 {len(rights)} right values in other formats or units accepted', not miss, miss)
    d1_line = '（二）对刘祥华给予警告，并处以 90 万元罚款，其中作为直接负责的主管人员罚款\n30 万元'
    cases = [('notice-stage line cited for a final amount', 'F2', '30万元', 'D1', d1_line, 'LOC_WRONG'),
             ('same company line cited from the notice', 'F1', '60万元', 'D1', '（一）对千山药机责令改正，给予警告，并处以 60 万元罚款', 'LOC_WRONG'),
             ('fabricated quote', 'F8', '9166.23万元', 'D2', '千山药机虚增在建工程约九千万元', 'LOC_WRONG'),
             ('quote without the subject', 'F3', '30万元', 'D2', '并分别处以30万元的罚款', 'UNSUPPORTED'),
             ('verbatim but unrelated sentence', 'F10', '22435.90万元', 'D2', '对公司及相关当事人的《行政处罚决定书》（[2020]32号）', 'UNSUPPORTED'),
             ('2015 sentence for a 2016 slot', 'F9', '11656.10万元', 'D2', '虚减了应收账款13,246.90万元', 'UNSUPPORTED'),
             ('affirmation slot cited with a denial-free unrelated sentence', 'F20', '是', 'D1', '公司股票可能被实施重大违法强制退市', 'UNSUPPORTED')]
    for name, fid, v, d, q, want in cases:
        got = status(fid, v, d, q)
        chk(f'A4 evidence bar: {name} -> {want}', got == want, got)
    chk('A4 a D1 sentence is accepted where the whitelist allows it (F11)', status('F11', '14.83%', 'D1',
        '刘祥华担任千山药机董事长、法定代表人、总经理，是公司的实际控制人之一，持有公司股票 53,583,500 股，持股比例达 14.83%') == 'TP')
    zero = Q.score(dict(answers=[], unknown_slots=list(FACTS)), CT)
    m = S.metrics(zero)
    chk('A5 zero answers: Q_all 0, error rate undefined, safety gate never passes',
        zero['Q_all'] == 0.0 and m['error_rate'] is None and S.safety_gate(m, S.metrics(Q.score(dict(answers=[canon('F1')]), CT))) == 'UNDEFINED')
    tree = ast.parse((HERE / 'qs_scorer.py').read_text('utf-8'))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'score')
    chk('A6 scorer is arm-blind: score(sink, contract), no arm/condition/rep identifiers',
        [a.arg for a in fn.args.args] == ['sink', 'contract'] and not names & {'arm', 'condition', 'rep', 'trace', 'injected'})


def detector_checks():
    """Disclosures for review: how the frozen V2 detectors and base module behave on this task."""
    print('V. frozen detectors V2 on this task (disclosure, nothing changed)')
    slots = [dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'], **({'unit': f['unit']} if f.get('unit') else {}))
             for f in CT['required_facts']]
    types = {s['fact_id']: D.slot_type(s) for s in slots}
    expect = {**{f'F{i}': 'amount' for i in range(1, 12)}, 'F12': 'date', 'F13': 'date', 'F14': 'date', 'F15': 'doc_number',
              'F16': 'doc_number', 'F17': 'doc_number', 'F18': 'title', 'F19': 'derived', 'F20': 'negation'}
    chk('V1 V2 typing matches the scoring rule of every slot except F20 (affirmation typed as negation)', types == expect, types)
    rows = [dict(row='R1', doc='D1', label='x', quote=FACTS['F20']['source_evidence'][0]['quote'])]
    m3 = D.detect_m3(slots, dict(answers=[dict(fact_id='F20', value='是', doc='D1', quote=rows[0]['quote'])]), rows, dict(value=None))
    chk('V2 KNOWN LIMITATION: V2 M3 flags the correct F20 answer "是" (assumes 是否 answers are denials)',
        m3['F20']['state'] == 'SELF_EVIDENCE_INCONSISTENT', m3)
    e2_ok = dict(parties=[dict(name='湖南千山制药机械股份有限公司', penalty_amount='60万元'), dict(name='刘祥华', penalty_amount='30万元'),
                          dict(name='刘华山', penalty_amount='30万元'), dict(name='周大连', penalty_amount='15万元'),
                          dict(name='姜纯', penalty_amount='10万元')]
                 + [dict(name=n, penalty_amount='4万元') for n in ('钟波', '刘燕', '邓铁山', '王国华', '郑国胜', '彭勋德', '黄盛秋')]
                 + [dict(name=n, penalty_amount='3万元') for n in ('付慧龙', '金杰')])
    base = D.deterministic_total(e2_ok)
    chk('V3 base module on a clean decision extraction: 179 over 14 parties', base['value'] == '179万元' and base['parties'] == 14, base)
    alias = dict(parties=e2_ok['parties'] + [dict(name='千山药机', penalty_amount='60万元')])
    b2 = D.deterministic_total(alias)
    chk('V4 KNOWN LIMITATION: if the extraction lists the company under both names, the frozen base module double-counts (239)',
        b2['value'] == '239万元', b2)


def independence_checks():
    print('I. independence of event-specific strings (working tree, git HEAD, git history)')
    terms = ['千山药机', '千山制药', '华冠花炮', '中苋生态', '春华建筑', '千山慢病', '经沣财务', '湘稽调查字0528', '处罚字[2019]149号',
             '刘祥华', '刘华山', '周大连', '管新和', '刘件民']
    roots = ['/root/research_outputs', '/root/capital_opinion_pilot', '/root/r3_own_pool', '/root/cap_eval_bench_v1',
             '/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE', '/root/q_foundation', '/root/phase_c9_0', '/root/phase_e5_unified', '/root/.worktrees']
    excl = ['--exclude-dir=.git', '--exclude-dir=independent_case_search', '--exclude-dir=qs_confirm', '--exclude-dir=QS_300216']
    # Exposure means use before the case was selected, or any model-call ledger at any time. Files written after
    # selection (plans, tests and their results that name the case) are reported, not counted as exposure.
    audit_log = SD / 'independent_case_search' / 'AUDIT_LOG.json'
    cutoff = os.path.getmtime(audit_log)
    hits, post_selection_docs = {}, {}
    for t in terms:
        tree = subprocess.run(['grep', '-rlsF', *excl, t, *roots], capture_output=True, text=True).stdout.split()
        head = subprocess.run(['git', '-C', '/root', 'grep', '-lF', t, 'HEAD'], capture_output=True, text=True, errors='replace').stdout.split()
        hist = subprocess.run(['git', '-C', '/root', 'log', '--all', '--format=%h', '-F', '-S', t], capture_output=True, text=True,
                              timeout=900).stdout.split()
        late_docs = [f for f in tree if os.path.getmtime(f) > cutoff and not f.endswith('.jsonl') and 'ledger' not in f.lower()]
        exposure = [f for f in tree if f not in late_docs]
        if late_docs:
            post_selection_docs[t] = late_docs
        if exposure or head or hist:
            hits[t] = dict(tree=exposure[:3], head=head[:3], history=hist[:3])
    chk(f'I1 {len(terms)} event-specific strings: no pre-selection use, no run artefact, nothing in git', not hits, hits)
    print(f'     post-selection files naming the case (reported, not exposure): '
          f'{sorted({f for v in post_selection_docs.values() for f in v})}')
    return terms, dict(exposure=hits, post_selection_docs=post_selection_docs, cutoff_mtime=cutoff)


def main():
    gold_checks()
    scorer_checks()
    detector_checks()
    terms, hits = independence_checks()
    files = [B.RAW / B.DOCS['D1'][0], B.RAW / (B.DOCS['D1'][0] + '.txt'), B.RAW / B.DOCS['D2'][0], B.RAW / (B.DOCS['D2'][0] + '.txt'),
             Q.CONTRACT_PATH, HERE / 'build_contract_qs.py', HERE / 'qs_scorer.py', HERE / 'dag_qs.json', HERE / 'test_qs.py',
             SD / 'sc_e1_1' / 'detectors_v2.py', SD / 'sc_e1_1' / 'safety_metrics.py', SD / 'sc_e1_1' / 'sc_e1_scorer.py']
    manifest = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.exists()}
    passed = sum(r['ok'] for r in RES)
    out = dict(passed=passed, total=len(RES), results=RES, independence_terms=terms, independence_hits=hits, sha256=manifest)
    (HERE / 'QS_SELFTEST.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), 'utf-8')
    print(f'\n{passed}/{len(RES)} passed')
    sys.exit(0 if passed == len(RES) else 1)


if __name__ == '__main__':
    main()
