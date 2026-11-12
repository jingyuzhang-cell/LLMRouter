#!/usr/bin/env python3
"""UB-1 TWO-LAYER DELIVERY CONTRACT (frozen 2026-11-07, operator ruling).

Store -> [key-fact selection (body priority ONLY)] -> body (model narrative +
         priority facts attached verbatim by code)
      -> [complete fact appendix] -> ALL facts code-carried; conflicts kept+flagged;
         dedup keeps source relations. NOTHING is silently deletable.
Selection organizes; it does not decide delivery eligibility.
Scoring (frozen): Q_body / Q_appendix / Q_terminal reported SEPARATELY.

Priority rules (frozen BEFORE gold inspection; gold-independent regex):
  amounts / dates / entities / penalties / core events.
"""
import json, re

NORM = lambda s: re.sub(r'[\s,,、;;::]+','',str(s))
RE_AMOUNT = re.compile(r'\d[\d,,.]*\s*(万元|亿元|元|%|％)')
RE_DATE = re.compile(r'(19|20)\d{2}\s*年|\d{4}-\d{2}-\d{2}|\d{4}\.\d{1,2}\.\d{1,2}')
RE_ENTITY = re.compile(r'公司|证监会|交易所|管理局|监管局|银行|协会|委员会|事务所')
RE_PENALTY = re.compile(r'处罚|罚款|禁入|警告|责令|立案|没收')
RE_CORE = re.compile(r'违法|违规|虚增|虚减|虚列|退市|虚假|欺诈|风险提示|信息披露|内幕')

def priority(f):
    v = str(f.get('value','')) + str(f.get('quote',''))
    tags = []
    if RE_AMOUNT.search(v): tags.append('amount')
    if RE_DATE.search(v): tags.append('date')
    if RE_ENTITY.search(v): tags.append('entity')
    if RE_PENALTY.search(v): tags.append('penalty')
    if RE_CORE.search(v): tags.append('core')
    return tags

def build_delivery(store, vs, narrative, model_key_facts):
    by_fid = {f['fid']: f for f in store}
    cited, seen = [], set()
    for k in model_key_facts or []:
        f = by_fid.get(str(k))
        if f and f['fid'] not in seen:
            cited.append({**f, 'verify_status': vs.get(str(k),'unverified'),
                          'tier':'body', 'why':'model-cited'}); seen.add(f['fid'])
    for f in store:
        tags = priority(f)
        if tags and f['fid'] not in seen:
            cited.append({**f, 'verify_status': vs.get(str(f['fid']),'unverified'),
                          'tier':'body', 'why':'priority:'+ '+'.join(tags)}); seen.add(f['fid'])
    groups = {}
    for f in store:
        groups.setdefault(NORM(f.get('value','')), []).append(f)
    appendix = []
    for f in store:
        g = groups[NORM(f.get('value',''))]
        conflict = len({x.get('doc') for x in g}) > 1 or len(g) > 1
        appendix.append({**f, 'verify_status': vs.get(str(f['fid']),'unverified'),
                         'tier':'appendix',
                         'status_source':'slim-annotation (not source verification)',
                         'conflict': bool(conflict), 'sources': [x['fid'] for x in g]})
    artifact = dict(kind='two_layer_terminal_answer',
                    body=dict(narrative=narrative, facts=cited),
                    appendix=dict(n_facts=len(appendix), facts=appendix))
    q_body_text = narrative + json.dumps(cited, ensure_ascii=False)
    q_appendix_text = json.dumps(appendix, ensure_ascii=False)
    return artifact, q_body_text, q_appendix_text

def score_delivery(q_body_text, q_appendix_text, gold):
    def hits(text):
        blob = NORM(text); n = 0
        for c in gold:
            gs, gv = NORM(c['span']), NORM(c['value'])
            if (gs and gs in blob) or (len(gv) >= 6 and gv in blob): n += 1
        return n / len(gold)
    qb, qa = hits(q_body_text), hits(q_appendix_text)
    qt = hits(q_body_text + q_appendix_text)
    return dict(Q_body=round(qb,3), Q_appendix=round(qa,3), Q_terminal=round(qt,3))

P_SELECT_ANCHORS = {'V1_model_keyfacts': (0.33, 0.70),
                    'V2_priority_deterministic': (0.94, 1.00),
                    'V3_two_layer_appendix': (1.00, 1.00)}
L_SELECTION_ANCHORS = {'V1': 0.32, 'V2': 0.02, 'V3': 0.0}

def dQ_terminal_hat(dQ_transport, delivery='V3_two_layer_appendix', conservative=True):
    lo, hi = P_SELECT_ANCHORS[delivery]
    p = lo if conservative else hi
    return round(dQ_transport * p - L_SELECTION_ANCHORS[delivery.split('_')[0]], 4)
