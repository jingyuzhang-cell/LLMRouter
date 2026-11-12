"""SC-E1.1 offline regression (zero calls: urlopen is patched to fail the run if anything tries the network)."""
import ast
import copy
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
for key in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY', 'SC_E1_1_CANARY_GO', 'SC_E1_GO'):
    os.environ.pop(key, None)


def _no_network(*a, **k):
    raise AssertionError('network attempted during offline regression')


urllib.request.urlopen = _no_network

import sc_e1_runner as OLD  # noqa: E402
import sc_e1_scorer as SC  # noqa: E402
import sc_e1_1_mock as M  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402
import build_contract_v1_1 as B  # noqa: E402

CT = SC.load_contract()
FACTS = {f['fact_id']: f for f in CT['required_facts']}
RES = []


def chk(name, cond, detail=''):
    RES.append(dict(name=name, ok=bool(cond), detail=str(detail)[:300]))
    print(f'  {name:<72} {"PASS" if cond else "FAIL"} {"" if cond else detail}')


def status_of(fid, value, doc=None, quote=None, contract=CT):
    canon = M.CANON[fid]
    answer = dict(fact_id=fid, value=value, doc=canon[1] if doc is None else doc,
                  quote=canon[2] if quote is None else quote)
    return next(r for r in SC.score(dict(answers=[answer]), contract)['rows'] if r['fact_id'] == fid)['status']


def test_contract():
    print('D. contract v1.1')
    v1_bytes = B.V1.read_bytes()
    chk('D1 Gold v1 is untouched', hashlib.sha256(v1_bytes).hexdigest().startswith(B.V1_SHA256))
    chk('D2 v1.1 file matches the pinned sha256', hashlib.sha256(B.V1_1.read_bytes()).hexdigest() == SC.CONTRACT_SHA256)
    try:
        SC.load_contract(B.V1)
        refused = False
    except RuntimeError:
        refused = True
    chk('D2 scoring refuses contract v1, so versions cannot be mixed', refused)
    v1 = json.loads(v1_bytes)
    chk('D3 no Gold value changed', [(f['fact_id'], f['value']) for f in v1['required_facts']]
        == [(f['fact_id'], f['value']) for f in CT['required_facts']])
    idx = SC.doc_index(CT)
    bad = [f['fact_id'] for f in CT['required_facts'] for e in f['source_evidence']
           if SC.norm_text(e['quote']) not in idx[e['doc_id']]]
    chk('D4 every evidence quote is verbatim in its source document', not bad, bad)
    changed = [r['fact_id'] for r in CT['revision_log'][0]['changes'] if r.get('fact_id')]
    chk('D4 revision log names exactly the four corrected quotes', sorted(changed) == ['F12', 'F13', 'F14', 'F19'], changed)
    final = B.penalty_table(idx['D2'])
    proposed = B.penalty_table(idx['D1'])
    chk('D5 F19 recomputed from source: final 16 parties 201, proposed 25 parties 344',
        sum(len(n) * a for n, a in final) == 201 == FACTS['F19']['value'] and sum(len(n) for n, _ in final) == 16
        and sum(len(n) * a for n, a in proposed) == 344 and sum(len(n) for n, _ in proposed) == 25)
    rows = CT['p2_draft_mapping']['rows']
    targets = [r['v1_1_slot'] for r in rows if r['v1_1_slot']]
    chk('D6 P2 mapping: 20 rows, 7 same, 13 changed, 4 added, every slot accounted for',
        len(rows) == 20 and sum(r['change'] == 'same' for r in rows) == 7
        and sorted(targets + CT['p2_draft_mapping']['added_in_contract'], key=lambda x: int(x[1:])) == [f'F{i}' for i in range(1, 21)], targets)
    rules = {'amount', 'date', 'doc_number', 'title_set', 'negation', 'penalty_line_sum'}
    chk('D7 every slot has a citation whitelist and a known grounding rule',
        all(f['allowed_citation_docs'] and set(f['allowed_citation_docs']) <= {'D1', 'D2'} and f['grounding']['rule'] in rules
            for f in CT['required_facts']))
    chk('D8 positioning and independence are corrected in the contract',
        '不属于独立确认性实验' in CT['positioning'] and CT['provenance']['independence'].startswith('NOT INDEPENDENT'))
    variant = copy.deepcopy(CT)
    next(f for f in variant['required_facts'] if f['fact_id'] == 'F8')['allowed_citation_docs'] = ['D1']
    chk('D9 the whitelist is read from the contract, not from code', status_of('F8', '6002.99万元') == 'TP'
        and status_of('F8', '6002.99万元', contract=variant) == 'LOC_WRONG')


def test_scorer():
    print('A. scorer')
    SC.verify_pins()
    perfect = SC.score(M.canonical_sink(), CT)
    chk('A1 gold self-test: Q_all=Q_terminal=1, 20 TP, no unTPable slot',
        perfect['Q_all'] == 1.0 and perfect['Q_terminal'] == 1.0 and perfect['tp'] == 20, perfect['rows'])

    wrong_values = [
        ('F1', '60元'), ('F1', '6万元'), ('F2', '20万元'), ('F4', '30万元'), ('F5', '30万元'), ('F6', '5万元'),
        ('F7', '20万元'), ('F4', '拟30万元，终20万元'), ('F8', '6002.99亿元'), ('F11', '158.15%'),
        ('F12', '2018-12-31'), ('F12', '2018-02-08'), ('F13', '2019-07-11'), ('F14', '2020-06-25'),
        ('F15', '【2020】9号'), ('F16', '【2020】29号'), ('F17', '连调查字[2018]001号'), ('F17', '【2020】29号'),
        ('F15', '【2020】29号和【2020】9号'), ('F18', '董事长'), ('F18', '董事、常务副总裁'), ('F18', '总裁'),
        ('F18', '董事长、副总裁'), ('F18', '副董事长、总裁'), ('F19', '344万元'), ('F19', '246万元'), ('F20', '是'), ('F20', '已触及'),
    ]
    miss = [(f, v, status_of(f, v)) for f, v in wrong_values if status_of(f, v) != 'VALUE_WRONG']
    chk(f'A2 {len(wrong_values)} wrong values all scored VALUE_WRONG (incl. D1 proposed-stage traps)', not miss, miss)

    right_values = [
        ('F1', 60), ('F1', '60'), ('F1', '60万元'), ('F1', '60 万元'), ('F1', '60万'), ('F1', '６０万元'),
        ('F1', '罚款60万元'), ('F6', '每人4万元'), ('F6', '4万元/人'), ('F6', '邹建等8人各4万元'),
        ('F8', '6,002.99万元'), ('F8', '6002.99'), ('F8', 6002.99), ('F11', '158.11%'), ('F11', '158.11％'),
        ('F11', '158.11'), ('F12', '2018-02-09'), ('F12', '2018年2月9日'), ('F12', '2018 年 2 月 9 日'),
        ('F12', '2018/2/9'), ('F15', '【2020】29号'), ('F15', '【2020】29 号'), ('F15', '[2020]29号'),
        ('F15', '〔2020〕29号'), ('F15', '《行政处罚决定书》【2020】29号'), ('F16', '【2020】9号'),
        ('F17', '处罚字【2019】95号'), ('F17', '（处罚字【2019】95 号）'), ('F18', '董事长、总裁'),
        ('F18', '时任獐子岛公司董事长、总裁'), ('F18', '董事长兼总裁'), ('F20', '否'), ('F20', '不触及'),
        ('F20', '未触及重大违法强制退市情形'), ('F20', False), ('F19', '201万元'), ('F19', 201),
    ]
    miss = [(f, v, status_of(f, v)) for f, v in right_values if status_of(f, v) != 'TP']
    chk(f'A3 {len(right_values)} format variants of right values all TP', not miss, miss)

    cases = {
        'fabricated quote': ('F8', '6002.99万元', 'D2', '獐子岛公司虚减营业成本共计六千万元以上', 'LOC_WRONG'),
        'node name as doc id (P0 root cause 3)': ('F8', '6002.99万元', 'E_D2', None, 'LOC_WRONG'),
        'empty citation': ('F8', '6002.99万元', '', '', 'LOC_WRONG'),
        'proposed-stage sentence for a final fact': ('F2', '30万元', 'D1', '对吴厚刚、梁峻、孙福君、勾荣给予警告，并分别处以 30 万元罚款', 'LOC_WRONG'),
        'identical sentence cited from D1 for a final fact': ('F1', '60万元', 'D1', None, 'LOC_WRONG'),
        'verbatim but irrelevant sentence': ('F8', '6002.99万元', 'D2', '特别风险提示', 'UNSUPPORTED'),
        'quote lacks the subject': ('F2', '30万元', 'D2', '并分别处以 30 万元罚款', 'UNSUPPORTED'),
        'another subject in the quote': ('F3', '30万元', 'D2', '对孙福君、勾荣给予警告，并分别处以 20 万元罚款', 'UNSUPPORTED'),
        'bare number with no fact context': ('F8', '6002.99万元', 'D2', '6,002.99 万元', 'UNSUPPORTED'),
        'too short to be evidence': ('F20', '否', 'D1', '未触及', 'LOC_WRONG'),
    }
    for name, (fid, value, doc, quote, want) in cases.items():
        got = status_of(fid, value, doc, quote)
        chk(f'A4 evidence bar: {name} -> {want}', got == want, got)
    d2_f12 = '2018 年 2 月 9 日，獐子岛集团股份有限公司（以下简称“公司”）收到中国证券监督管理委员会（以下简称“中国证监会”）《调查通知书》（编号：连调查字【2018】001 号）'
    chk('A4 whitelisted background fact may cite either doc', status_of('F12', '2018-02-09', 'D2', d2_f12) == 'TP')
    d1 = SC.doc_index(CT)['D1']
    chk('A4 quote across a PDF page break matches once the page number is ignored',
        SC.norm_text('根据獐子岛成本核算方式，上述区域应重新核算成本') in d1)
    literal = SC.score(dict(answers=[dict(fact_id='F8', value='6002.99万元', doc='D2', quote='特别风险提示')]), CT)
    chk('A4 E_literal keeps the P2 caliber: verbatim but unsupported counts there, not in TP',
        literal['E_literal'] == 1.0 and literal['tp'] == 0 and literal['Q_all'] == 0.0, literal)

    empty = SC.score(dict(answers=[], unknown_slots=list(FACTS)), CT)
    chk('A5 zero answers: Q_all=0, not NULL, flagged', empty['Q_all'] == 0.0 and empty['zero_assertions'], empty)
    chk('A5 unknown_slots recorded as declared abstention', all(r['declared_unknown'] for r in empty['rows']))
    nulls = SC.score(dict(answers=[dict(fact_id='F1', value=None, doc='D2', quote='x'),
                                   dict(fact_id='F2', value='未载明', doc='D2', quote='x')]), CT)
    chk('A5 null/未载明 is abstention, not a wrong assertion', nulls['asserted'] == 0 and nulls['wrong'] == 0, nulls)
    odd = SC.score(dict(answers=['bad', dict(fact_id='X9', value=1), dict(fact_id='f1', value='60万元')]), CT)
    chk('A5 unknown ids are reported, never remapped', odd['out_of_contract'] == ['X9', 'f1'] and odd['malformed_answers'] == 1, odd)
    q = M.CANON['F1'][2]
    dup_same = SC.score(dict(answers=[dict(fact_id='F1', value='60万元', doc='D2', quote=q)] * 2), CT)
    dup_diff = SC.score(dict(answers=[dict(fact_id='F1', value='60万元', doc='D2', quote=q),
                                      dict(fact_id='F1', value='30万元', doc='D2', quote=q)]), CT)
    chk('A5 same duplicate counted once; conflicting duplicate is wrong',
        dup_same['asserted'] == 1 and dup_same['tp'] == 1 and dup_diff['wrong'] == 1 and dup_diff['tp'] == 0)

    def graded(k_wrong):
        answers = M.canonical_sink()['answers']
        for a in answers[:k_wrong]:
            a['value'] = '99999万元' if FACTS[a['fact_id']]['value_kind'] == 'number' else '错误'
        return SC.score(dict(answers=answers), CT)
    q_seq = [graded(k)['Q_terminal'] for k in (0, 1, 5, 10, 20)]
    a_seq = [graded(k)['Q_all'] for k in (0, 1, 5, 10, 20)]
    chk('A6 discrimination: Q_all and Q_terminal fall strictly as wrong answers rise',
        all(x > y for x, y in zip(q_seq, q_seq[1:])) and all(x > y for x, y in zip(a_seq, a_seq[1:])), (q_seq, a_seq))
    one = SC.score(dict(answers=M.canonical_sink()['answers'][:1]), CT)
    fifteen = graded(5)
    chk('A6 primary endpoint fixes the abstention defect: 15 right 5 wrong outranks one lone answer on Q_all only',
        fifteen['Q_all'] > one['Q_all'] and fifteen['Q_terminal'] < one['Q_terminal'], (fifteen['Q_all'], one['Q_all']))

    tree = ast.parse((HERE / 'sc_e1_scorer.py').read_text('utf-8'))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'score')
    chk('A8 scorer is arm-blind: no arm/condition/rep identifier, signature score(sink, contract)',
        not names & {'arm', 'condition', 'rep', 'trace', 'injected'} and [a.arg for a in fn.args.args] == ['sink', 'contract'])

    perfect_ans = M.canonical_sink()['answers']
    old_perfect = OLD.score(perfect_ans, CT['required_facts'])
    chk('A7 old scorer defect reproduced: perfect answer capped below 1 (F18, F20 can never match)',
        old_perfect['correct'] == 18 and old_perfect['Q_terminal'] < 1, old_perfect)
    collapse = [dict(fact_id='F12', value='2018-12-31', doc='D1', quote='x'),
                dict(fact_id='F15', value='【2020】9号', doc='D2', quote='x'),
                dict(fact_id='F8', value='6002.99亿元', doc='D2', quote='x')]
    old_c = OLD.score(collapse, CT['required_facts'])
    new_c = SC.score(dict(answers=collapse), CT)
    chk('A7 old scorer defect reproduced: wrong date/doc number/unit credited correct; new scorer rejects them',
        old_c['correct'] == 3 and new_c['correct'] == 0, (old_c, new_c['correct']))
    chk('A7 old scorer defect reproduced: fabricated citation credited (E=1); new scorer gives E=0',
        old_c['E'] == 1 and new_c['E'] == 0)
    return dict(q_terminal_by_wrong=dict(zip((0, 1, 5, 10, 20), q_seq)), q_all_by_wrong=dict(zip((0, 1, 5, 10, 20), a_seq)),
                old_scorer_perfect=old_perfect, old_scorer_collapse=old_c)


def done_rows(out):
    return [r for r in R.read_ledger(Path(out) / 'LEDGER.jsonl') if r['phase'] == 'done']


def user_of(row):
    return row['request_body']['messages'][-1]['content']


def run_a(faults=None):
    td = tempfile.mkdtemp()
    t = M.MockTransport(faults)
    return t, R.run_stage('A', t, td), done_rows(td), td


def test_runner():
    print('B. runner (oracle mock)')
    extra = {}
    docs, slots_json = R.load_task(CT)

    t, s, rows, td = run_a()
    recs = s['records']
    chk('B1 stage A: 11 calls, three COMPLETE, acceptance PASS',
        s['used']['calls'] == 11 and all(r['status'] == 'COMPLETE' for r in recs) and s['acceptance']['verdict'] == 'PASS', s['used'])
    chk('B1 oracle reaches 20/20 TP in every arm', all(r['metrics']['tp'] == 20 for r in recs))
    chk('B1 normal condition: no arm takes a recovery action', all(r['trace'][0]['action'] == 'none' for r in recs))
    chk('B1 all three arms go through one scorer with no arm input', all(SC.score(r['sink'], CT) == r['metrics'] for r in recs))
    chk('B1 ledger-only rescore reproduces every online score', R.rescore(td) == {f"normal|1|{r['arm']}": r['metrics'] for r in recs})
    e2 = next(r for r in rows if r['node'] == 'E_D2')
    chk('B1 E_D2 receives the whole document, not doc[:6000]', docs['D2'][-200:] in user_of(e2), len(user_of(e2)))
    j1 = next(r for r in rows if r['node'] == 'J1')
    j2 = next(r for r in rows if r['node'] == 'J2')
    chk('B1 J2 receives the whole J1 output, not j1[:3000]', j1['text'] in user_of(j2) and len(j1['text']) > 3000, len(j1['text']))
    sink = next(r for r in rows if r['node'] == 'SINK')
    chk('B1 SINK receives the whole J2 output and the evidence table', j2['text'] in user_of(sink) and '已核验证据表' in user_of(sink))
    chk('B1 frozen route: J1=GLM (P2 pool), E/J2/SINK=DS',
        {r['node']: r['backend'] for r in rows} == {'E_D1': 'ds', 'E_D2': 'ds', 'J1': 'glm', 'J2': 'ds', 'SINK': 'ds'})
    all_rows = R.read_ledger(Path(td) / 'LEDGER.jsonl')
    chk('B1 ledger: a sent row precedes every done row, each done row has payload, response, usage, model, cost, output',
        [r['phase'] for r in all_rows] == ['sent', 'done'] * 11 and R.ledger_integrity(Path(td) / 'LEDGER.jsonl')
        and all(r.get('request_body') and r.get('raw_response') and r.get('usage_raw') and r.get('response_model')
                and r.get('text') and r.get('yuan_accounting') is not None for r in rows))
    chk('B1 GLM calls are booked at the accounting price, marginal ¥0', j1['yuan_accounting'] > 0 and j1['yuan_marginal'] == 0)
    chk('B1 model identity is summarized', s['models_reported'] == ['ds:deepseek-flash', 'glm:glm-5.3-flash'], s['models_reported'])
    extra['stage_A_mock_used'] = s['used']

    with tempfile.TemporaryDirectory() as td2:
        t = M.MockTransport()
        s = R.run_stage('B', t, td2)
        rows = done_rows(td2)
        by = {(r['condition'], r['arm']): r for r in s['records']}
        nodes = lambda c, a: [x['node'] for x in rows if x['condition'] == c and x['arm'] == a]
        chk('B2 exec_anomaly Static: injected empty, no paid J1 call, INCOMPLETE',
            by['exec_anomaly', 'Static']['status'] == 'INCOMPLETE_NO_RECOVERY' and nodes('exec_anomaly', 'Static') == ['J1'], nodes('exec_anomaly', 'Static'))
        fixed = [x for x in rows if x['condition'] == 'exec_anomaly' and x['node'] == 'J1_retry']
        joint = [x for x in rows if x['condition'] == 'exec_anomaly' and x['node'] == 'J1_swap']
        chk('B2 exec_anomaly: Fixed retries same model, Joint swaps model',
            len(fixed) == 1 and fixed[0]['backend'] == 'glm' and len(joint) == 1 and joint[0]['backend'] == 'ds')
        chk('B2 recovery calls share max_tokens (old runner gave Joint 4000, Fixed 8000)',
            fixed[0]['max_tokens'] == joint[0]['max_tokens'] == 8000)
        s_q = by['info_anomaly', 'Static']['metrics']
        f_q = by['info_anomaly', 'Fixed-Recovery']['metrics']
        j_q = by['info_anomaly', 'Joint-Dynamic']['metrics']
        chk('B2 info_anomaly reaches the arms: Static acts none, Fixed retries J1, Joint re-extracts E_D2',
            by['info_anomaly', 'Static']['trace'][0]['action'] == 'none'
            and by['info_anomaly', 'Fixed-Recovery']['trace'][0]['action'] == 'repair_retry'
            and by['info_anomaly', 'Joint-Dynamic']['trace'][0]['action'] == 'reextract_upstream')
        chk('B2 info_anomaly oracle ordering: Joint recovers penalty slots, Fixed cannot (set by topology)',
            j_q['Q_all'] == 1.0 and f_q['Q_all'] == s_q['Q_all'] < 1.0, (s_q['Q_all'], f_q['Q_all'], j_q['Q_all']))
        chk('B2 stage B mock stays inside its call cap (22 of 23)', s['used']['calls'] == 22, s['used'])
        chk('B2 acceptance PASS with Static INCOMPLETE by design only', s['acceptance']['verdict'] == 'PASS', s['acceptance'])
        extra['stage_B_mock_used'] = s['used']
        extra['info_anomaly_oracle'] = dict(Static=(s_q['Q_all'], s_q['Q_terminal']), Fixed=(f_q['Q_all'], f_q['Q_terminal']),
                                            Joint=(j_q['Q_all'], j_q['Q_terminal']))

    stops = [
        ('GLM J1 HTTP 400', {('J1', 'glm'): 'http400'}, 3, 'transport error'),
        ('GLM J1 HTTP 500', {('J1', 'glm'): 'http500'}, 3, 'transport error'),
        ('HTTP 429 at SINK', {('SINK', 'ds'): 'http429'}, 5, 'transport error'),
        ('truncation at E_D1', {('E', 'ds'): 'length'}, 1, 'natural fault: truncated'),
        ('empty text at J1', {('J1', 'glm'): 'empty'}, 3, 'natural fault: empty_text'),
        ('parse failure at J2', {('J2', 'ds'): 'bad_json'}, 4, 'natural fault: json_invalid'),
        ('SINK empty answers', {('SINK', 'ds'): 'empty_answers'}, 5, 'SINK returned no answers'),
        ('input silently truncated', {('E', 'ds'): 'input_truncated'}, 1, 'input looks truncated'),
        ('provider reports another model family', {('J1', 'glm'): 'wrong_model'}, 3, 'provider reports model'),
    ]
    for label, faults, want_calls, want_msg in stops:
        t, s, rows, td3 = run_a(faults)
        chk(f'B3 stop, {label}: halts after {want_calls} calls, no retry, FAIL, scene on disk',
            s['stopped'] and want_msg in s['stopped'] and len(t.calls) == want_calls and s['acceptance']['verdict'] == 'FAIL'
            and rows and rows[-1].get('request_body') and R.ledger_integrity(Path(td3) / 'LEDGER.jsonl'), (s['stopped'], len(t.calls)))
    t, s, rows, _ = run_a({('J1', 'glm'): 'http400'})
    chk('B3 a failed request keeps its payload and the status line', rows[-1]['stop'] == 'transport_error' and '400' in rows[-1]['error']
        and user_of(rows[-1]))
    t, s, rows, _ = run_a({('J1', 'glm'): [None, 'no_final']})
    chk('B3 stop, recovery wanted in Stage A: no recovery call, Static record survives',
        'recovery action' in s['stopped'] and len(t.calls) == 6 and [r['arm'] for r in s['records']] == ['Static'], (s['stopped'], len(t.calls)))
    real_score = SC.score
    try:
        def boom(*a):
            raise ValueError('scorer broke')
        SC.score = boom
        t, s, rows, _ = run_a()
        chk('B3 stop, scoring exception on a complete execution', 'scoring failed' in s['stopped'] and len(t.calls) == 5
            and s['acceptance']['verdict'] == 'FAIL', (s['stopped'], len(t.calls)))
        SC.score = lambda *a: dict(real_score(*a), Q_all=None)
        t, s, rows, _ = run_a()
        chk('B3 stop, Q_all NULL on a complete execution', 'NULL' in s['stopped'] and len(t.calls) == 5
            and s['acceptance']['verdict'] == 'FAIL', (s['stopped'], len(t.calls)))
    finally:
        SC.score = real_score
    t, s, rows, _ = run_a({('E', 'ds'): 'alias_model'})
    chk('B3 same-family model alias is recorded, not a stop', s['stopped'] is None and rows[0]['response_model'].endswith('-20261106'), s['stopped'])
    t, s, rows, _ = run_a({('J1', 'glm'): 'no_model'})
    chk('B3 a response without a model string is recorded, not a stop', s['stopped'] is None and 'glm:None' in s['models_reported'], s['stopped'])
    chk('B3 truncation outranks empty text (GLM budget filling), unknown stop reason is a fault',
        R.guard('J1', dict(text='', stop='max_tokens'))[0] == 'truncated' and R.guard('J1', dict(text='{"party_matrix": []}', stop='content_filter'))[0] == 'abnormal_stop')
    with tempfile.TemporaryDirectory() as td4:
        path = Path(td4) / 'LEDGER.jsonl'
        led = R.Ledger(path)
        led.write(dict(phase='sent', condition='normal', arm='Static', node='J1', user_sha256='x', injected=False, request_body=dict(a=1)))
        chk('B3 a crash between send and receive leaves a dangling row that fails ledger integrity', not R.ledger_integrity(path))

    def env_with(budget, t=None):
        t = t or M.MockTransport()
        return t, R.Env(t, R.Ledger(Path(tempfile.mkdtemp()) / 'LEDGER.jsonl'), budget, 'normal', 1)

    def stopped_at(env, node, backend, system, user):
        try:
            env.call(node, backend, system, user)
            return None
        except R.Stop as stop:
            return str(stop)
    t, env = env_with(R.Budget(99, 1000, 1.0))
    msg = stopped_at(env, 'E_D2', 'ds', R.E_SYS, R.e_user(docs['D2']))
    chk('B4 token cap: pre-flight stops before the transport is called', msg and 'token' in msg and not t.calls, msg)
    t, env = env_with(R.Budget(99, 10**9, 0.001))
    msg = stopped_at(env, 'E_D2', 'ds', R.E_SYS, R.e_user(docs['D2']))
    chk('B4 yuan cap: pre-flight stops before the transport is called', msg and 'yuan' in msg and not t.calls, msg)
    t, env = env_with(R.Budget(1, 10**9, 100.0))
    msg = stopped_at(env, 'E_D1', 'ds', R.E_SYS, R.e_user(docs['D1']))
    chk('B4 call cap: reaching it stops at once', msg and 'calls cap reached' in msg and len(t.calls) == 1, msg)
    chk('B4 authorized Stage A caps are exactly 13 / 230K / ¥0.30 with no recovery',
        (R.STAGES['A']['calls'], R.STAGES['A']['tokens'], R.STAGES['A']['yuan']) == (13, 230_000, 0.30) and R.STAGES['A']['allow_recovery'] is False
        and R.STAGES['A']['conditions'] == ('normal',))
    t, env = env_with(R.Budget(99, 10**9, 100.0))
    msg1 = stopped_at(env, 'J1', 'ds', R.J1_SYS, 'x')
    msg2 = stopped_at(env, 'J2', 'ds', R.J2_SYS + ' 改动', 'x')
    msg3 = stopped_at(env, 'E_D2', 'ds', R.E_SYS_DEGRADED, 'x')
    chk('B4 request differing from the frozen route or prompt stops before sending',
        all(m and 'frozen configuration' in m for m in (msg1, msg2, msg3)) and not t.calls, (msg1, msg2, msg3))

    def row(final, doc=None, quote='并分别处以 30 万元罚款'):
        return dict(name='x', final_penalty=final, evidence=[dict(doc=doc, quote=quote)] if doc else [])

    def obs_for(rows_, e_text=''):
        return R.observe(R.NodeOut('x', dict(party_matrix=rows_), None), e_text)
    chk('B4b J1 contract: all-null final amounts are unmet', R.policy_fixed(obs_for([row(None)] * 25)) == R.RETRY)
    chk('B4b J1 contract: amounts copied from D1 do not hide a deficient E_D2',
        R.policy_joint(obs_for([row('30万元', 'D1')] * 25)) == R.REEXTRACT)
    chk('B4b J1 contract: one lone D2-backed row is still unmet',
        R.policy_joint(obs_for([row('60万元', 'D2')] + [row(None)] * 24)) == R.REEXTRACT)
    chk('B4b J1 contract: 16 of 25 D2-backed rows (expected normal shape) passes in every policy',
        all(pol(obs_for([row('30万元', 'D2')] * 16 + [row(None)] * 9)) == R.NONE
            for pol in (R.policy_static, R.policy_fixed, R.policy_joint)))
    chk('B4b J1 contract accepts D2 named as 决定书 and a final amount given as a number',
        R.policy_fixed(obs_for([row(30, '决定书(D2)')] * 16 + [row(None)] * 9)) == R.NONE)
    chk('B4b Joint repairs J1, not E_D2, when E_D2 already carries penalty sentences',
        R.policy_joint(obs_for([row(None)] * 25, '对吴厚刚给予警告，并分别处以 30 万元罚款')) == R.RETRY)
    chk('B4b Joint maps empty/truncated to model swap, malformed JSON to structural retry',
        R.policy_joint(R.Obs('empty_text', 0.0, 9)) == R.SWAP and R.policy_joint(R.Obs('truncated', 0.0, 9)) == R.SWAP
        and R.policy_joint(R.Obs('json_invalid', 0.0, 9)) == R.RETRY)

    tree = ast.parse((HERE / 'sc_e1_1_runner.py').read_text('utf-8'))
    decision = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ('policy_static', 'policy_fixed', 'policy_joint', 'observe', '_backed_by_d2', 'run_execution'):
            decision[node.name] = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} \
                | {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)} | {a.arg for a in node.args.args}
    forbidden = {'condition', 'inject', 'injected', 'inject_empty', 'required_facts', 'contract', 'CANON', 'source_evidence', 'SC'}
    hits = {k: sorted(v & forbidden) for k, v in decision.items() if v & forbidden}
    old_src = Path(OLD.__file__).read_text('utf-8')
    chk('B5 decision code reads no condition flag and no Gold (old Joint branched on inject_empty)',
        not hits and 'if inject_empty:' in old_src and len(decision) == 6, hits)
    slot_keys = {k for s_ in json.loads(slots_json) for k in s_}
    chk('B5 slots carry no Gold value', slot_keys == {'fact_id', 'subject', 'predicate', 'unit'}, slot_keys)

    fake = {'E_D1': json.dumps(dict(parties=[], quotes=['2019 年 7 月 9 日，公司及相关人员收到\n中国证监会下发的', '这句话原文根本没有出现过']), ensure_ascii=False),
            'E_D2': json.dumps(dict(parties=[dict(name='吴厚刚', penalty_amount='999万元', quote=M.PENALTY_LINES['F2'])]), ensure_ascii=False)}
    ev_rows, rejected = R.evidence_rows(fake, SC.doc_index(CT))
    chk('B6 evidence table: verbatim kept (whitespace-insensitive), fabricated dropped', len(ev_rows) == 2 and rejected == 1, (ev_rows, rejected))
    chk('B6 evidence table drops the model-attached amount, keeps the source sentence',
        '999万元' not in R.evidence_block(ev_rows) and '30 万元' in R.evidence_block(ev_rows))

    chk('B7 system prompts are byte-identical to sc_e1_runner.py',
        (R.E_SYS, R.J1_SYS, R.J2_SYS, R.SINK_SYS) == (OLD.E_SYS, OLD.J1_SYS, OLD.J2_SYS, OLD.SINK_SYS))
    chk('B7 degraded E prompt differs only by dropped penalty fields and quotes list',
        'penalty_amount' not in R.E_SYS_DEGRADED and '"quotes"' not in R.E_SYS_DEGRADED and 'fraud_facts' in R.E_SYS_DEGRADED)
    chk('B7 every prompt sent with json_object contains "json" (HTTP 400 regression)',
        all('json' in p.lower() for p in (R.E_SYS, R.E_SYS_DEGRADED, R.J1_SYS, R.J1_REPAIR_SYS, R.J2_SYS, R.SINK_SYS)))

    zero = [dict(arm=a, condition='normal', rep=1, status='COMPLETE', metrics=SC.score(dict(answers=[]), CT),
                 trace=[dict(action=R.NONE)]) for a in R.ARMS]
    chk('B8 false-PASS regression: an all-zero run can never be accepted', R.canary_acceptance(zero, None)['verdict'] == 'FAIL')
    spurious = [dict(arm=a, condition='normal', rep=1, status='COMPLETE', metrics=SC.score(M.canonical_sink(), CT),
                     trace=[dict(action=R.RETRY if a == 'Fixed-Recovery' else R.NONE)]) for a in R.ARMS]
    chk('B8 a spurious recovery in the normal condition fails acceptance', R.canary_acceptance(spurious, None)['verdict'] == 'FAIL')
    clean = [dict(r, trace=[dict(action=R.NONE)]) for r in spurious]
    chk('B8 an incomplete ledger fails acceptance', R.canary_acceptance(clean, None, ledger_ok=False)['verdict'] == 'FAIL'
        and R.canary_acceptance(clean, None)['verdict'] == 'PASS')

    def refused(stage, env_go, sha):
        if env_go:
            os.environ['SC_E1_1_CANARY_GO'] = '1'
        try:
            R.check_real_gate(stage, sha)
            return None
        except SystemExit as exc:
            return str(exc)
        finally:
            os.environ.pop('SC_E1_1_CANARY_GO', None)
    chk('B9 Stage B cannot run for real even with the GO flag', 'HOLD' in (refused('B', True, 'x') or ''))
    chk('B9 real mode refused without GO flag', 'SC_E1_1_CANARY_GO' in (refused('A', False, 'x') or ''))
    chk('B9 real mode refused with a wrong freeze sha', 'freeze' in (refused('A', True, 'not-the-sha') or ''))
    return extra


def test_request_bytes():
    print('E. real transport (request capture only, nothing leaves the process)')
    captured = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps(self.payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    responses = {
        'ds': dict(model='deepseek-flash', choices=[dict(message=dict(content='{"a":1}'), finish_reason='stop')],
                   usage=dict(prompt_tokens=7, completion_tokens=3)),
        'glm': dict(model='glm-5.3-flash', content=[dict(type='thinking', thinking='想'), dict(type='text', text='{"a":1}')],
                    usage=dict(input_tokens=7, cache_read_input_tokens=5, output_tokens=3), stop_reason='end_turn'),
    }
    current = {}

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        return FakeResponse(responses[current['backend']])

    os.environ['DEEPSEEK_API_KEY'] = 'FAKEKEYDS'
    os.environ['STAGE_D_GLM_KEY'] = 'FAKEKEYGLM'
    urllib.request.urlopen = fake_urlopen
    try:
        system, user = R.J1_SYS, '含中文的用户消息 json'
        transport = R.RealTransport()
        current['backend'] = 'ds'
        R.DS_TRANSPORT.openai_call('deepseek', system, user, 8000, 300, 0)
        ref_ds = captured.pop()
        ds = transport.call('ds', system, user, 8000)
        new_ds = captured.pop()
        current['backend'] = 'glm'
        OLD.glm_low(system, user, max_tokens=8000)
        ref_glm = captured.pop()
        glm = transport.call('glm', system, user, 8000)
        new_glm = captured.pop()
    finally:
        urllib.request.urlopen = _no_network
        os.environ.pop('DEEPSEEK_API_KEY', None)
        os.environ.pop('STAGE_D_GLM_KEY', None)
    chk('E1 DS request is byte-identical to transport.openai_call', new_ds.data == ref_ds.data and new_ds.full_url == ref_ds.full_url)
    chk('E1 GLM request is byte-identical to the prior glm_low (subscription endpoint, reasoning_effort=low, no thinking field)',
        new_glm.data == ref_glm.data and new_glm.full_url == ref_glm.full_url and 'api/anthropic' in new_glm.full_url
        and 'thinking' not in json.loads(new_glm.data))
    chk('E1 the payload written to the ledger is what is sent',
        json.dumps(transport.describe('ds', system, user, 8000)[1]).encode() == new_ds.data
        and json.dumps(transport.describe('glm', system, user, 8000)[1], ensure_ascii=False).encode() == new_glm.data)
    chk('E2 raw response and model identity kept; thinking blocks stay in raw only',
        ds['response_model'] == 'deepseek-flash' and glm['response_model'] == 'glm-5.3-flash' and glm['text'] == '{"a":1}'
        and glm['raw_response']['content'][0]['type'] == 'thinking' and ds['in'] == 7 and glm['out'] == 3)
    chk('E2 cached GLM input counts toward usage (J1 repeats one prompt across arms)', glm['in'] == 12, glm['in'])
    blob = json.dumps([ds, glm], ensure_ascii=False)
    chk('E3 no credential can reach the ledger: keys only in headers, never in the returned record',
        'FAKEKEY' not in blob and 'Bearer' not in blob and new_ds.get_header('Authorization') == 'Bearer FAKEKEYDS')


def test_ablation():
    print('C. plumbing ablation (oracle reachability, not model performance)')
    table = {}
    for name, kw in (('old_all_cuts_no_table', dict(e_window=6000, j1_cut=3000, j2_cut=2000, table=False)),
                     ('fix_e_window_only', dict(e_window=None, j1_cut=3000, j2_cut=2000, table=False)),
                     ('fix_j1_to_j2_only', dict(e_window=6000, j1_cut=None, j2_cut=2000, table=False)),
                     ('fix_j2_to_sink_only', dict(e_window=6000, j1_cut=3000, j2_cut=None, table=False)),
                     ('fix_all_cuts_no_table', dict(e_window=None, j1_cut=None, j2_cut=None, table=False)),
                     ('table_only_old_cuts', dict(e_window=6000, j1_cut=3000, j2_cut=2000, table=True)),
                     ('all_fixes', dict())):
        x = M.simulate_plumbing(contract=CT, **kw)
        table[name] = {k: x[k] for k in ('asserted', 'correct', 'tp', 'Q_all', 'Q_terminal')}
    chk('C1 old plumbing yields zero answers even with oracle nodes', table['old_all_cuts_no_table']['asserted'] == 0, table)
    chk('C2 removing the cuts alone still leaves TP=0 (no path carries doc+quote to SINK)',
        table['fix_all_cuts_no_table']['tp'] == 0 and table['fix_all_cuts_no_table']['asserted'] == 15, table)
    chk('C3 the table alone cannot reach the penalty slots', table['table_only_old_cuts']['tp'] == 11, table)
    chk('C4 all fixes together reach 20/20 TP', table['all_fixes']['tp'] == 20, table)
    return table


def main():
    test_contract()
    extra = test_scorer()
    extra.update(test_runner())
    test_request_bytes()
    ablation = test_ablation()
    passed = sum(r['ok'] for r in RES)
    out = dict(passed=passed, total=len(RES), results=RES, ablation=ablation, extra=extra,
               files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (HERE / 'sc_e1_scorer.py', HERE / 'sc_e1_1_runner.py', HERE / 'sc_e1_1_mock.py',
                                HERE / 'build_contract_v1_1.py', SC.CONTRACT_PATH)})
    (HERE / 'REGRESSION_RESULTS.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), 'utf-8')
    print(f'\n{passed}/{len(RES)} passed')
    sys.exit(0 if passed == len(RES) else 1)


if __name__ == '__main__':
    main()
