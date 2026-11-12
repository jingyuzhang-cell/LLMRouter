"""Offline fixtures for SC-E1.1: verbatim canonical answers and a deterministic oracle transport.

Each mock node can only report what is present in the user message it received, so a mock run
measures information reachability through the plumbing. It says nothing about model capability.
"""
import json
import re
import sys
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import sc_e1_runner as OLD  # noqa: E402
import sc_e1_scorer as SC  # noqa: E402

CT = SC.load_contract()


def _canon_value(fact):
    return f"{fact['value']}{fact['unit']}" if fact['value_kind'] == 'number' else str(fact['value'])


CANON = {f['fact_id']: (_canon_value(f), f['source_evidence'][0]['doc_id'], f['source_evidence'][0]['quote'])
         for f in CT['required_facts']}
PENALTY_LINES = {fid: CANON[fid][2] for fid in ('F1', 'F2', 'F4', 'F6', 'F7')}

PARTY_ORDER = ['獐子岛集团股份有限公司', '吴厚刚', '梁峻', '勾荣', '孙福君', '于成家', '赵颖', '石敬江', '邹建', '王涛',
               '赵志年', '罗伟新', '陈本洲', '丛锦秀', '陈树文', '吴晓巍', '杨育健', '刘红涛', '李金良', '唐艳',
               '张戡', '刘中博', '姜玉宝', '曹秉才', '邹德波']
# Length of one party row in the real J1 output: 3000 chars held 9 rows (sc_e1_diag snapshot).
ROW_FILLER = '依据两文书核对。' * 30
DATE_KEYS = {'F12': '立案调查', 'F13': '告知书', 'F14': '决定书'}
DOCNO_KEYS = {'F15': '处罚决定书文号', 'F16': '市场禁入决定书文号', 'F17': '告知书文号'}
SUBJECT_NAME = {'F1': '獐子岛集团股份有限公司', 'F2': '吴厚刚', 'F3': '梁峻', 'F4': '孙福君', 'F5': '勾荣',
                'F6': '邹建', 'F7': '于成家'}


def _in(fid, text):
    return SC.norm_text(CANON[fid][2]) in SC.norm_doc(text)


def canonical_sink():
    return dict(answers=[dict(fact_id=f, value=v, doc=d, quote=q) for f, (v, d, q) in CANON.items()], unknown_slots=[])


class MockTransport:
    """faults: {(node, backend): kind or [kind or None, ...]} consumed per call to that node/backend.
    Kinds: empty, length, http429, http400, http500, bad_json, wrong_model, alias_model, no_model, input_truncated,
    empty_answers, no_final."""

    MODELS = {'ds': 'deepseek-flash', 'glm': 'glm-5.3-flash'}

    def __init__(self, faults=None):
        self.faults = dict(faults or {})
        self.calls = []

    def describe(self, backend, system, user, max_tokens):
        return f'mock://{backend}', dict(model=self.MODELS[backend], max_tokens=max_tokens, system=system,
                                         messages=[dict(role='user', content=user)])

    def _next_fault(self, key):
        fault = self.faults.get(key)
        if isinstance(fault, list):
            return fault.pop(0) if fault else None
        self.faults.pop(key, None)
        return fault

    def call(self, backend, system, user, max_tokens):
        node = self._node(system)
        self.calls.append(dict(node=node, backend=backend, max_tokens=max_tokens, user_len=len(user)))
        fault = self._next_fault((node, backend))
        if fault == 'http429':
            raise urllib.error.HTTPError('mock://', 429, 'Too Many Requests', None, None)
        if fault == 'http400':
            raise urllib.error.HTTPError('mock://', 400, 'Bad Request', None, None)
        if fault == 'http500':
            raise urllib.error.HTTPError('mock://', 500, 'Internal Server Error', None, None)
        size = (len(system) + len(user)) // 2
        model = self.MODELS[backend]
        stop = 'stop'
        if fault == 'empty':
            text = ''
        elif fault == 'length':
            text, stop = '{"answers": [', 'length'
        elif fault == 'bad_json':
            text = '这不是 JSON'
        elif fault == 'empty_answers':
            text = json.dumps(dict(answers=[], unknown_slots=list(CANON)), ensure_ascii=False)
        else:
            text = getattr(self, f'_{node.lower()}')(system, user, fault)
        if fault == 'wrong_model':
            model = 'qwen-plus' if backend == 'ds' else 'deepseek-flash'
        elif fault == 'alias_model':
            model += '-20261106'
        elif fault == 'no_model':
            model = None
        tin = 10 if fault == 'input_truncated' else size
        tout = max_tokens if fault == 'length' else len(text) // 2
        usage = dict(input_tokens=tin, output_tokens=tout)
        return dict(text=text, stop=stop, lat=0.0, response_model=model, usage_raw=usage,
                    raw_response=dict(model=model, usage=usage, content=text), **{'in': tin, 'out': tout})

    @staticmethod
    def _node(system):
        for marker, node in (('抽取器', 'E'), ('衔接器', 'J1'), ('核验器', 'J2'), ('汇总器', 'SINK')):
            if marker in system:
                return node
        raise ValueError('unknown node prompt')

    def _e(self, system, user, fault=None):
        degraded = 'penalty_amount' not in system
        out = dict(parties=[], doc_number=None, dates={}, fraud_facts=[], delisting_risk=None)
        if not degraded:
            out['quotes'] = []
        for fid in CANON:
            if not _in(fid, user):
                continue
            value, _, quote = CANON[fid]
            if fid in ('F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7'):
                if not degraded:
                    out['parties'].append(dict(name=SUBJECT_NAME[fid], penalty_amount=value, quote=quote))
            elif fid == 'F18':
                out['parties'].append(dict(name='吴厚刚', position='董事长、总裁', quote=quote))
            elif fid in ('F8', 'F9', 'F10', 'F11'):
                out['fraud_facts'].append(dict(item=fid, amount=value, quote=quote))
            elif fid in DATE_KEYS:
                out['dates'][DATE_KEYS[fid]] = dict(date=value, quote=quote)
            elif fid in DOCNO_KEYS:
                out['dates'][DOCNO_KEYS[fid]] = dict(number=value, quote=quote)
            elif fid == 'F20':
                out['delisting_risk'] = dict(value='否', quote=quote)
        return json.dumps(out, ensure_ascii=False)

    def _j1(self, system, user, fault=None):
        final_part = '' if fault == 'no_final' else user.split('决定书(D2)抽取：', 1)[-1]
        finals = {}
        for fid, line in PENALTY_LINES.items():
            if line in final_part:
                names = re.search(r'对(.+?)给予警告', line).group(1).split('、')
                for name in names:
                    finals[name] = (CANON[fid][0], line)
        matrix = []
        for name in PARTY_ORDER:
            position = '董事长、总裁' if name == '吴厚刚' and '董事长、总裁' in final_part else '其他直接责任人员'
            final, line = finals.get(name, (None, None))
            matrix.append(dict(name=name, proposed_penalty=None, final_penalty=final, position=position,
                               adjustment_note=ROW_FILLER, evidence=[dict(doc='D2', quote=line)] if line else []))
        date_chain = {k: CANON[f][0] for f, k in DATE_KEYS.items() if _in(f, user)}
        doc_numbers = {k: CANON[f][0] for f, k in DOCNO_KEYS.items() if _in(f, user)}
        return json.dumps(dict(party_matrix=matrix, date_chain=date_chain, doc_numbers=doc_numbers), ensure_ascii=False)

    def _j2(self, system, user, fault=None):
        verified, derived = [], []
        amounts = {}
        for fid, name in SUBJECT_NAME.items():
            m = re.search(rf'"name": "{name}".{{0,60}}?"final_penalty": "([^"]+)"', user)
            if m:
                verified.append(dict(fact_id=fid, status='confirmed', final_value=m.group(1)))
                amounts[fid] = m.group(1)
        for fid, key in {**DATE_KEYS, **DOCNO_KEYS}.items():
            m = re.search(rf'"{key}": "([^"]+)"', user)
            if m:
                verified.append(dict(fact_id=fid, status='confirmed', final_value=m.group(1)))
        if re.search(r'"name": "吴厚刚".{0,90}?"position": "董事长、总裁"', user):
            verified.append(dict(fact_id='F18', status='confirmed', final_value='董事长、总裁'))
        if len(amounts) == 7:
            derived.append(dict(fact_id='F19', value='201万元', computation='60+30×2+20×2+4×8+3×3'))
        return json.dumps(dict(verified=verified, derived=derived), ensure_ascii=False)

    def _sink(self, system, user, fault=None):
        slots = json.loads(user.rsplit('槽位：', 1)[-1])
        table = re.findall(r'^R\d+ \| doc=(D\d) \| .*? \| quote=(.+)$', user, flags=re.M)
        answers, unknown = [], []
        for slot in slots:
            fid = slot['fact_id']
            hit = next(((d, q) for d, q in table
                        if d == CANON[fid][1] and SC.norm_text(q) == SC.norm_text(CANON[fid][2])), None)
            carried = re.search(rf'"fact_id": "{fid}", "(?:status": "[^"]+", "final_value|value)": "([^"]+)"', user)
            if fid == 'F19' and not carried:
                hit = None
            if hit:
                answers.append(dict(fact_id=fid, value=CANON[fid][0], doc=hit[0], quote=hit[1]))
            elif carried:
                answers.append(dict(fact_id=fid, value=carried.group(1), doc='', quote=''))
            else:
                unknown.append(fid)
        return json.dumps(dict(answers=answers, unknown_slots=unknown), ensure_ascii=False)


def simulate_plumbing(e_window=None, j1_cut=None, j2_cut=None, table=True, contract=None):
    """Reachability of a slot under the given cuts, with oracle nodes. None means no cut."""
    import sc_e1_1_runner as R
    contract = contract or SC.load_contract()
    docs, slots_json = R.load_task(contract)
    docs_norm = SC.doc_index(contract)
    t = MockTransport()
    clip = lambda s, n: s if n is None else s[:n]
    e_texts = {f'E_{d}': t.call('ds', R.E_SYS, R.e_user(clip(docs[d], e_window)), 8000)['text'] for d in ('D1', 'D2')}
    j1 = t.call('glm', R.J1_SYS, R.j1_user(e_texts), 8000)['text']
    j2 = t.call('ds', R.J2_SYS, R.j2_user(clip(j1, j1_cut), slots_json), 4000)['text']
    if table:
        rows, _ = R.evidence_rows(e_texts, docs_norm)
        user = R.sink_user(clip(j2, j2_cut), rows, slots_json)
    else:
        user = f'核验结果：\n{clip(j2, j2_cut)}\n\n槽位：{slots_json}'
    sink = json.loads(t.call('ds', R.SINK_SYS, user, 4000)['text'])
    return SC.score(sink, contract)
