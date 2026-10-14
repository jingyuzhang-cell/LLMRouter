"""Recovery gate v1.1 (zero calls) - fixes the four decision-modeling
defects identified in the operator review of v1:

  1. LOCAL_REPAIR is VERIFICATION-BASED: the fence-stripped output
     must pass the full node contract (JSON -> per-node fields ->
     citation validity); its quality estimate is the ORIGINAL model's
     pessimistic prior - fence removal adds contract compliance,
     NEVER semantic quality. Its advantage is exactly zero
     cost/time, nothing else.
  2. Downstream is NODE-AWARE: each faulted node's remaining DAG
     (fe->{tl,xc}, tl->{xc}, er->{xc}, xc->{}) carries real
     per-(node,model) planned latencies from the paid logs; quality
     propagates multiplicatively.
  3. On-time probability is EMPIRICALLY CALIBRATED with Laplace
     shrinkage over the real latency SAMPLES (deepseek n=7: a 100%
     point estimate shrinks conservatively; tiny n never yields
     near-certain claims).
  4. Both terminal paths computed: ACCEPT (keep current output +
     downstream) vs TERMINATE (end the task now with the partial
     result). STOP is a real action.

Run: python3 -m deadline_reward_v1.recovery_gate
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = (HERE / 'fe_screening_runs'
       / 'restricted_dag_20261014_093559')

LAMBDA_C, LAMBDA_T, LAMBDA_F = 0.5, 1.0, 2.0
C0 = 60000.0

EDGES = {'fe': ['tl'], 'tl': ['xc'], 'er': ['xc'], 'xc': []}
CITATION_FIELDS = {'fe': ('evidence_doc_id',), 'tl': ('evidence',),
                   'er': ('evidence_doc_id',),
                   'xc': ('source_a', 'source_b')}


def _downstream(node):
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        for m in EDGES[n]:
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def strip_fence(text):
    t = (text or '').strip()
    if t.startswith('```'):
        p = t.split('\n', 1)
        if len(p) == 2:
            t = p[1].rsplit('```', 1)[0].strip()
    return t


def parse_layers(answer):
    a = (answer or '').strip()
    try:
        return 'STRICT', json.loads(a)
    except (ValueError, TypeError):
        pass
    t = strip_fence(a)
    try:
        return 'FENCE', json.loads(t)
    except (ValueError, TypeError):
        return 'FAIL', None


def contract_items(parsed):
    items = parsed if isinstance(parsed, list) else (
        (parsed.get('facts') or parsed.get('timeline')
         or parsed.get('relations') or parsed.get('claims') or [])
        if isinstance(parsed, dict) else [])
    return items if isinstance(items, list) else []


VERDICTS = ('SUPPORTED', 'UNSUPPORTED', 'CONFLICT')


def _src_ref(v, expected_doc_ids):
    """A valid source reference: a string id in the stated set, OR a
    dict carrying evidence_doc_id in the set (xc nested sources).
    A bare date/event is NOT a valid evidence identity."""
    if isinstance(v, str):
        return v in expected_doc_ids if expected_doc_ids else bool(v)
    if isinstance(v, dict):
        ref = v.get('evidence_doc_id')
        return (isinstance(ref, str)
                and (ref in expected_doc_ids if expected_doc_ids
                     else bool(ref)))
    return False


def _valid_item(it, node_type, expected_doc_ids):
    """Full per-node schema check: required fields, types, citation
    identity, verdict enum (xc)."""
    if not isinstance(it, dict):
        return False
    if node_type == 'fe':
        if not isinstance(it.get('fact'), str) or not it['fact']:
            return False
        return _src_ref(it.get('evidence_doc_id'), expected_doc_ids)
    if node_type == 'tl':
        if not isinstance(it.get('event'), str) or not it['event']:
            return False
        d = it.get('date')
        if d is not None and not isinstance(d, str):
            return False
        return _src_ref(it.get('evidence'), expected_doc_ids)
    if node_type == 'er':
        if not isinstance(it.get('entity'), str) or not it['entity']:
            return False
        return _src_ref(it.get('evidence_doc_id'), expected_doc_ids)
    if node_type == 'xc':
        if not isinstance(it.get('claim'), str) or not it['claim']:
            return False
        if it.get('verdict') not in VERDICTS:
            return False
        return (_src_ref(it.get('source_a'), expected_doc_ids)
                and _src_ref(it.get('source_b'), expected_doc_ids))
    return False


def verify_local_repair(answer, node_type, expected_doc_ids,
                        finish_reason=None):
    """Deterministic verification of the fence-stripped output
    against the FULL node contract (schema + types + citation
    identity + verdict enum). Fence normalization removes EXTERNAL
    FORMAT ONLY - the content is byte-identical after stripping.

    A response whose finish_reason is a CUT marker (max_tokens /
    length) is REFUSED: a truncated response keeps its true
    completion status and is never locally re-labeled as naturally
    finished (operator task 1)."""
    checks = dict(finish_reason=finish_reason)
    if finish_reason in ('max_tokens', 'length'):
        checks['refused'] = ('truncated responses are not locally '
                             'repairable')
        return False, None, checks
    layer, parsed = parse_layers(answer)
    checks['parse_layer'] = layer
    if parsed is None:
        return False, None, checks
    items = contract_items(parsed)
    checks['nonempty'] = bool(items)
    if not items:
        return False, None, checks
    schema_ok = all(_valid_item(it, node_type, expected_doc_ids)
                    for it in items)
    checks['schema_ok'] = schema_ok
    if not schema_ok:
        return False, None, checks
    repaired = (strip_fence(answer) if layer == 'FENCE'
                else (answer or '').strip())
    # semantic preservation is structural: the repaired text is the
    # original with ONLY the fence markers removed
    checks['content_preserved'] = (repaired.replace('\n', '')
                                   in answer.replace('\n', ''))
    return checks['content_preserved'], repaired, checks


def load_samples():
    lat, tok, node_lat = {}, {}, {}
    for arm in ('SS-Tuned', 'Fixed-Tuned', 'DD-Online'):
        p = RUN / f'DAG_LEDGER_{arm}.jsonl'
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            k = (e['model'], e['tag'])
            lat.setdefault(k, []).append(e['latency_s'])
            tok.setdefault(k, []).append(
                e['usage']['prompt_tokens']
                + e['usage']['completion_tokens'])
            node_lat.setdefault((e['node'], e['tag']),
                                []).append(e['latency_s'])
    return lat, tok, node_lat


LAT, TOK, NODE_LAT = load_samples()


def p_on_time(model, tag, budget_s):
    """Empirical on-time probability, Laplace-shrunk:
    (hits+1)/(n+2) - small n stays conservative."""
    s = LAT.get((model, tag))
    if not s or budget_s <= 0:
        return 0.0
    hits = sum(1 for x in s if x <= budget_s)
    return round((hits + 1) / (len(s) + 2), 3)


def lat_med(model, tag):
    s = sorted(LAT.get((model, tag), [30.0]))
    return s[len(s) // 2]


def _dag_on_time(nodes, budget_s):
    """DAG-level on-time estimate: product of per-call Laplace-
    shrunk estimates over the remaining chain. This is a shrinkage
    approximation, NOT a validated joint-probability calibration
    (operator task 3)."""
    p = 1.0
    for n in nodes:
        s = NODE_LAT.get((n, 'planned'))
        if not s:
            continue
        med = sorted(s)[len(s) // 2]
        # remaining budget minus this call's median
        budget_s = budget_s - med
        p *= p_on_time('qwen-plus' if n == 'xc' else 'GLM-5.3',
                       'planned', budget_s)
    return round(max(0.0, p), 3)


def downstream_time(node):
    total, detail = 0.0, {}
    for d in sorted(_downstream(node)):
        s = sorted(NODE_LAT.get((d, 'planned'), [20.0]))
        med = s[len(s) // 2]
        total += med
        detail[d] = med
    return total, detail


def utility(q, tokens, T, D):
    c = tokens / C0
    if T <= D:
        return round(q - LAMBDA_C * c, 6)
    return round(-LAMBDA_C * c - LAMBDA_T * (T - D) / D - LAMBDA_F, 6)


def q_prior(model):
    tbl = {'GLM-5.3': 0.34 * 0.316,
           'GLM-5.3-Flash': 0.34 * 0.367,
           'deepseek-flash': 0.75 * 0.286,
           'qwen-plus': 0.566 * 0.226}
    return tbl.get(model, 0.15)


def gate(node, fault, answer, node_type, original_model, clock_t,
         deadline, tokens_spent, expected_doc_ids, downstream_q=0.12,
         rate_overrides=None):
    remaining = deadline - clock_t
    d_time, d_detail = downstream_time(node)
    d_nodes = len(_downstream(node))
    unaffected = 3 - d_nodes
    acts = {}

    def q_task(slot_q):
        return (slot_q + d_nodes * downstream_q * slot_q
                + unaffected * downstream_q) / 4

    # TERMINATE: end the task now. Quality follows the FROZEN
    # settlement semantics: nodes that never ran count as semantic 0
    # (they are NOT averaged away) - identical to how the terminal
    # scorer treats missing/contract-failed nodes.
    q_partial = (q_prior(original_model) + unaffected * downstream_q
                 + d_nodes * 0.0) / 4
    acts['TERMINATE'] = dict(
        eU=utility(q_partial, tokens_spent, clock_t, deadline),
        cost_tok=0, time_s=0.0,
        note='end task now; missing nodes count 0 (frozen '
             'settlement semantics)')

    # ACCEPT: keep the current output, run downstream
    acc_slot = q_prior(original_model) if fault == 'OK' else 0.02
    acc_q = q_task(acc_slot)
    acc_tok = 3000
    acc_p = _dag_on_time(['xc'] if node in ('tl', 'er')
                         else (['tl', 'xc'] if node == 'fe' else []),
                         remaining)
    acts['ACCEPT'] = dict(
        eU=(acc_p * utility(acc_q, tokens_spent + acc_tok,
                            clock_t + d_time, deadline)
            + (1 - acc_p) * utility(
                acc_q * 0.6, tokens_spent + acc_tok,
                clock_t + d_time + 30.0, deadline)),
        cost_tok=acc_tok, time_s=d_time,
        note=f'downstream {d_detail} at real latencies')

    # LOCAL_REPAIR: verified only; q = original model prior (no
    # semantic boost from fence removal)
    if fault == 'FENCE_ONLY':
        ok, repaired, checks = verify_local_repair(
            answer, node_type, expected_doc_ids)
        acts['_local_verify'] = dict(ok=ok, checks=checks)
        if ok:
            q_loc = q_task(q_prior(original_model))
            p_loc = _dag_on_time(['xc'] if node in ('tl', 'er')
                                 else (['tl', 'xc'] if node == 'fe'
                                       else []), remaining)
            acts['LOCAL_REPAIR'] = dict(
                eU=(p_loc * utility(q_loc, tokens_spent,
                                    clock_t + d_time, deadline)
                    + (1 - p_loc) * utility(
                        q_loc * 0.6, tokens_spent,
                        clock_t + d_time + 30.0, deadline)),
                cost_tok=0, time_s=0.0,
                note='verified fence fix; q=original model prior; '
                     'advantage = zero cost/time only')

    # ACCEPT baseline (for reporting dEU), NOT the failure branch:
    # a FAILED action has already burned its tokens/time and then
    # continues from the degraded state (operator fix 2)
    acc_eU = acts['ACCEPT']['eU']
    econ = json.loads((HERE / 'RECOVERY_ECONOMETRICS.json')
                      .read_text())['action_outcomes'] \
        if (HERE / 'RECOVERY_ECONOMETRICS.json').exists() else {}
    for model, tag in (('deepseek-flash', 'repair'),
                       ('GLM-5.3', 'repair'),
                       ('GLM-5.3-Flash', 'repair'),
                       ('qwen-plus', 'fallback')):
        if (model, tag) not in LAT:
            continue
        med = lat_med(model, tag)
        s = LAT[(model, tag)]
        p = p_on_time(model, tag, max(0.0, remaining - d_time))
        if p <= 0.05:
            continue
        # action SUCCESS RATE: E-arm store override > frozen
        # econometric Laplace rate — this is the learning channel
        if rate_overrides and (model, tag) in rate_overrides:
            rate = rate_overrides[(model, tag)]
            rate_src = 'store-updated'
        else:
            e = econ.get(f'{model}|{tag}')
            # standard Laplace shrinkage on the econometric counts:
            # (ok+1)/(n+2) — always within [0,1]
            rate = ((e['ok'] + 1) / (e['n'] + 2)
                    if e and e.get('n') else 0.5)
            rate_src = 'frozen-econometric'
        toks = sorted(TOK[(model, tag)])[len(s) // 2]
        q_fix = q_task(q_prior(model))
        # SUCCESS: the call lands; downstream proceeds on the fix
        e_succ = (p * utility(q_fix, tokens_spent + toks,
                              clock_t + med + d_time, deadline)
                  + (1 - p) * utility(
                      q_fix * 0.6, tokens_spent + toks,
                      clock_t + med + d_time + 30.0, deadline))
        # FAILURE: the call's tokens AND time are already spent;
        # the task continues from the degraded output (ACCEPT
        # semantics), not from the pre-call state
        q_deg = q_task(0.02)
        e_fail = (p * utility(q_deg, tokens_spent + toks,
                              clock_t + med + d_time, deadline)
                  + (1 - p) * utility(
                      q_deg, tokens_spent + toks,
                      clock_t + med + d_time + 30.0, deadline))
        acts[f'{tag.upper()}:{model}'] = dict(
            eU=round(rate * e_succ + (1 - rate) * e_fail, 6),
            cost_tok=toks, time_s=med + d_time,
            on_time_p=p, action_rate=round(rate, 3),
            rate_source=rate_src, n_samples=len(s),
            note=f'p_on_time={p} (shrinkage), action_rate={rate} '
                 f'({rate_src})')

    best = max((k for k in acts if not k.startswith('_')),
               key=lambda k: acts[k]['eU'])
    base = acts['ACCEPT']['eU']
    return dict(decision=best,
                deltaEU_vs_accept=round(acts[best]['eU'] - base, 6),
                actions={k: (dict(v, dEU_vs_accept=round(
                    v['eU'] - base, 4)) if 'eU' in v else v)
                    for k, v in acts.items()},
                state=dict(node=node, fault=fault, clock_t=clock_t,
                           deadline=deadline,
                           remaining_s=round(remaining, 1),
                           downstream=d_detail,
                           tokens_spent=tokens_spent))


# ---- T01 full re-simulation (state-forward, honest reporting) -----
def t01_resim():
    """Re-simulates T01 FORWARD: gate decisions change the state.
    LOCAL_REPAIR outcomes are DETERMINISTIC FACTS (verified on the
    real logged answers); model-replacement outcomes are PREDICTIONS
    (intervals over real latency samples), never claimed as facts."""
    led = RUN / 'DAG_LEDGER_DD-Online.jsonl'
    es = [json.loads(l) for l in led.read_text().splitlines()
          if l.strip()]
    t01 = [e for e in es if e['task'] == 'T01']
    D = t01[0]['deadline_s']
    # real doc id from the frozen task definitions
    from deadline_reward_v1 import full_dag_tasks as _fdt
    doc_id = next(t['doc_id'] for t in _fdt.build_tasks()
                  if t['task_id'] == 'T01')
    assert doc_id, 'T01 doc_id not resolvable'
    planned_pi = dict(fe='GLM-5.3', tl='GLM-5.3',
                      er='deepseek-flash', xc='qwen-plus')
    # deterministic part: which planned faults are fence-only and
    # locally verifiable (FACTS from the real answers)
    facts = []
    for e in t01:
        if e['tag'] != 'planned':
            continue
        layer, parsed = parse_layers(e['answer'])
        fault = ('OK' if layer == 'STRICT'
                 else 'TRUNCATED' if e['finish_reason'] in
                 ('length', 'max_tokens')
                 else 'FENCE_ONLY' if layer == 'FENCE' else 'INVALID')
        ok, repaired, checks = verify_local_repair(
            e['answer'], e['node'], {doc_id})
        facts.append(dict(node=e['node'], fault=fault,
                          local_verifiable=bool(
                              fault == 'FENCE_ONLY' and ok),
                          checks=checks))
    # predicted savings interval for the model-replacement on fe
    fe_glm = sorted(LAT.get(('GLM-5.3-Flash', 'repair'), []))
    ds = sorted(LAT.get(('deepseek-flash', 'repair'), []))
    return dict(
        deadline_s=D, doc_id=doc_id,
        deterministic_facts=facts,
        prediction=dict(
            fe_model_replacement=dict(
                ds_repair_lat_range=[ds[0], ds[-1]] if ds else None,
                glm_repair_lat_range=[fe_glm[0], fe_glm[-1]]
                if fe_glm else None,
                note='model-substitution outcomes are PREDICTION '
                     'INTERVALS over real samples, not verified '
                     'counterfactuals'),
            note='only local-repair savings are deterministic; the '
                 '~20-30s completion claim from v1 is WITHDRAWN '
                 'as unverified'))


def main():
    out = dict(
        version='RECOVERY_GATE_v1_1', zero_model_calls=True,
        fixes=['verification-based LOCAL_REPAIR (no semantic boost; '
               'advantage = zero cost only)',
               'node-aware downstream at real per-(node,model) '
               'planned latencies',
               'empirical Laplace-shrunk on-time probability '
               '(deepseek n=7 conservative)',
               'TERMINATE implemented alongside ACCEPT'],
        t01_resimulation=t01_resim())
    (HERE / 'RECOVERY_GATE_V11.json').write_text(
        json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out['fixes'], indent=1, ensure_ascii=False))
    print('\nT01 re-simulation deterministic facts:')
    for f in out['t01_resimulation']['deterministic_facts']:
        print(f"  {f['node']}: fault={f['fault']} "
              f"locally_verifiable={f['local_verifiable']} "
              f"checks={f['checks']}")
    print('v1 的"20-30s 完成"声明已撤回（未验证的反事实）。',
          '模型替换仅报预测区间。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
