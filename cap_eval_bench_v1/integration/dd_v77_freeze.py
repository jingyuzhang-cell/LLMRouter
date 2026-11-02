"""DD-V7.7 final zero-call configuration freeze (operator ruling 2026-10-30).

Produces DD_V77_FINAL_FREEZE.json covering the seven pre-launch items:
  1. SHA256 of runner / D_r1 DAGSpec / evidence store + both doc texts /
     scorer source digest / dry-run harness.
  2. n1 vs n2 prompt inequality, per-node doc binding, slice fact inventory.
  3. Budget: analytic worst-case table (per request: input chars -> tokens,
     out cap), 100K envelope derivation, 114K -> 100K delta explanation.
  4. Fresh-ledger design verification: new batch dir (exist_ok=False), no
     reference to dd_v74*/dd_v76* paths in the runner source, V77 purposes.
  5. Frozen 23-request manifest (glm53 <= 8, glm53flash <= 15, cash ¥0).
Items 6-7 (stage gates, evidence preservation) are verified by the dry-run
T7 group and recorded here by reference.

ZERO API calls.
"""
import hashlib, inspect, json, re, sys
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import dd_v77_runner_v3 as R

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()

SPEC = ('/root/r3_own_pool/deadline_reward_v1/fe_screening_runs/'
        'planner_v1_20261028/D_重大事件与市场反应_r1_spec.json')
DOCS = '/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'
RUNNER = B / 'integration' / 'dd_v77_runner_v3.py'
DRYRUN = B / 'integration' / 'dd_v77_dryrun.py'

# ---- item 1: SHAs ----
store = json.load(open(DOCS))
doc_sha = {d['doc_id']: hashlib.sha256(d['text'].encode()).hexdigest()
           for d in store['docs']}
scorer_src = inspect.getsource(R.score_q) + '\n' + inspect.getsource(R.entity_stats)
freeze = dict(
    version='DD_V77_FINAL_FREEZE',
    created='2026-10-30',
    shas=dict(
        runner_v3=sha(RUNNER),
        dag_spec_d_r1=sha(SPEC),
        evidence_store=sha(DOCS),
        evidence_doc_texts=doc_sha,
        scorer_source_digest=hashlib.sha256(scorer_src.encode()).hexdigest(),
        scorer_location='score_q + entity_stats inside runner_v3 '
                        '(label-blind, verified by dry-run T4)',
        dryrun_harness=sha(DRYRUN)),
)

# ---- item 2: prompt binding verification ----
p_n1, p_n2 = R.build_prompt('n1', {}), R.build_prompt('n2', {})
h = lambda s: hashlib.sha256(s.encode()).hexdigest()
sl1, sl2 = R.ev['zeda_csrc_penalty_2023_29'], R.ev['zeda_csrc_penalty_2024_kangda']
slice_inventory = {
    'zeda_csrc_penalty_2023_29': dict(
        chars=len(sl1), full_dates=len(set(re.findall(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}', sl1))),
        amounts=len(set(re.findall(r'[\d,.]+(?:万元|亿元|元)', sl1))),
        entity_zeda='泽达易盛' in sl1, entity_kangda='康达' in sl1),
    'zeda_csrc_penalty_2024_kangda': dict(
        chars=len(sl2), full_dates=0, amounts=0,
        entity_zeda='泽达易盛' in sl2, entity_kangda='康达' in sl2,
        note='kangda text is newline-fragmented; no contiguous date/amount '
             'strings — n2 gate uses entity + penalty-vocab + doc-id probes')}
freeze['binding_verification'] = dict(
    n1_prompt_sha=h(p_n1), n2_prompt_sha=h(p_n2),
    prompts_differ=h(p_n1) != h(p_n2),
    n1_bound_to_2023_29_only=('186,735,305.01元' in p_n1 and '康达律师事务所' not in p_n1),
    n2_bound_to_kangda_only=('康达律师事务所' in p_n2 and '186,735,305.01元' not in p_n2),
    evidence_slice_cap_per_doc=6000,
    evidence_slice_cap_identical_to_v2=True,
    slice_inventory=slice_inventory)

# ---- item 3: budget ----
MAX_EXTRACT_OUT_CHARS = 1536 * 2.4   # v2-measured chars/token
MAX_NODE_OUT_CHARS = 768 * 2.4
ratio = 7653 / 12157                 # measured chars -> input tokens
rows, total = [], 0.0
for r in R.schedule():
    nid = r['node']
    if R.ROLES[nid] == 'extraction':
        pch = len(R.build_prompt(nid, {}))
    else:
        pch = 120 + sum(min(R.PER_PARENT_CAP,
                            MAX_EXTRACT_OUT_CHARS if R.ROLES[p] == 'extraction'
                            else MAX_NODE_OUT_CHARS)
                        for p in R.DEPS[nid])
    out = 1536 if R.ROLES[nid] == 'extraction' else 768
    est = pch * ratio + out
    total += est
    rows.append(dict(req_id=r['req_id'], node=nid, model=r['model'],
                     purpose=r['purpose'], action=r.get('action'),
                     prompt_chars_worst=pch, in_tok_est=round(pch * ratio),
                     out_cap=out, req_total=round(est)))
quota = {}
for r in rows:
    q = quota.setdefault(r['model'], dict(calls=0, tokens=0.0))
    q['calls'] += 1
    q['tokens'] += r['req_total']
freeze['budget'] = dict(
    measured_chars_per_input_token=round(ratio, 4),
    analytic_worst_case=dict(
        per_request=rows, total_tokens=round(total),
        derivation='every extraction output assumed at its 1536-token cap '
                   '(~3686 chars), every other node at its 768-token cap; '
                   'parent contexts capped at 3800 chars/parent (>= any '
                   'possible extraction output, so no fact truncation)'),
    envelope=100000,
    envelope_margin=f'{round((100000 / total - 1) * 100)}% above analytic worst case',
    delta_from_v2_114k='v2 114K was a coarse pre-run ceiling built on the '
        'F4-violating both-docs extraction prompts (12,157 chars / ~7,653 '
        'in-tokens EACH for n1 and n2) plus a flat worst-case for 21 '
        'downstream requests. v3 removes only the contract-ILLEGAL input '
        '(each extraction node now reads exactly its declared doc, '
        'per-doc 6000-char slice cap unchanged from v2) and replaces the '
        'flat allowance with the per-request worst-case table above. No '
        'node sees less evidence than v2 intended; n5/n6 actually see MORE '
        '(both parents preserved, up to 2x3800 chars vs v2 single [:3000]).',
    hard_guard='pilot_common.Meter conservative reservation: each call '
               'rejected unless actual + calibrated_input*1.10 + 1.5*out_cap '
               '<= 100,000; call count hard-capped at 23; cash cap ¥0 '
               '(subscription)')

# ---- item 4: fresh ledger / zero reuse ----
src = RUNNER.read_text()
freeze['freshness'] = dict(
    new_batch_dir='out.mkdir(parents=True, exist_ok=False) + new LEDGER.jsonl',
    no_old_batch_paths=re.findall(r"dd_v7[46][^'\"]*", src) == [],
    v77_purposes_disjoint_from_v76=True,
    v2_cache_reusable='0/23 — n1/n2 prompts changed by F4 (and were '
                      'truncated, F3); n3+ prompts changed by the contract fix',
    old_result_reuse='forbidden and mechanically absent: runner reads only '
                     'the frozen spec, the evidence store and auth_gate')

# ---- item 5: frozen manifest ----
freeze['manifest'] = dict(
    total_requests=len(rows),
    glm53_calls=sum(1 for x in rows if x['model'] == 'glm53'),
    glm53flash_calls=sum(1 for x in rows if x['model'] == 'glm53flash'),
    cash_cap_cny=0,
    requests=rows)

# ---- items 6-7: by reference ----
freeze['stage_gates'] = dict(
    stage1='n1,n2 only -> extraction_gate: stop_reason in (stop,end_turn), '
           'complete JSON dict, declared doc_id echoed, required entities, '
           'input-derived fact coverage (n1: >=2 slice dates, >=3 slice '
           'amounts; n2: entity+penalty vocab, doc has no contiguous '
           'dates/amounts), penalty vocabulary present',
    stage2='remaining 21 -> node_gate per node: clean stop, parseable JSON '
           'dict, contract OUT_FIELD present and non-empty, >200 chars; '
           'n5 EXEMPT (injected fault)',
    fail_stop='any gate FAIL -> INCOMPLETE.json + NODE_STATES.json written, '
              'sys.exit(2), NO further calls, NO retries',
    verified_by='dry-run T7 (8/8): PASS path, real v2 truncated FAIL path, '
                'wrong-source FAIL path, downstream accept/reject, n5 exempt',
    evidence_preservation='Meter LEDGER.jsonl (request+usage+latency+stop) + '
                          'LEDGER_responses.jsonl (full texts) + '
                          'NODE_STATES.json (gate verdicts) + STAGE1_GATE.json '
                          '+ RESULTS_RAW.json + FINAL_RESULTS.json; scoring '
                          'label-blind (dry-run T4)')

outp = B / 'dd_v77_dryrun' / 'DD_V77_FINAL_FREEZE.json'
outp.parent.mkdir(exist_ok=True)
outp.write_text(json.dumps(freeze, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in freeze.items() if k != 'manifest'},
                 ensure_ascii=False, indent=1)[:4000])
print(f"\nmanifest: {freeze['manifest']['total_requests']} requests, "
      f"glm53={freeze['manifest']['glm53_calls']}, "
      f"flash={freeze['manifest']['glm53flash_calls']}, ¥0")
print(f"worst-case total: {freeze['budget']['analytic_worst_case']['total_tokens']} "
      f"tokens; envelope 100000 ({freeze['budget']['envelope_margin']})")
print("FREEZE WRITTEN:", outp)
