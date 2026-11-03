"""Phase Pi V2.3 — candidate scoring pipeline (does NOT modify v1.2.3).

Pipeline:
  raw SINK output
    -> adapter: claims + abstentions + claims_complete + delivery_valid + doc-id normalization
    -> canonicalizer: map preregistered semantically-equivalent answer forms onto the frozen gold token
    -> frozen terminal_quality.evaluate_terminal_quality (unchanged, imported read-only)

Every transformation is deterministic, audited per claim, and applied identically
to all arms. The canonicalization table is authored from gold semantics and is
PENDING human ratification; it must be frozen before any confirmatory run.
"""
import hashlib, json, re, sys, unicodedata

sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
sys.path.insert(0, '/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4')
from terminal_quality import evaluate_terminal_quality

CANDIDATE_DIR = '/root/research_outputs/static_pi/stage_d/v23'
DEFAULT_CONTRACT = CANDIDATE_DIR + '/contract_v23_candidate.json'


def _norm(x):
    t = unicodedata.normalize('NFKC', str(x if x is not None else ''))
    return re.sub(r'\s+', '', t)


def normalize_doc(doc):
    """Node-name -> document-id normalization (deterministic, contract-level).

    'E1(D1)' -> 'D1'; 'E2_pos' -> 'D2'; 'D3' -> 'D3'; unknown ids stay unchanged.
    """
    if doc is None:
        return doc
    s = str(doc)
    m = re.search(r'D([1-4])', s)
    if m:
        return 'D' + m.group(1)
    m = re.match(r'E([1-4])(?:$|_)', s)
    if m:
        return 'D' + m.group(1)
    return s


def build_terminal_output(sink, contract, source_pages):
    """Contract-aware adapter. Fills claims_complete / delivery_valid per the
    frozen answer_policy, and normalizes document ids at the boundary."""
    slots = {f['fact_id']: f for f in contract['required_facts']}
    unknown_ids = {u.get('item_id') for u in contract.get('unknown_items', [])
                   if isinstance(u, dict) and u.get('item_id') not in (None, '')}
    answers = sink.get('answers') if isinstance(sink, dict) else None
    answers = answers if isinstance(answers, list) else []

    claims, structural_ok, seen = [], True, set()
    for a in answers:
        if not isinstance(a, dict):
            structural_ok = False
            continue
        fid = a.get('fact_id')
        if fid is None or not str(fid).strip():
            structural_ok = False
            continue
        if fid in seen:
            structural_ok = False
            continue
        seen.add(fid)
        if fid in unknown_ids:
            claims.append({'claim_id': f'c_{fid}', 'item_id': fid, 'value': a.get('value'),
                           'citations': [], 'weight': 1.0, 'material': True})
            continue
        slot = slots.get(fid)
        if slot is None:
            structural_ok = False
            continue
        doc = normalize_doc(a.get('doc'))
        cite = {'doc_id': doc, 'page': a.get('page'), 'quote': a.get('quote', '')}
        d = source_pages.get(doc) if doc else None
        if isinstance(d, dict):
            pg = d.get('pages', {}).get(str(cite['page']))
            if isinstance(pg, dict):
                cite['page_sha256'] = pg.get('page_sha256')
                cite['raw_sha256'] = d.get('raw_sha256')
        claims.append({
            'claim_id': f'c_{fid}', 'fact_id': fid,
            'subject': slot.get('subject'), 'predicate': slot.get('predicate'),
            'value': a.get('value'),
            'value_kind': slot.get('value_kind'), 'unit': '', 'date_type': '',
            'citations': [cite], 'weight': 1.0, 'material': True,
        })

    abstentions = [{'item_id': x.get('item_id'), 'text': str(x.get('text', ''))}
                   for x in (sink.get('abstentions') or []) if isinstance(x, dict)] \
                  if isinstance(sink, dict) else []
    abstained = {x['item_id'] for x in abstentions if x.get('item_id') not in (None, '')}
    asserted = {c.get('item_id') for c in claims if c.get('item_id')}
    claims_complete = bool(isinstance(sink, dict) and isinstance(answers, list) and structural_ok and answers)
    delivery_valid = bool(isinstance(sink, dict) and answers
                          and any(a.get('value') not in (None, '') for a in answers if isinstance(a, dict)))
    return {
        'claims': claims, 'abstentions': abstentions,
        'abstentions_complete': unknown_ids <= (abstained | asserted),
        'claims_complete': claims_complete,
        'delivery_valid': delivery_valid,
    }


# ── canonicalization: preregistered semantic equivalences ──────────────────
def _num(v):
    m = re.match(r'^(-?\d+(?:\.\d+)?)', _norm(v))
    return m.group(1) if m else None


def _num_ok(v, target):
    """Numeric equivalence: leading number equals target, and the remainder is
    only measure words or a digit-free parenthetical qualifier."""
    m = re.match(r'^(-?\d+(?:\.\d+)?)(.*)$', v)
    if not m:
        return False
    num, rest = m.group(1), m.group(2)
    rest = re.sub(r'^(个|件|项|人|条|次|位|名)+', '', rest)
    if rest and not (rest.startswith('(') and rest.endswith(')') and not re.search(r'\d', rest)):
        return False
    return num == target


_PARTIAL = ('无法判定', '不可判定', '无法确定', '不能判定', '不确定')


def _canon(fid, v, gold):
    v = _norm(v)
    g = _norm(gold)
    if not v:
        return None
    # Terminal punctuation is a formatting variant, never a contradiction.
    v = v.strip('。．.,，；;、')
    if not v:
        return None
    # A partial answer that explicitly declines part of the slot must never be
    # canonicalized onto the full gold value.
    if any(k in v for k in _PARTIAL):
        return None
    if v == g:
        return g
    if fid in ('A1', 'A2'):
        if v.startswith('PERSON_ONLY_') and '俞发祥' in v and 'BOTH_' not in v \
                and 'COMPANY_ONLY_' not in v and not _has(v, '公司被立案', '公司亦被立案', '公司及实控人'):
            return g
        return None
    if fid == 'A3':
        return g if (v.startswith('BOTH_') and '王勇' in v) else None
    if fid == 'A4':
        return g if (v.startswith('COMPANY_ONLY_') and '纳川' in v) else None
    if fid == 'A5':
        ok = _has(v, '仅实际控制人', '均无职务', '无职务', '均为实际控制人')
        bad = _has(v, '董事长', '总经理', '法定代表人', '监事', '董事')
        return g if (ok and not bad and '实际控制人' in v) else None
    if fid == 'B3':
        return g if ('0042026002' in v and '0042026003' in v and '王勇' in v and '公司' in v) else None
    if fid == 'B3b':
        # mapping must be 0042026002 -> 公司 and 0042026003 -> 王勇, in that order
        m2 = re.search(r'0042026002(.{0,24})', v)
        m3 = re.search(r'0042026003(.{0,24})', v)
        ok2 = bool(m2 and '公司' in m2.group(1))
        ok3 = bool(m3 and '王勇' in m3.group(1))
        return g if (ok2 and ok3 and _has(v, '→', '->', '对应', '分别')) else None
    if fid == 'C1':
        return g if ('2023年年报' in v and '信息披露违法违规' in v and 'SPECIFIC' in v) else None
    if fid == 'C2':
        return g if ('GENERIC' in v and '涉嫌信息披露违法违规' in v and '未指明' not in v) else None
    if fid == 'D_1':
        return g if (_has(v, '同一人', '同一自然人', '同一个人') and not _has(v, '不同', '并非', '不是')) else None
    if fid == 'D_2':
        return g if (_has(v, '同一份', '同属一份') and _has(v, '告知书', '文书')
                     and not _has(v, '不同', '并非', '不是')) else None
    if fid == 'D_3':
        return g if (_has(v, '同一收到事件', '同日收到') and not _has(v, '不同', '并非', '不是')) else None
    if fid == 'D_4':
        return g if _has(v, '非同一公司', '不同公司', '两家不同', '不是同一公司', '并非同一公司') else None
    if fid == 'E1':
        return g if _num_ok(v, '1') else None
    if fid == 'E2':
        return g if _num_ok(v, '2') else None
    if fid == 'E3':
        return g if _num_ok(v, '2') else None
    if fid == 'F4':
        return g if ('落款日' in v and _has(v, '不同', '差', '10-10', '10月10日')
                     and _has(v, '收到日', '收到事件') and '不可判定' not in v) else None
    return None


def _has(v, *keys):
    return any(k in v for k in keys)


def canonicalize(terminal_output, contract):
    """Rewrite materially-equivalent claim values onto the frozen gold token.
    Returns an audit list; never rewrites a claim that is not equivalent."""
    gold = {f['fact_id']: f.get('value') for f in contract['required_facts']}
    audit = []
    for c in terminal_output.get('claims', []):
        fid = c.get('fact_id')
        if fid is None or fid not in gold or c.get('item_id'):
            continue
        before = c.get('value')
        canon = _canon(fid, before, gold[fid])
        if canon is not None and _norm(canon) != _norm(before):
            c['value'] = canon
            audit.append({'claim_id': c.get('claim_id'), 'fact_id': fid,
                          'from': str(before)[:120], 'to': gold[fid]})
    return audit


def sink_sha256(sink):
    """Canonical hash used as the blinded key of the answer-relevance registry."""
    return hashlib.sha256(json.dumps(sink, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def answer_relevance_for(sink, registry):
    """Only per-output (I-2) adjudications may supply the question_relevance
    dimension. Task-material (I-1) entries are rejected by scope."""
    if not isinstance(registry, dict):
        return None, 'no_registry'
    if registry.get('scope') != 'output_answer':
        return None, 'wrong_registry_scope'
    entry = (registry.get('entries') or {}).get(sink_sha256(sink))
    if not isinstance(entry, dict):
        return None, 'no_entry_for_output'
    if entry.get('scope') != 'output_answer':
        return None, 'entry_wrong_scope'
    assessment = entry.get('assessment')
    if not isinstance(assessment, dict):
        return None, 'bad_assessment'
    return assessment, 'ok'


def score(sink, contract, source_pages, relevance=None, answer_registry=None):
    if relevance is None and answer_registry is not None:
        relevance, _ = answer_relevance_for(sink, answer_registry)
    term = build_terminal_output(sink, contract, source_pages)
    if relevance is not None:
        term['question_relevance'] = relevance
    audit = canonicalize(term, contract)
    res = evaluate_terminal_quality(contract, term, source_pages)
    return res, audit, term


def load_contract(path=DEFAULT_CONTRACT):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def load_relevance_registry(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


VALUE_OK_STATUSES = ('CORRECT_GOLD', 'CORRECT_BUT_UNSUPPORTED_CITATION',
                     'SEMANTICALLY_CORRECT', 'SEMANTICALLY_CORRECT_BUT_UNSUPPORTED_CITATION')


def metrics_summary(res, term, contract):
    """The five metrics the operator requires alongside the gate's 0/1.
    The gate measures trustworthy terminal delivery; the others explain the
    failure mechanism and must not substitute for it."""
    claims = [c for c in (term or {}).get('claims', []) if c.get('fact_id')]
    loc_ok = sum(1 for c in claims
                 if any(cit.get('page_sha256') for cit in (c.get('citations') or [])))
    crit = [f['fact_id'] for f in contract.get('required_facts', []) if f.get('critical')]
    correct = {c.get('fact_id') for c in res.get('claim_results', [])
               if c.get('status') in VALUE_OK_STATUSES}
    gate = res.get('critical_gate', {}).get('status')
    return {
        'critical_gate': gate,
        'critical_gate_pass': 1.0 if gate == 'PASS' else 0.0,
        'critical_value_correct_rate': round(len(set(crit) & correct) / len(crit), 6) if crit else None,
        'evidence_localization_rate': round(loc_ok / len(claims), 6) if claims else None,
        'evidence_support_rate': (res.get('dimensions') or {}).get('evidence_support'),
        'q_partial_diagnostic': res.get('Q_partial_diagnostic'),
        'q_final': res.get('Q_final'),
        'fact_precision': (res.get('fact_metrics') or {}).get('precision'),
    }
