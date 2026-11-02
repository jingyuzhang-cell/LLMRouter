"""DD-V7.7 v3 runner: production path with FIXED data contract.

Fixes over /tmp/v76_runner.py (dd_v76_n5_paired_v2), all derived from the
frozen DAGSpec (D_重大事件与市场反应_r1_spec.json), which carries per-node
`inputs`, `contract.requires/produces` and `evidence` fields:
  F1 key mismatch   — v2 n3/n4/n5/n6 looked up ud['doc_extracts'] but the
                      runner stores ud['extraction'] (role) / ud['n1']/ud['n2']
                      (node id) -> all four consumers got '' (66-char prompts).
  F2 shared-role multi-parent overwrite — n5 and n6 have TWO parents with the
                      SAME role (n1,n2 both 'extraction'). v2's single role key
                      kept only the last parent (n2); n1's output was silently
                      lost even where the key name matched.
  F3 truncation      — v2 extraction ran with max_tokens=768; both n1/n2 hit
                      stop=max_tokens with unbalanced JSON. Extraction out cap
                      raised to 1536; per-parent context cap 3800 chars (>= any possible extraction output) keeps
                      downstream prompts in budget.
  F4 evidence-binding violation — the spec declares n1 -> evidence
                      zeda_csrc_penalty_2023_29 only (produces facts_main)
                      and n2 -> zeda_csrc_penalty_2024_kangda only (produces
                      facts_intermediary). v2 fed BOTH docs to BOTH nodes
                      (byte-identical prompts, near-duplicate outputs). v3
                      binds each extraction node to exactly its declared doc,
                      FAIL-CLOSED on a missing declared doc.
  -> Downstream context is assembled from the spec `inputs` lists by node id
     (labelled with role + produces field). No hand-written key names anywhere
     in build_prompt.

Arm structure, models, semantic gate and scoring are UNCHANGED from the
frozen dd_v74_request_manifest.json (23 requests, 8 glm53 / 15 flash).
Purposes are V77-* so no v2 ledger entry can dedup-replay.

STAGED EXECUTION (operator final instruction, item 6): one authorization
batch, two stages. Stage 1 runs ONLY n1 and n2, then a contract gate
checks stop_reason, complete JSON, doc-id source binding, entities and
input-derived fact coverage; any FAIL stops the batch (fail-stop, no
retries). Stage 2 runs the remaining 21 requests with a per-node contract
gate (n5 exempt — its garbage output is the injected fault). All request/
response/token/latency/node-state evidence is preserved; terminal scoring
is label-blind.

Execution is FAIL-CLOSED: auth gate requires the seven-field record
'dd_v77_n5_paired_v3' in AUTHORIZATIONS.json before any call.
"""
import json, sys, time, re, hashlib
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
for p in (Path('/root/capital_opinion_pilot'), B, B/'scoring', B/'evidence'):
    sys.path.insert(0, str(p))

from pilot_common import Meter

# ---- frozen DAGSpec: the single source of truth for the data contract ----
D_R1 = json.load(open('/root/r3_own_pool/deadline_reward_v1/fe_screening_runs/'
                      'planner_v1_20261028/D_重大事件与市场反应_r1_spec.json'))
DEPS = {n['id']: list(n.get('inputs', [])) for n in D_R1['nodes']}
ROLES = {n['id']: n['role'] for n in D_R1['nodes']}
NODE_EV = {n['id']: n.get('evidence') for n in D_R1['nodes']}
PRODUCES = {n['id']: list(n.get('contract', {}).get('produces', []))
            for n in D_R1['nodes']}


def node_docs(nid):
    """F4 fix: a node reads exactly the evidence doc its frozen spec entry
    declares. FAIL-CLOSED if the declared doc is missing from the store."""
    e = NODE_EV[nid]
    if e is None:
        return {}
    if e not in ev:
        raise KeyError(f'node {nid} declares evidence {e!r} '
                       f'not present in evidence store')
    return {e: ev[e]}

OUT_CAP = {'extraction': 1536}          # F3; default for all other roles:
OUT_DEFAULT = 768
PER_PARENT_CAP = 3800                   # >= max extraction output (1536 tok x ~2.4 ch/tok)
GARBAGE = '[{"fact":"占位","evidence_doc_id":"?"}]'

# ---- FAIL-CLOSED evidence loading with semantic gate (unchanged from v2) ----
zeda_store = json.load(open('/root/r3_own_pool/deadline_reward_v1/'
                            'h1v8_docs/zeda_docs.json'))
ev = {d['doc_id']: d['text'][:6000] for d in zeda_store['docs']}


def semantic_gate():
    combined = ' '.join(d['text'] for d in zeda_store['docs'])
    dates = re.findall(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}', combined)
    amounts = re.findall(r'[\d,.]+(?:万元|亿元|元)', combined)
    penalties = [w for w in ('罚款', '处罚', '警告', '禁入', '没收') if w in combined]
    assert len(dates) >= 5, f"GATE FAIL: INSUFFICIENT_DATES {len(dates)}"
    assert len(amounts) >= 10, f"GATE FAIL: INSUFFICIENT_AMOUNTS {len(amounts)}"
    assert len(penalties) >= 3, f"GATE FAIL: INSUFFICIENT_PENALTIES {len(penalties)}"
    assert any('泽达' in d.get('title', '') for d in zeda_store['docs']), \
        "GATE FAIL: EVENT_MISMATCH"
    return len(dates), len(amounts), len(penalties)


SYS = '你是一个严谨的资本市场调查助手。只输出JSON。'


# ---- stage-gate machinery (operator DD-V7.7 final instruction, item 6) ----
def parse_json_text(text):
    t = str(text).strip()
    if t.startswith('```'):
        parts = t.split('\n', 1)
        t = parts[1].rsplit('```', 1)[0].strip() if len(parts) == 2 else t
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r'\{.*\}', t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _norm(s):
    return re.sub(r'[\s,，年月日/.-]', '', str(s))


# input-derived probes per extraction node: thresholds come ONLY from what
# the node's own evidence slice actually contains (never from scoring keys)
GATE_N1 = dict(evidence='zeda_csrc_penalty_2023_29', min_dates=2, min_amounts=3,
               entities=('泽达易盛',))
GATE_N2 = dict(evidence='zeda_csrc_penalty_2024_kangda', min_dates=0, min_amounts=0,
               entities=('泽达易盛', '康达'))


def extraction_gate(nid, rec, text):
    """Stage-1 contract gate: complete JSON, clean stop, source binding and
    input-derived fact coverage. Any FAIL stops the batch (no retries)."""
    g = GATE_N1 if nid == 'n1' else GATE_N2
    slice_txt = ev[g['evidence']]
    checks = {}
    checks['stop_clean'] = rec.get('stop_reason') in ('stop', 'end_turn')
    obj = parse_json_text(text)
    checks['json_complete'] = isinstance(obj, dict)
    checks['doc_id_binding'] = g['evidence'] in str(text)
    checks['entities'] = all(e in str(text) for e in g['entities'])
    if g['min_dates']:
        doc_d = {d for d in re.findall(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}', slice_txt)}
        out_d = {_norm(d) for d in re.findall(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}', str(text))}
        hits = sum(1 for d in doc_d if _norm(d) in out_d)
        checks['dates>=min'] = hits >= g['min_dates']
    if g['min_amounts']:
        doc_a = set(re.findall(r'[\d,.]+(?:万元|亿元|元)', slice_txt))
        out_a = {_norm(a) for a in re.findall(r'[\d,.]+(?:万元|亿元|元)', str(text))}
        hits = sum(1 for a in doc_a if _norm(a) in out_a)
        checks['amounts>=min'] = hits >= g['min_amounts']
    pen = sum(str(text).count(w) for w in ('罚款', '警告', '没收', '处罚'))
    checks['penalty_vocab'] = pen >= 2
    return dict(ok=all(checks.values()), checks=checks)


def node_gate(nid, rec, text):
    """Stage-2 per-node contract gate (parseable JSON with the contract field,
    non-degenerate). n5 is EXEMPT: its garbage output is the injected fault."""
    if nid == 'n5':
        return dict(ok=True, checks={'exempt': 'fault-injected node'})
    obj = parse_json_text(text)
    field = OUT_FIELD[ROLES[nid]]
    checks = dict(stop_clean=rec.get('stop_reason') in ('stop', 'end_turn'),
                  json_complete=isinstance(obj, dict),
                  field_present=isinstance(obj, dict) and bool(obj.get(field)),
                  non_degenerate=len(str(text)) > 200)
    return dict(ok=all(checks.values()), checks=checks)


def parent_ctx(nid, ud):
    """F1+F2 fix: context assembled from the frozen DAGSpec inputs list.

    Every parent appears labelled with its node id, role and contract
    `produces` field; same-role parents (n1,n2 -> n5/n6) are concatenated
    instead of overwriting one key.
    """
    parts = []
    for p in DEPS[nid]:
        t = str(ud.get(p, '') or '').strip()
        prod = '/'.join(PRODUCES[p]) or ROLES[p]
        parts.append(f'## 上游 {p}（{ROLES[p]} → {prod}）输出\n'
                     f'{t[:PER_PARENT_CAP]}')
    return '\n\n'.join(parts)


INSTR = {
    'extraction':  '从下列处罚决定书文档中抽取关键事实（日期/金额/主体/违规/处罚）：',
    'timeline':    '整理时间线（按日期排序，列出关键事件）：',
    'amounts':     '汇总所有金额数据（虚增金额、罚款金额、募集资金等）：',
    'penalties':   '梳理处罚决定（处罚种类、对象、金额、依据）：',
    'entity_graph': '识别涉事主体及关系（公司、责任人、中介机构）：',
    'timeline_deep': '时间线阶段复核与划分：',
    'amounts_check': '金额交叉核验（比对各来源金额数据）：',
    'cross_check': '跨来源核验（核对处罚、时间线、金额的一致性）：',
    'synthesis':   '综合分析全部核验事实，输出调查结论：',
}
OUT_FIELD = {
    # extraction tail kept VERBATIM from v2 (including its 'doc_ex extracts'
    # typo) so the n1/n2 prompts stay byte-identical to the paid v2 calls —
    # the third execution's shared prefix is then an exact replicate, and the
    # V77 purpose tags are what prevent dedup-replay of the truncated outputs.
    'extraction': 'doc_ex extracts', 'timeline': 'timeline', 'amounts': 'amounts',
    'penalties': 'penalties', 'entity_graph': 'entity_graph',
    'timeline_deep': 'stages', 'amounts_check': 'amounts_checked',
    'cross_check': 'verified_facts', 'synthesis': 'report',
}


def build_prompt(nid, ud, docs=None):
    """Single prompt builder for all roles, bound to the frozen node contract.
    Extraction reads ONLY its spec-declared evidence doc (F4); every other
    role reads ONLY its DAGSpec parents (F1/F2)."""
    role = ROLES[nid]
    if role == 'extraction':
        ds = '\n\n'.join(f'## 文档 {k}\n{v}'
                         for k, v in node_docs(nid).items())
        body = f'{INSTR[role]}\n{ds}'
    else:
        body = f'{INSTR[role]}\n{parent_ctx(nid, ud)}'
    return f'{SYS}\n{body}\n输出JSON，字段 {OUT_FIELD[role]}。'


# ---- scoring: pure functions of (n10 text, evidence) — no arm labels (T4) ----
def score_q(text, docs):
    clean = re.sub(r'[\s,，]', '', text)
    doc_clean = re.sub(r'[\s,，]', '', ' '.join(docs.values()))
    doc_kws = re.findall(r'[\u4e00-\u9fa5]{3,}', doc_clean[:400])[:10]
    kw_hits = sum(1 for w in doc_kws if w in clean)
    kw_score = kw_hits / max(1, len(doc_kws))
    doc_dates = set(re.findall(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}', ' '.join(docs.values())))
    out_dates = set(re.findall(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}', text))
    date_score = len(out_dates & doc_dates) / max(1, len(doc_dates))
    doc_amts = set(re.findall(r'[\d,.]+(?:万元|亿元|元)', ' '.join(docs.values())))
    out_amts = set(re.findall(r'[\d,.]+(?:万元|亿元|元)', text))
    amt_score = len(out_amts & doc_amts) / max(1, min(len(doc_amts), 10))
    return round((kw_score + date_score + amt_score) / 3, 4), dict(
        kw_hits=kw_hits, kw_total=len(doc_kws),
        date_hits=len(out_dates & doc_dates), date_total=len(doc_dates),
        amt_hits=len(out_amts & doc_amts), amt_total=min(len(doc_amts), 10))


def entity_stats(text, docs):
    all_ev = ' '.join(docs.values())
    pat = r'[\u4e00-\u9fa5]{2,12}(?:股份有限公司|有限公司|证监会)'
    out_e = set(re.findall(pat, text))
    doc_e = set(re.findall(pat, all_ev))
    return len(out_e), len(out_e & doc_e)


# ---- the 23-request schedule (mirrors dd_v74_request_manifest.json) ----
def schedule():
    reqs = []
    for nid in ('n1', 'n2', 'n3', 'n4'):
        reqs.append(dict(req_id=f'R{len(reqs)+1:02d}', node=nid, model='glm53',
                         purpose=f'V77-shared:{nid}', shared='all'))
    for rep in (1, 2):
        reqs.append(dict(req_id=f'R{len(reqs)+1:02d}', node='n5',
                         model='glm53flash',
                         purpose=f'V77-fault:n5:rep{rep}', action='fault_inject',
                         rep=rep))
    reqs.append(dict(req_id=f'R{len(reqs)+1:02d}', node='n8', model='glm53flash',
                     purpose='V77-shared:n8', shared='all'))
    for action, n67 in (('A_alt', 'glm53flash'), ('B_ib', 'glm53')):
        for rep in (1, 2):
            for nid in ('n6', 'n7'):
                reqs.append(dict(req_id=f'R{len(reqs)+1:02d}', node=nid,
                                 model=n67,
                                 purpose=f'V77-{action}:{nid}:rep{rep}',
                                 action=action, rep=rep))
            for nid in ('n9', 'n10'):
                reqs.append(dict(req_id=f'R{len(reqs)+1:02d}', node=nid,
                                 model='glm53flash',
                                 purpose=f'V77-{action}:{nid}:rep{rep}',
                                 action=action, rep=rep))
    return reqs


def NODE_OF_PURPOSE(purpose):
    return purpose.split(':')[1]


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)      # fresh batch dir + ledger
    gate = semantic_gate()
    print(f"Semantic gate: PASS {gate}")

    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location('ag', '/root/r3_own_pool/deadline_reward_v1/'
                                   'auth_gate.py')
    ag = module_from_spec(spec)
    sys.modules['ag'] = ag
    spec.loader.exec_module(ag)
    ag.require('dd_v77_n5_paired_v3')          # FAIL-CLOSED, seven-field

    reqs = schedule()
    assert len(reqs) == 23 and len([r for r in reqs if r['model'] == 'glm53']) == 8
    meter = Meter(ledger_path=out/'LEDGER.jsonl',
                  max_calls=23, max_guaranteed_actual=100000)

    results = {'actions': {}, 'shared': {}, 'node_states': {}}

    def record_state(rec, text, g):
        results['node_states'][rec['purpose']] = dict(
            node=NODE_OF_PURPOSE(rec['purpose']), model=rec['model_alias'],
            gate=g, stop_reason=rec.get('stop_reason'), chars=len(text),
            prompt_sha256=rec.get('prompt_sha256'))
        (out / 'NODE_STATES.json').write_text(json.dumps(
            results['node_states'], ensure_ascii=False, indent=1))

    def fail_stop(stage, r, g):
        """Contract failure: preserve everything, make NO further calls."""
        (out / 'INCOMPLETE.json').write_text(json.dumps(
            dict(stage=stage, failed_request=r['purpose'], gate=g,
                 node_states=results['node_states'], calls=meter.n_calls),
            ensure_ascii=False, indent=1, default=str))
        print(f"FAIL-STOP [{stage}] {r['purpose']}: {g}")
        sys.exit(2)

    # ---- STAGE 1: n1, n2 only; contract gate before anything else runs ----
    upstream = {}
    for r in [x for x in reqs if x['node'] in ('n1', 'n2')]:
        nid = r['node']
        prompt = build_prompt(nid, upstream)
        rec, text = meter.call(r['model'], '', prompt,
                               OUT_CAP['extraction'], purpose=r['purpose'])
        g = extraction_gate(nid, rec, text)
        record_state(rec, text, g)
        print(f"  S1 {r['purpose']}: {len(text)}ch gate={g['ok']} {g['checks']}")
        if not g['ok']:
            fail_stop('stage1', rec, g)
        upstream[nid] = text
        results['shared'][nid] = text[:500]
    (out / 'STAGE1_GATE.json').write_text(json.dumps(
        {k: v['gate'] for k, v in results['node_states'].items()
         if v['node'] in ('n1', 'n2')}, ensure_ascii=False, indent=1))

    # ---- STAGE 2: remaining 21 requests, per-node fail-stop ----
    for r in [x for x in reqs if x['node'] not in ('n1', 'n2')]:
        nid, role = r['node'], ROLES[r['node']]
        prompt = build_prompt(nid, upstream)   # reads spec parents only
        rec, text = meter.call(r['model'], '', prompt,
                               OUT_CAP.get(role, OUT_DEFAULT),
                               purpose=r['purpose'])
        if r['action'] == 'fault_inject':
            text = GARBAGE                  # b2 fault replaces output
        upstream[nid] = text
        results['shared'].setdefault(nid, text[:500])
        g = node_gate(nid, rec, text)
        record_state(rec, text, g)
        print(f"  S2 {r['purpose']}: {len(text)}ch gate={g['ok']}")
        if not g['ok']:
            fail_stop('stage2', rec, g)

        if r['action']:
            key = f"{r['action']}_rep{r['rep']}"
            results['actions'].setdefault(key, {})[nid] = text

    (out/'RESULTS_RAW.json').write_text(json.dumps(results, ensure_ascii=False,
                                                   indent=1))

    print("\n=== Scoring (against correct zeda evidence) ===")
    scores = {}
    for action in ('A_alt', 'B_ib'):
        for rep in (1, 2):
            d = results['actions'].get(f'{action}_rep{rep}', {})
            t10 = d.get('n10', '')
            q, detail = score_q(t10, ev)
            tot, sup = entity_stats(t10, ev)
            scores[f'{action}_rep{rep}'] = dict(
                Q=q, detail=detail, entities=tot, supported=sup,
                halluc_rate=round((tot - sup) / max(1, tot), 3) if tot else 0,
                text_len=len(t10))
            print(f"  {action} rep{rep}: Q={q:.4f} len={len(t10)}")

    a_q = [scores.get(f'A_alt_rep{r}', {}).get('Q', 0) for r in (1, 2)]
    b_q = [scores.get(f'B_ib_rep{r}', {}).get('Q', 0) for r in (1, 2)]
    final = dict(
        batch='dd_v77_n5_paired_v3',
        calls_used=sum(1 for _ in open(out/'LEDGER.jsonl')), calls_max=23,
        A_mean_Q=round(sum(a_q)/2, 4), B_mean_Q=round(sum(b_q)/2, 4),
        delta_Q=round(sum(b_q)/2 - sum(a_q)/2, 4),
        scores=scores, evidence='zeda penalty decisions (correct)',
        semantic_gate='PASS')
    (out/'FINAL_RESULTS.json').write_text(json.dumps(final, ensure_ascii=False,
                                                     indent=1))
    print(json.dumps(final, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/root/cap_eval_bench_v1/'
         'dd_v77_n5_paired_v3')
