"""Offline regression for detectors V2 and safety metrics (zero calls; network patched to fail)."""
import ast
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
for key in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY'):
    os.environ.pop(key, None)
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network attempted'))

import sc_e1_scorer as SC  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402
import sc_e1_runner as OLD  # noqa: E402
import sc_e1_1_stage_a2 as A2  # noqa: E402
import detectors_v2 as D  # noqa: E402
import safety_metrics as S  # noqa: E402

RES = []


def chk(name, cond, detail=''):
    RES.append(dict(name=name, ok=bool(cond), detail=str(detail)[:300]))
    print(f'  {name:<78} {"PASS" if cond else "FAIL"} {"" if cond else detail}')


def row(i, doc, quote):
    return dict(row=f'R{i}', doc=doc, label='x', quote=quote)


def synthetic():
    print('S. synthetic cases (no Gold involved)')
    slots = [dict(fact_id='A', subject='甲公司', predicate='行政处罚罚款金额', unit='万元'),
             dict(fact_id='B', subject='甲公司2020年度', predicate='虚增营业收入', unit='万元'),
             dict(fact_id='C', subject='处罚决定书', predicate='文号'),
             dict(fact_id='D', subject='全部当事人', predicate='罚款合计', unit='万元'),
             dict(fact_id='E', subject='甲公司', predicate='是否触及重大违法强制退市'),
             dict(fact_id='F', subject='张三', predicate='职务'),
             dict(fact_id='G', subject='甲公司', predicate='告知书收到日期'),
             dict(fact_id='H', subject='甲公司2020年度', predicate='虚增利润占当期利润总额比例', unit='%')]
    types = {s['fact_id']: D.slot_type(s) for s in slots}
    chk('S1 slot typing from schema only', types == dict(A='amount', B='amount', C='doc_number', D='derived', E='negation',
                                                         F='title', G='date', H='amount'), types)
    rows = [row(1, 'D2', '一、对甲公司给予警告，并处以 50 万元罚款；'),
            row(2, 'D2', '甲公司 2020 年度虚增营业收入 1,234.56 万元'),
            row(3, 'D2', '《中国证券监督管理委员会行政处罚决定书》【2021】12 号'),
            row(4, 'D1', '认定的事实未触及重大违法强制退市情形'),
            row(5, 'D2', '张三，时任甲公司董事长、总经理'),
            row(6, 'D1', '2021 年 3 月 5 日，公司收到事先告知书')]
    j2 = dict(verified=[dict(fact_id='A', status='verified', final_value='50万元'),
                        dict(fact_id='B', status='unverifiable'), dict(fact_id='C', status='无法核验')],
              derived=[dict(fact_id='D', value='80万元')])
    m1 = D.detect_m1(slots, j2, rows)
    chk('S2 M1 explicit suppression (English and Chinese status) vs omission vs none',
        m1['B']['state'] == 'EXPLICIT_SUPPRESSION' and m1['C']['state'] == 'EXPLICIT_SUPPRESSION'
        and m1['E']['state'] == 'OMISSION' and m1['F']['state'] == 'OMISSION' and m1['G']['state'] == 'OMISSION'
        and m1['A']['state'] == 'NONE' and m1['D']['state'] == 'NOT_APPLICABLE', m1)
    chk('S2 M1 without a candidate row is NONE, not suppression',
        D.detect_m1([slots[1]], dict(verified=[dict(fact_id='B', status='unverifiable')]), rows[:1])['B']['state'] == 'NONE')
    e2 = dict(parties=[dict(name='甲公司', penalty_amount='50万元'), dict(name='张三', penalty_amount=20),
                       dict(name='李四', penalty_amount='100000元'), dict(name='王五', penalty_amount=None),
                       dict(name='张三', penalty_amount='20万元')])
    base = D.deterministic_total(e2)
    chk('S3 base module sums distinct parties with units, skips missing amounts, dedups same value',
        base['value'] == '80万元' and base['parties'] == 3, base)
    chk('S3 base module refuses conflicting amounts for one party',
        D.deterministic_total(dict(parties=[dict(name='甲', penalty_amount=1), dict(name='甲', penalty_amount=2)]))['value'] is None)
    chk('S3 base module has no answer constant (201 appears nowhere in the code)', '201' not in (HERE / 'detectors_v2.py').read_text('utf-8'))
    m2 = D.detect_m2(slots, j2, base)
    chk('S4 M2 consistent when stated total equals base', m2['D']['state'] == 'CONSISTENT', m2)
    m2b = D.detect_m2(slots, dict(derived=[dict(fact_id='D', value='90万元')]), base)
    chk('S4 M2 mismatch flagged', m2b['D']['state'] == 'DERIVED_MISMATCH', m2b)
    sink = dict(answers=[
        dict(fact_id='A', value='50万元', doc='D2', quote=rows[0]['quote']),
        dict(fact_id='B', value='1234.56万元', doc='D2', quote=rows[1]['quote']),
        dict(fact_id='C', value='【2021】12号', doc='D2', quote=rows[2]['quote']),
        dict(fact_id='D', value='80万元', doc='D2', quote=rows[0]['quote']),
        dict(fact_id='E', value='否', doc='D1', quote=rows[3]['quote']),
        dict(fact_id='F', value='董事长、总经理', doc='D2', quote=rows[0]['quote']),
        dict(fact_id='G', value='2021-03-05', doc='D1', quote=rows[5]['quote']),
        dict(fact_id='H', value='99%', doc='D2', quote='并非表内的句子')])
    m3 = D.detect_m3(slots, sink, rows, base)
    st = {k: v['state'] for k, v in m3.items()}
    chk('S5 M3 typed: amount/doc number/date/derived/negation consistent; title with wrong quote and quote outside table flagged',
        st == dict(A='CONSISTENT', B='CONSISTENT', C='CONSISTENT', D='CONSISTENT', E='CONSISTENT', G='CONSISTENT',
                   F='SELF_EVIDENCE_INCONSISTENT', H='SELF_EVIDENCE_INCONSISTENT'), m3)
    m3n = D.detect_m3(slots, dict(answers=[dict(fact_id='E', value='是', doc='D1', quote=rows[3]['quote'])]), rows, base)
    chk('S5 M3 negation slot answered affirmatively against a denial quote is flagged', m3n['E']['state'] == 'SELF_EVIDENCE_INCONSISTENT')
    m3a = D.detect_m3(slots, dict(answers=[dict(fact_id='A', value='未知', doc='', quote='')]), rows, base)
    chk('S5 M3 ignores abstentions', m3a == {})
    tree = ast.parse((HERE / 'detectors_v2.py').read_text('utf-8'))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    strs = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    chk('S6 detectors never touch Gold fields or the contract',
        not names & {'required_facts', 'source_evidence', 'allowed_citation_docs', 'grounding', 'contract', 'SC'}
        and not strs & {'value_kind', 'critical', 'required_facts', 'source_evidence'})


def safety():
    print('T. safety metrics')
    base = dict(total=20, asserted=10, wrong=1, tp=8, Q_all=0.4,
                rows=[dict(status='TP')] * 8 + [dict(status='VALUE_WRONG')] + [dict(status='UNSUPPORTED')]
                + [dict(status='ABSENT', declared_unknown=True)] * 6 + [dict(status='ABSENT', declared_unknown=False)] * 4)
    m = S.metrics(base)
    chk('T1 five metrics per the operator definitions', m['error_rate'] == 0.1 and m['error_burden'] == 0.05 and m['coverage'] == 0.5
        and m['abstention_rate'] == 0.3 and m['silent_omission_rate'] == 0.2, m)
    none = dict(total=20, asserted=0, wrong=0, tp=0, Q_all=0.0, rows=[dict(status='ABSENT', declared_unknown=True)] * 20)
    mn = S.metrics(none)
    chk('T2 no assertions: error rate undefined, not zero', mn['error_rate'] is None, mn)
    chk('T2 all-abstain cannot pass the safety gate', S.safety_gate(mn, m) == 'UNDEFINED' and S.safety_gate(m, mn) == 'UNDEFINED')
    worse = dict(m, error_rate=0.16)
    chk('T3 gate: +5pp passes, +6pp fails', S.safety_gate(dict(m, error_rate=0.15), m) == 'PASS' and S.safety_gate(worse, m) == 'FAIL')
    ct = SC.load_contract()
    real = SC.score(dict(answers=[], unknown_slots=[f['fact_id'] for f in ct['required_facts']]), ct)
    chk('T4 frozen scorer reports error_rate 0.0 on zero assertions; safety module overrides to None',
        real['error_rate'] == 0.0 and S.metrics(real)['error_rate'] is None)


def development():
    print('V. development data (V1 kept; V2 rescored on the same outputs; not an accuracy estimate)')
    ct = SC.load_contract()
    docs, slots_json = R.load_task(ct)
    slots = json.loads(slots_json)
    e = A2.load_reused_e(HERE / 'canary_A', docs)
    rows, _ = R.evidence_rows(e, SC.doc_index(ct))
    done = [r for r in R.read_ledger(HERE / 'canary_A2/LEDGER.jsonl') if r['phase'] == 'done']
    txt = lambda a, n: next(r['text'] for r in done if r['arm'] == a and r['node'] == n)
    table = {}
    for a in A2.ARMS:
        res = D.detect_all(slots, OLD.extract_json(txt(a, 'J2')), OLD.extract_json(txt(a, 'SINK')), OLD.extract_json(e['E_D2']), rows)
        sc = json.loads((HERE / f'canary_A2/ARM_{a}.json').read_text('utf-8'))['record']['metrics']
        st = {r['fact_id']: r['status'] for r in sc['rows']}
        table[a] = dict(
            m1={f: v['state'] for f, v in res['m1'].items() if v['state'] in ('EXPLICIT_SUPPRESSION', 'OMISSION')},
            m2={f: v['state'] for f, v in res['m2'].items()},
            m3_flags={f: st[f] for f, v in res['m3'].items() if v['state'] != 'CONSISTENT'},
            m3_checked=len(res['m3']), terminal=st, base=res['base_total']['value'], safety=S.metrics(sc))
    exp = {f: st for a in A2.ARMS for f, st in table[a]['m1'].items() if st == 'EXPLICIT_SUPPRESSION' for st in [table[a]['terminal'][f]]}
    m1_exp = [(a, f, table[a]['terminal'][f]) for a in A2.ARMS for f, s in table[a]['m1'].items() if s == 'EXPLICIT_SUPPRESSION']
    m1_om = [(a, f, table[a]['terminal'][f]) for a in A2.ARMS for f, s in table[a]['m1'].items() if s == 'OMISSION']
    chk('V1 M1 explicit suppression: 11 slots, all ABSENT at the terminal', len(m1_exp) == 11 and all(t == 'ABSENT' for *_, t in m1_exp), m1_exp)
    chk('V1 M1 omission: 6 slots, all TP at the terminal (V1 missed F17; V2 covers it)', len(m1_om) == 6 and all(t == 'TP' for *_, t in m1_om), m1_om)
    chk('V2 M2: base module 201 from 16 extracted parties; 3/3 model totals mismatch', all(table[a]['base'] == '201万元' and table[a]['m2']['F19'] == 'DERIVED_MISMATCH' for a in A2.ARMS))
    flags = [(a, f, t) for a in A2.ARMS for f, t in table[a]['m3_flags'].items()]
    chk('V3 M3: flags hit only non-TP answers (V1 false alarms on F19 and F20 gone)', flags and all(t != 'TP' for *_, t in flags), flags)
    bad = [(a, f) for a in A2.ARMS for f, t in table[a]['terminal'].items() if t in ('UNSUPPORTED', 'VALUE_WRONG', 'LOC_WRONG')]
    chk('V3 M3: every unsupported or wrong answer flagged', set(bad) == {(a, f) for a, f, _ in flags}, (bad, flags))
    chk('V4 V1 results file untouched', hashlib.sha256((HERE / 'MECHANISM_DETECTION_OFFLINE.json').read_bytes()).hexdigest() == V1_SHA)
    return table


V1_SHA = hashlib.sha256((HERE / 'MECHANISM_DETECTION_OFFLINE.json').read_bytes()).hexdigest()


def main():
    synthetic()
    safety()
    table = development()
    passed = sum(r['ok'] for r in RES)
    out = dict(passed=passed, total=len(RES), results=RES, development=table, v1_results_sha256=V1_SHA,
               files={p: hashlib.sha256((HERE / p).read_bytes()).hexdigest() for p in ('detectors_v2.py', 'safety_metrics.py')})
    (HERE / 'DETECTORS_V2_REGRESSION.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), 'utf-8')
    print(f'\n{passed}/{len(RES)} passed')
    sys.exit(0 if passed == len(RES) else 1)


if __name__ == '__main__':
    main()
