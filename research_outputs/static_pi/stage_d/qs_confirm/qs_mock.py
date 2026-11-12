"""Offline mock for the QS executor. Each node answers only from what its own user message contains, using the
canonical source quotes of the QS contract; behaviour is steered by a per-node plan consumed call by call.

J2 plan kinds: clean, suppress, unknown, mixed, omit (applied to the target slots below); stubborn keeps suppressing
on a recheck. SINK plan kinds: drop_citation:Fx (answer Fx with an empty quote), bad_cite:Fx (answer Fx with an
unrelated table quote). Fault kinds (any node): empty, length, bad_json, http500. E plan: drop_quote:Fx.
"""
import json
import re
import urllib.error

import qs_scorer as Q
import detectors_v5 as D5

CT = Q.load_contract()
FACTS = {f['fact_id']: f for f in CT['required_facts']}
CANON = {fid: ((f['value'] + f.get('unit', '')) if f['value_kind'] == 'number' else f['value'], f['source_evidence'][0]['doc_id'],
               f['source_evidence'][0]['quote']) for fid, f in FACTS.items()}
TARGET = ('F8', 'F9', 'F10', 'F20')
FINAL = CT['entity_correspondence']['final_lines_D2']
PROPOSED = CT['entity_correspondence']['proposed_lines_D1']
MODELS = {'ds': 'deepseek-flash', 'glm': 'glm-5.3-flash'}


def node_of(system):
    for marker, node in (('抽取器', 'E'), ('衔接器', 'J1'), ('核验器', 'J2'), ('汇总器', 'SINK')):
        if marker in system:
            return node
    raise ValueError('unknown node')


class QSMock:
    def __init__(self, plan=None):
        self.plan = {k: list(v) for k, v in (plan or {}).items()}
        self.calls = []

    def describe(self, backend, system, user, max_tokens):
        return f'mock://{backend}', dict(model=MODELS[backend], max_tokens=max_tokens, system=system,
                                         messages=[dict(role='user', content=user)])

    def _next(self, node):
        q = self.plan.get(node)
        return q.pop(0) if q else None

    def call(self, backend, system, user, max_tokens):
        node = node_of(system)
        kind = self._next(node)
        self.calls.append(dict(node=node, backend=backend, kind=kind, max_tokens=max_tokens))
        if kind == 'http500':
            raise urllib.error.HTTPError('mock://', 500, 'Internal Server Error', None, None)
        stop, text = 'stop' if backend == 'ds' else 'end_turn', None
        if kind == 'empty':
            text = ''
        elif kind == 'length':
            text, stop = '{"answers": [', 'length' if backend == 'ds' else 'max_tokens'
        elif kind == 'bad_json':
            text = '不是 JSON'
        else:
            text = getattr(self, '_' + node.lower())(user, kind)
        tin, tout = (len(system) + len(user)) // 2, len(text) // 2 if stop != 'length' and stop != 'max_tokens' else max_tokens
        return dict(text=text, stop=stop, lat=1.0 if backend == 'ds' else 80.0, response_model=MODELS[backend],
                    usage_raw=dict(input_tokens=tin, output_tokens=tout), raw_response=dict(model=MODELS[backend], content=text),
                    **{'in': tin, 'out': tout})

    def _e(self, user, kind):
        drop = {kind.split(':')[1]} if kind and kind.startswith('drop_quote:') else set()
        is_d2 = '2020-079' in user
        doc = 'D2' if is_d2 else 'D1'
        quotes = [CANON[f][2] for f in FACTS if CANON[f][1] == doc and f not in drop and Q.norm_text(CANON[f][2]) in Q.norm_text(user)]
        if is_d2:
            for f in FACTS:
                for e in FACTS[f]['source_evidence']:
                    if e['doc_id'] == 'D2' and f not in drop and e['quote'] not in quotes:
                        quotes.append(e['quote'])
        lines = FINAL if is_d2 else PROPOSED
        parties = [dict(name=n, penalty_amount=f'{a}万元', quote=quotes[0] if quotes else '') for names, a in lines for n in names.split('、')]
        return json.dumps(dict(parties=parties, doc_number=None, dates={}, fraud_facts=[], delisting_risk=None, quotes=quotes), ensure_ascii=False)

    def _j1(self, user, kind):
        matrix = [dict(name=n, proposed_penalty=None, final_penalty=f'{a}万元', position='x', adjustment_note='',
                       evidence=[dict(doc='D2', quote='万元')]) for names, a in FINAL for n in names.split('、')]
        return json.dumps(dict(party_matrix=matrix, date_chain={}, doc_numbers={}), ensure_ascii=False)

    def _j2(self, user, kind):
        slots = json.loads(user.split('槽位：', 1)[1].split('\n\n', 1)[0])
        recheck = '复核要求' in user
        if recheck and kind != 'stubborn':
            kind = 'clean'
        if kind == 'stubborn':
            kind = 'suppress'
        verified = []
        for s in slots:
            fid = s['fact_id']
            if fid == 'F19':
                continue
            entry = dict(fact_id=fid, status='verified', final_value=CANON[fid][0])
            if fid in TARGET and kind in ('suppress', 'unknown', 'mixed', 'omit'):
                if kind == 'omit':
                    continue
                label = {'suppress': 'unverifiable', 'unknown': '部分核验'}.get(kind) or ('unverifiable' if fid in ('F8', 'F9') else '部分核验')
                entry = dict(fact_id=fid, status=label, final_value=None)
            verified.append(entry)
        return json.dumps(dict(verified=verified, derived=[dict(fact_id='F19', value='999万元', computation='x')]), ensure_ascii=False)

    def _sink(self, user, kind):
        j2_text = user.split('核验结果：\n', 1)[1].split('\n\n已核验证据表', 1)[0]
        j2 = json.loads(j2_text)
        status = {str(v.get('fact_id')): v.get('status') for v in j2.get('verified') or []}
        table = re.findall(r'^R\d+ \| doc=(D\d) \| .*? \| quote=(.+)$', user, flags=re.M)
        base = re.search(r'= (\d+万元)', user)
        slots = json.JSONDecoder().raw_decode(user.rsplit('槽位：', 1)[1].lstrip())[0]  # trailing H feedback may follow
        answers, unknown = [], []
        for s in slots:
            fid = s['fact_id']
            if D5.classify(status.get(fid)) in ('suppressed', 'unknown'):
                unknown.append(fid)
                continue
            if fid == 'F19':
                row = next(((d, q) for d, q in table if d == 'D2' and '万元的罚款' in Q.norm_text(q)), None)
                if base and row:
                    answers.append(dict(fact_id=fid, value=base.group(1), doc=row[0], quote=row[1]))
                else:
                    unknown.append(fid)
                continue
            row = next(((d, q) for d, q in table if d == CANON[fid][1] and Q.norm_text(q) == Q.norm_text(CANON[fid][2])), None)
            if row:
                answers.append(dict(fact_id=fid, value=CANON[fid][0], doc=row[0], quote=row[1]))
            else:
                unknown.append(fid)
        if kind and ':' in kind:
            op, fid = kind.split(':')
            for a in answers:
                if a['fact_id'] == fid and op == 'drop_citation':
                    a['quote'], a['doc'] = '', ''
                if a['fact_id'] == fid and op == 'bad_cite':
                    other = next((q for d, q in table if Q.norm_text(q) != Q.norm_text(CANON[fid][2])), '')
                    a['quote'] = other
        if '终端校验反馈' in user:
            pass
        return json.dumps(dict(answers=answers, unknown_slots=unknown), ensure_ascii=False)
