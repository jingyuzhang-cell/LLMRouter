"""QP9: Three-arm dynamic recovery experiment (Static / R-only / R+π).

4 tasks × 2 reps × 3 arms. E outputs cached (QP8R + QP4) except ZEDA/ZIJING DS supplement.
SINK and recovery nodes use DeepSeek. R+π switches recovery model per task profile.
Caps: 55 calls / ¥0.32.
"""
import json, os, random, sys, hashlib, time
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
from real_provider_v22 import extract_any
from qp3_primitives import normalize_stage as old_parser
from parser_v2 import normalize_stage_v2_string_values as new_parser
import qp2_chain as CH
import qp3_primitives as P3
import qp5a_pure_prep as PP
import scorer_qp1 as Q1
from qp1_prompts import E_SYS, EVIDENCE_REQ, P_SYS, e_user, MAXTOK

QP9 = '/root/research_outputs/static_pi/stage_d/qp9'
ROOT = '/root/research_outputs/static_pi/stage_d'
SEED = 20261104
CAPS = dict(calls=55, tokens=400_000, yuan=0.32)
TASKS = ['MVR1', 'KANGMEI', 'ZEDA', 'ZIJING']
ARMS = ('A_static', 'B_r_only', 'C_r_pi')

# Preregistered model profiles (from Stage A repairability screening)
MODEL_PROFILE = {
    'MVR1': {'recovery_model': 'deepseek'},     # DS fixes GLM errors
    'KANGMEI': {'recovery_model': 'glm53flash'}, # GLM fixes DS errors
    'ZEDA': {'recovery_model': 'glm53flash'},
    'ZIJING': {'recovery_model': 'glm53flash'},
}

# Preregistered feedback thresholds (same as QP7)
THRESH = dict(evidence_completeness=0.5, fact_retention=0.7, answer_completeness=0.6)

_ledger_path = f'{QP9}/QP9_LEDGER.jsonl'
_calls = 0; _cost = 0.0; _index = {}


def load_contract(t):
    p = [x for x in json.load(open(f'{ROOT}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if x['event_key'] == t][0]['contract']
    if not os.path.isabs(p): p = f'{ROOT}/v23a/{p}'
    return json.load(open(p))


def real_call(alias, system, user, mt, purpose):
    global _calls, _cost
    from stage_d_v2_transport import build_request, glm_key, ds_key, MODEL_CFG
    if _calls >= CAPS['calls']: raise RuntimeError('calls cap')
    if _cost + 0.008 > CAPS['yuan'] * 0.95: raise RuntimeError('cost cap')
    body = build_request(alias, system, user, mt)
    sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    hit = _index.get((purpose, sha))
    if hit is not None: return hit['text'], 0, 0
    import urllib.request
    req = urllib.request.Request(MODEL_CFG[alias]['url'], data=json.dumps(body).encode(), method='POST')
    req.add_header('content-type', 'application/json')
    k = glm_key() if alias == 'glm53flash' else ds_key()
    req.add_header('authorization', 'Bearer ' + k)
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    ch = d['choices'][0]; u = d.get('usage', {})
    c = ch.get('message', {}).get('content', '')
    text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
    tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
    yuan = round(tin * 0.8e-6 + tout * 2.8e-6, 8)
    lat = round(time.monotonic() - t0, 3)
    rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias=alias, purpose=purpose,
                prompt_sha256=sha, usage=dict(input_tokens=tin, output_tokens=tout),
                accounting_yuan=yuan, latency_s=lat, text=text)
    with open(_ledger_path, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    _calls += 1; _cost += yuan
    _index[(purpose, sha)] = {'text': text}
    return text, lat, yuan


def evidence_completeness(obj, contract):
    entries = P3.normalize_stage(obj) if obj else []
    if not entries: return 0.0
    ok = sum(1 for e in entries if e.get('doc') and e.get('quote'))
    return ok / len(entries)


def answer_completeness(sink_obj, contract):
    if not isinstance(sink_obj, dict): return 0.0
    answered = {a.get('fact_id') for a in sink_obj.get('answers', []) if isinstance(a, dict) and a.get('value')}
    return len(answered) / max(1, len(contract['required_facts']))


def get_or_call_e(task, node, model_alias, contract):
    """Get cached E output or make new call."""
    docs = sorted(contract['source_pages'].keys())
    h = (len(docs) + 1) // 2
    e_docs = docs[:h] if node == 'e0' else (docs[h:] or docs[:1])
    system = E_SYS  # fixed prompt (no duplicate EVIDENCE_REQ)
    user = e_user(contract, e_docs, 'E1')
    purpose = f'qp9|{task}|E|{model_alias}|{node}'
    text, lat, yuan = real_call(model_alias, system, user, 2000, purpose)
    return extract_any(text), yuan, lat


def run_cell(arm, task, rep, contract, cached_e):
    cost = 0.0; lat = 0.0; recovery_triggered = False; recovery_node = None
    recovery_model_used = None

    # === E nodes (start with DS for all arms) ===
    e0_obj = cached_e.get(f'DS_e0')
    e1_obj = cached_e.get(f'DS_e1')
    if e0_obj is not None: cost += 0; lat += 0  # cached
    else:
        e0_obj, y, l = get_or_call_e(task, 'e0', 'deepseek', contract); cost += y; lat += l
    if e1_obj is not None: cost += 0; lat += 0
    else:
        e1_obj, y, l = get_or_call_e(task, 'e1', 'deepseek', contract); cost += y; lat += l

    # === Feedback check on E nodes ===
    if arm in ('B_r_only', 'C_r_pi'):
        for ename, eobj in (('e0', e0_obj), ('e1', e1_obj)):
            ec = evidence_completeness(eobj, contract)
            if ec < THRESH['evidence_completeness']:
                recovery_triggered = True; recovery_node = ename
                if arm == 'B_r_only':
                    # Same model re-execution
                    new_obj, y, l = get_or_call_e(task, ename, 'deepseek', contract)
                    cost += y; lat += l; recovery_model_used = 'DS'
                else:
                    # Switch to complementary model
                    switch_to = MODEL_PROFILE[task]['recovery_model']
                    new_obj, y, l = get_or_call_e(task, ename, switch_to, contract)
                    cost += y; lat += l; recovery_model_used = 'GLM' if switch_to == 'glm53flash' else 'DS'
                if ename == 'e0': e0_obj = new_obj
                else: e1_obj = new_obj
                break  # only recover first failing node per prereg

    # === Build evidence table ===
    all_entries = new_parser(e0_obj or {}) + new_parser(e1_obj or {})
    m_facts = {}
    for e in all_entries:
        k = str(e.get('field') or e.get('bucket') or '')
        if k and e.get('value') not in (None, ''):
            m_facts.setdefault(k, e.get('value'))
    verified, _ = CH.verify_evidence(all_entries, contract)

    # === m/r (cached or lightweight) ===
    # Use m_facts directly as merged facts (simplified for SINK)
    # In production these would be model nodes; here we use E output directly
    r_output = {}  # simplified

    # === SINK ===
    ev_map = PP.match_evidence(m_facts, verified, contract)
    prompt = PP.render(contract, r_output, m_facts, ev_map, with_evidence=True)
    purpose = f'qp9|{task}|{arm}|r{rep}|p'
    text, y, l = real_call('deepseek', P_SYS, prompt, MAXTOK['p'], purpose)
    cost += y; lat += l
    sink = extract_any(text)

    # === SINK feedback check (only for B/C) ===
    if arm in ('B_r_only', 'C_r_pi') and sink:
        ac = answer_completeness(sink, contract)
        if ac < THRESH['answer_completeness'] and not recovery_triggered:
            # Re-run SINK with same model (B) or switch (C)
            if arm == 'B_r_only':
                text2, y2, l2 = real_call('deepseek', P_SYS, prompt, MAXTOK['p'], purpose + '_retry')
                cost += y2; lat += l2; recovery_triggered = True; recovery_node = 'p'
                recovery_model_used = 'DS'
                sink = extract_any(text2) or sink
            else:
                switch_to = MODEL_PROFILE[task]['recovery_model']
                text2, y2, l2 = real_call(switch_to, P_SYS, prompt, MAXTOK['p'], purpose + '_switch')
                cost += y2; lat += l2; recovery_triggered = True; recovery_node = 'p'
                recovery_model_used = 'GLM' if switch_to == 'glm53flash' else 'DS'
                sink2 = extract_any(text2)
                if sink2: sink = sink2

    # === Score ===
    if sink:
        res = Q1.score_task(contract, sink)
        q = res['q']
        crit_tp = sum(1 for x in res['rows'] if x.get('critical') and x['status'] == 'TP')
        wa = sum(1 for x in res['rows'] if x['status'].startswith('VALUE'))
        wc = sum(1 for x in res['rows'] if x['status'].startswith('C_LOC') or x['status'] == 'UNSUPPORTED')
        abst = sum(1 for x in res['rows'] if x['status'] == 'ABSENT')
    else:
        q = 0.0; crit_tp = 0; wa = 0; wc = 0; abst = len(contract['required_facts'])

    return dict(task=task, rep=rep, arm=arm, q=q, cost_yuan=round(cost, 6),
                latency_s=round(lat, 2), recovery_triggered=recovery_triggered,
                recovery_node=recovery_node, recovery_model=recovery_model_used,
                crit_tp=crit_tp, wrong_assert=wa, wrong_cit=wc, abstentions=abst)


def main():
    global _index
    # Load existing ledger for cache
    if os.path.exists(_ledger_path):
        for line in open(_ledger_path):
            x = json.loads(line)
            _index[(x['purpose'], x['prompt_sha256'])] = x

    # Pre-load cached E outputs
    stage1_led = {}
    for line in open(f'{ROOT}/qp8/QP8R_STAGE1_LEDGER.jsonl'):
        x = json.loads(line); stage1_led[x['purpose']] = x
    qp4_led = {}
    for line in open(f'{ROOT}/quality_phase_v1/QP4_LEDGER.jsonl'):
        x = json.loads(line); qp4_led[x['purpose']] = x

    contracts = {t: load_contract(t) for t in TASKS}
    cached = {}
    for task in TASKS:
        cached[task] = {}
        # DS E from QP8R (MVR1, KANGMEI) — clean
        for node in ('e0', 'e1'):
            key = f'qp8r|{task}|DS|r1|{node}'
            if key in stage1_led:
                cached[task][f'DS_{node}'] = extract_any(stage1_led[key]['text'])
        # If DS not from QP8R, will be supplemented by new calls

    # Randomize block order
    blocks = []
    for t in TASKS:
        for rep in (1, 2):
            arms = list(ARMS)
            random.Random(SEED + hash(t) % 100 + rep).shuffle(arms)
            for a in arms:
                blocks.append((t, rep, a))

    results = []
    status = 'COMPLETE'
    for task, rep, arm in blocks:
        try:
            r = run_cell(arm, task, rep, contracts[task], cached[task])
            results.append(r)
            print(f"  {task:9s} {arm:10s} r{rep} Q={r['q']:.3f} "
                  f"rec={r['recovery_triggered']} node={r['recovery_node']} "
                  f"model={r['recovery_model']} ¥{r['cost_yuan']:.4f}", flush=True)
        except Exception as e:
            results.append(dict(task=task, rep=rep, arm=arm, error=str(e)[:160]))
            status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
            print(f"  {task} {arm} r{rep} ERROR {e}", flush=True)
            if 'cap' in str(e): break
        json.dump(dict(status=status, used=dict(calls=_calls, yuan=round(_cost, 4)),
                     results=results),
                  open(f'{QP9}/QP9_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{QP9}/QP9_PROGRESS.json.tmp', f'{QP9}/QP9_PROGRESS.json')

    json.dump(dict(batch='QP9_THREE_ARM', status=status, caps=CAPS,
                   used=dict(calls=_calls, yuan=round(_cost, 4)), results=results),
              open(f'{QP9}/QP9_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={_calls}/{CAPS['calls']} ¥{_cost:.4f}/{CAPS['yuan']}")


if __name__ == '__main__':
    main()
