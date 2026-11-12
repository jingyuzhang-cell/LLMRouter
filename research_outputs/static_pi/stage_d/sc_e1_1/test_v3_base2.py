"""Offline regression for detectors V3 and base_total_v2 (zero calls; network patched to fail)."""
import ast
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parent / 'qs_confirm')]
for key in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY'):
    os.environ.pop(key, None)
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network attempted'))

import detectors_v2 as V2  # noqa: E402
import detectors_v3 as V3  # noqa: E402
import base_total_v2 as BT  # noqa: E402
import sc_e1_scorer as SC  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402
import sc_e1_1_stage_a2 as A2  # noqa: E402
import sc_e1_runner as OLD  # noqa: E402
import qs_scorer as Q  # noqa: E402

RES = []
V2_RESULTS_SHA = hashlib.sha256((HERE / 'DETECTORS_V2_REGRESSION.json').read_bytes()).hexdigest()


def chk(name, cond, detail=''):
    RES.append(dict(name=name, ok=bool(cond), detail=str(detail)[:300]))
    print(f'  {name:<84} {"PASS" if cond else "FAIL"} {"" if cond else detail}')


QS = Q.load_contract()
QS_D2 = QS['source_pages']['D2']['pages']['1']['text']
AFF = QS['required_facts'][19]['source_evidence'][0]['quote']
DENY = '《事先告知书》中认定的事实未触及《深圳证券交易所上市公司重大违法强制退市实施办法》第二条、第四条、第五条规定的重大违法强制退市情形'
MIXED = '认定的事实未触及第二条规定的情形，但触及第四条规定的重大违法强制退市情形'
POLAR = dict(fact_id='P', subject='甲公司', predicate='是否触及重大违法强制退市情形')


def v3_tests():
    print('P. polarity (V3)')
    V3.verify_v2()
    chk('P1 V2 file is the frozen one', hashlib.sha256(Path(V2.__file__).read_bytes()).hexdigest() == V3.V2_SHA256)
    chk('P2 是否 slots are typed polar; every other type is V2\'s', V3.slot_type(POLAR) == 'polar' and all(
        V3.slot_type(s) == V2.slot_type(s) for s in [dict(predicate='文号'), dict(predicate='罚款合计', unit='万元'), dict(predicate='职务')]))
    ans = {'是': 'AFFIRM', '已触及': 'AFFIRM', '触及重大违法强制退市情形': 'AFFIRM', True: 'AFFIRM', '否': 'DENY', '未触及': 'DENY',
           '不触及重大违法强制退市情形': 'DENY', False: 'DENY', '可能': 'UNKNOWN', '公司股票可能被实施重大违法强制退市': 'UNKNOWN'}
    got = {repr(k): V3.answer_polarity(k) for k in ans}
    chk('P3 answer polarity: 是/触及 affirm, 否/未触及 deny, hedged answers unknown', all(V3.answer_polarity(k) == v for k, v in ans.items()), got)
    noisy = '公司判断公司涉及的违法行为不触及《上市公司重大违法强制退市实施办法》第二条、第四条和第五条规定的情形'
    got = [V3.quote_polarity(q, '触及') for q in (AFF, DENY, MIXED, noisy, '公司股票可能被实施重大违法强制退市')]
    chk('P4 quote polarity for the slot verb: affirm, deny, mixed clause unknown, other verbs ignored, no verb unknown',
        got == ['AFFIRM', 'DENY', 'UNKNOWN', 'DENY', 'UNKNOWN'], got)
    chk('P4 the slot verb is read from the schema', V3.slot_verb(POLAR) == '触及')
    rows = [dict(row='R1', doc='D1', label='x', quote=AFF), dict(row='R2', doc='D1', label='x', quote=DENY),
            dict(row='R3', doc='D1', label='x', quote=MIXED)]
    cases = [('是', AFF, 'CONSISTENT'), ('否', DENY, 'CONSISTENT'), ('是', DENY, 'SELF_EVIDENCE_INCONSISTENT'),
             ('否', AFF, 'SELF_EVIDENCE_INCONSISTENT'), ('是', MIXED, 'UNDETERMINED'), ('可能', AFF, 'UNDETERMINED'),
             ('是', '不在证据表中的触及强制退市句子', 'SELF_EVIDENCE_INCONSISTENT')]
    got = [(v, q[:8], V3.detect_m3([POLAR], dict(answers=[dict(fact_id='P', value=v, doc='D1', quote=q)]), rows, {})['P']['state'])
           for v, q, _ in cases]
    chk('P5 M3 polar: matching polarity consistent, opposite inconsistent, unreadable undetermined',
        [g[2] for g in got] == [c[2] for c in cases], got)
    v2 = V2.detect_m3([POLAR], dict(answers=[dict(fact_id='P', value='是', doc='D1', quote=AFF)]), rows, {})['P']['state']
    chk('P6 the V2 defect this fixes is still present in V2 (kept unchanged)', v2 == 'SELF_EVIDENCE_INCONSISTENT')
    m1 = V3.detect_m1([POLAR], dict(verified=[dict(fact_id='P', status='unverifiable')]), rows[:1])
    m1_v2 = V2.detect_m1([POLAR], dict(verified=[dict(fact_id='P', status='unverifiable')]), rows[:1])
    chk('P7 M1 polar: an affirmative row is a candidate (V3 flags suppression; V2 could not see it)',
        m1['P']['state'] == 'EXPLICIT_SUPPRESSION' and m1_v2['P']['state'] == 'NONE', (m1, m1_v2))


def equivalence_on_dev():
    print('E. V3 equals V2 on the SC-E1 development outputs except where polarity differs')
    ct = SC.load_contract()
    docs, slots_json = R.load_task(ct)
    slots = json.loads(slots_json)
    e = A2.load_reused_e(HERE / 'canary_A', docs)
    rows, _ = R.evidence_rows(e, SC.doc_index(ct))
    done = [r for r in R.read_ledger(HERE / 'canary_A2/LEDGER.jsonl') if r['phase'] == 'done']
    base = V2.deterministic_total(OLD.extract_json(e['E_D2']))
    diffs = []
    for arm in A2.ARMS:
        j2 = OLD.extract_json(next(r['text'] for r in done if r['arm'] == arm and r['node'] == 'J2'))
        sink = OLD.extract_json(next(r['text'] for r in done if r['arm'] == arm and r['node'] == 'SINK'))
        a, b = V2.detect_all(slots, j2, sink, OLD.extract_json(e['E_D2']), rows), V3.detect_all(slots, j2, sink, base, rows)
        for part in ('m1', 'm2', 'm3'):
            for fid in set(a[part]) | set(b[part]):
                sa, sb = (a[part].get(fid) or {}).get('state'), (b[part].get(fid) or {}).get('state')
                if sa != sb:
                    diffs.append((arm, part, fid, sa, sb))
    chk('E1 identical states for every slot on all three arms', not diffs, diffs)


def base_tests():
    print('B. base_total_v2')
    aliases, conflicts = BT.declared_aliases(QS_D2)
    chk('B1 aliases come only from the document\'s own 以下简称 declarations',
        aliases == {'公司': '湖南千山制药机械股份有限公司', '千山药机': '湖南千山制药机械股份有限公司'} and not conflicts, aliases)
    people = ([dict(name='刘祥华', penalty_amount='30万元'), dict(name='刘华山', penalty_amount='30万元'), dict(name='周大连', penalty_amount='15万元'),
               dict(name='姜纯', penalty_amount='10万元')] + [dict(name=n, penalty_amount='4万元') for n in ('钟波', '刘燕', '邓铁山', '王国华', '郑国胜', '彭勋德', '黄盛秋')]
              + [dict(name=n, penalty_amount='3万元') for n in ('付慧龙', '金杰')])
    full = dict(name='湖南千山制药机械股份有限公司', penalty_amount='60万元')
    clean = BT.total(dict(parties=[full] + people), QS_D2)
    chk('B2 clean extraction: 179 over 14 parties', clean['value'] == '179万元' and clean['parties'] == 14, clean)
    dup = BT.total(dict(parties=[full, dict(name='千山药机', penalty_amount='60万元')] + people), QS_D2)
    chk('B3 declared alias listed twice: counted once, 179, merge recorded',
        dup['value'] == '179万元' and dup['parties'] == 14 and dup['merged'] == {'湖南千山制药机械股份有限公司': ['千山药机', '湖南千山制药机械股份有限公司']}, dup)
    gen = BT.total(dict(parties=[dict(name='公司', penalty_amount='60万元')] + people), QS_D2)
    chk('B4 the declared generic alias 公司 maps to the company', gen['value'] == '179万元' and '湖南千山制药机械股份有限公司' in gen['addends'], gen)
    con = BT.total(dict(parties=[full, dict(name='千山药机', penalty_amount='30万元')] + people), QS_D2)
    chk('B5 alias with a different amount: total unavailable, conflict reported', con['value'] is None and con['conflicts'] == ['湖南千山制药机械股份有限公司'], con)
    fuzzy = BT.total(dict(parties=[full, dict(name='千山制药', penalty_amount='60万元')] + people), QS_D2)
    chk('B6 undeclared similar name is not merged (no similarity matching): counted separately',
        fuzzy['value'] == '239万元' and fuzzy['parties'] == 15 and not fuzzy['merged'], fuzzy)
    clash, cc = BT.declared_aliases('甲股份有限公司（以下简称“甲公司”）与乙股份有限公司（以下简称“甲公司”）')
    chk('B7 an alias declared for two different entities is dropped', clash == {} and cc == ['甲公司'], (clash, cc))
    none = BT.total(dict(parties=[full, dict(name='千山药机', penalty_amount='60万元')] + people), '没有任何简称声明的文本')
    chk('B8 without declarations it behaves as version 1 (double count stays visible)', none['value'] == '239万元', none)
    ct = SC.load_contract()
    docs, _ = R.load_task(ct)
    e2 = OLD.extract_json(A2.load_reused_e(HERE / 'canary_A', docs)['E_D2'])
    v1, v2 = V2.deterministic_total(e2), BT.total(e2, ct['source_pages']['D2']['pages']['1']['text'])
    chk('B9 SC-E1 development extraction: same 201 over 16 parties as version 1', v1['value'] == v2['value'] == '201万元' and v2['parties'] == 16, (v1, v2))
    src = (HERE / 'base_total_v2.py').read_text('utf-8') + (HERE / 'detectors_v3.py').read_text('utf-8')
    chk('B10 no answer constants in either module', '179' not in src and '201' not in src)
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    chk('B11 neither module reads Gold or a contract', not names & {'required_facts', 'source_evidence', 'allowed_citation_docs', 'contract', 'SC', 'Q'})
    chk('B12 V2 regression results untouched', hashlib.sha256((HERE / 'DETECTORS_V2_REGRESSION.json').read_bytes()).hexdigest() == V2_RESULTS_SHA)


def main():
    v3_tests()
    equivalence_on_dev()
    base_tests()
    passed = sum(r['ok'] for r in RES)
    files = {p: hashlib.sha256((HERE / p).read_bytes()).hexdigest() for p in ('detectors_v3.py', 'base_total_v2.py', 'detectors_v2.py')}
    (HERE / 'V3_BASE2_REGRESSION.json').write_text(json.dumps(dict(passed=passed, total=len(RES), results=RES, files=files),
                                                             ensure_ascii=False, indent=1), 'utf-8')
    print(f'\n{passed}/{len(RES)} passed')
    sys.exit(0 if passed == len(RES) else 1)


if __name__ == '__main__':
    main()
