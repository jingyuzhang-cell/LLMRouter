"""Evidence gating experiment: G0 (never provide) / G1 (always provide) / G2 (gated).

Upstream: cached DAG single_ds + format adaptation (adapt_runner outputs).
G2 gate (preregistered, frozen): provide evidence table IFF verified entries
cover >=40% of gold facts; below threshold, SINK runs free-form (like G0).
Conflict check: if a fact has >1 distinct value-equivalence class among its
verified entries, that fact's entry is withheld from the table.
30-36 calls (SINK only). Caps: 42 calls / ¥0.25.
"""
import json, os, random, sys, hashlib, time, re
from decimal import Decimal
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp4_factorial as F
import qp1_prompts as P1
import qp3_primitives as P3
import qp2_chain as CH
import qp2_amount as AM
import qp5a_pure_prep as PP
import scorer_qp1 as Q1
from adapt_runner import adapt_ds_output, extract_value_gold_blind, load_dag_ledger
from real_provider_v22 import extract_any

DAG = '/root/research_outputs/static_pi/stage_d/dag_exp'
SEED = 20261104
CAPS = dict(calls=42, tokens=300_000, yuan=0.25)
GATE_THRESHOLD = 0.40  # preregistered: provide evidence iff coverage >= 40%

_ledger_path = f'{DAG}/GATE_LEDGER.jsonl'
_calls = 0
_cost = 0.0


def value_classes(entries):
    """Distinct value-equivalence classes (unit-normalized, gold-blind)."""
    classes = []
    for e in entries:
        v = e.get('raw') or e.get('value')
        if v is None:
            continue
        a = P3.deco_amount(v)
        if a:
            from qp2_amount import to_yuan
            canon = ('pct', a[0]) if a[1] == '%' else ('yuan', to_yuan(a[0], a[1]))
        else:
            canon = ('txt', P3._norm(v))
        placed = False
        for c in classes:
            ca = P3.deco_amount(c)
            if ca and a:
                cc = ('pct', ca[0]) if ca[1] == '%' else ('yuan', to_yuan(ca[0], ca[1]))
                if canon[0] == cc[0] and abs(canon[1] - cc[1]) <= max(abs(cc[1]) * Decimal('0.001'), Decimal('1')):
                    placed = True; break
            elif P3._norm(v) == P3._norm(c):
                placed = True; break
        if not placed:
            classes.append(v)
    return classes


def build_gated_table(contract, verified, m_facts):
    """G2 gate: check coverage, filter conflicts, return table or None."""
    n_facts = len(contract['required_facts'])
    # coverage: how many gold facts have at least one verified entry?
    covered = set()
    for f in contract['required_facts']:
        for e in verified:
            if P3.name_matches(e, f) or Q1.value_in_quote(f.get('value'), e.get('quote', '')):
                covered.add(f['fact_id'])
                break
    coverage = len(covered) / n_facts
    # gate decision
    if coverage < GATE_THRESHOLD:
        return None, dict(coverage=round(coverage, 3), action='gate_closed', covered=len(covered), total=n_facts)
    # conflict filtering: for each fact with multiple entries, check value classes
    filtered = []
    conflicts_removed = 0
    for e in verified:
        # find which fact this entry belongs to
        matched_f = None
        for f in contract['required_facts']:
            if P3.name_matches(e, f) or Q1.value_in_quote(f.get('value'), e.get('quote', '')):
                matched_f = f; break
        if matched_f is None:
            filtered.append(e)  # unbound entry, keep (harmless)
            continue
        # get all verified entries for this fact
        fact_entries = [v for v in verified
                        if P3.name_matches(v, matched_f) or Q1.value_in_quote(matched_f.get('value'), v.get('quote', ''))]
        if len(fact_entries) > 1:
            classes = value_classes(fact_entries)
            if len(classes) > 1:
                conflicts_removed += 1
                continue  # withhold conflicting entry
        filtered.append(e)
    return filtered, dict(coverage=round(coverage, 3), action='gate_open',
                          covered=len(covered), total=n_facts, conflicts_removed=conflicts_removed)


def run_cell(arm, task, rep, contract, dag_led, tr):
    key = f'dag|{task}|single_ds|r{rep}|'
    if key + 'e0' not in dag_led or key + 'p' in dag_led and 'ZEDA' in task and rep == 2:
        # ZEDA r2 was cost-capped in the DAG experiment
        return dict(task=task, rep=rep, arm=arm, error='upstream_missing')
    e0_raw = extract_any(dag_led[key + 'e0']['text'])
    e1_raw = extract_any(dag_led[key + 'e1']['text'])
    m = extract_any(dag_led[key + 'm']['text'])
    r = extract_any(dag_led[key + 'r']['text'])

    raw_entries = P3.normalize_stage(e0_raw) + P3.normalize_stage(e1_raw)
    adapted = adapt_ds_output(e0_raw) + adapt_ds_output(e1_raw)
    verified, _ = CH.verify_evidence(adapted, contract)

    m_facts = {}
    for e in P3.normalize_stage(m):
        k = PP.fact_key(e)
        if k and e.get('value') not in (None, ''):
            m_facts.setdefault(k, e.get('value'))

    gate_info = dict(action='n/a')
    if arm == 'G0':
        ev_map = {}
        p_user = PP.render(contract, r, m_facts, ev_map, with_evidence=False)
    elif arm == 'G1':
        ev_map = PP.match_evidence(m_facts, verified, contract)
        p_user = PP.render(contract, r, m_facts, ev_map, with_evidence=True)
    elif arm == 'G2':
        table, gate_info = build_gated_table(contract, verified, m_facts)
        if table is not None:
            ev_map = PP.match_evidence(m_facts, table, contract)
            p_user = PP.render(contract, r, m_facts, ev_map, with_evidence=True)
        else:
            ev_map = {}
            p_user = PP.render(contract, r, m_facts, ev_map, with_evidence=False)

    purpose = f'gate|{task}|{arm}|r{rep}|p'
    from stage_d_v2_transport import build_request
    body = build_request('deepseek', P1.P_SYS, p_user, P1.MAXTOK['p'])
    sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    hit = tr.get((purpose, sha))
    if hit:
        text = hit['text']; yuan = 0; lat = 0
    else:
        text, lat, yuan = real_call('deepseek', P1.P_SYS, p_user, P1.MAXTOK['p'], purpose, sha, tr)

    sink = extract_any(text)
    res = Q1.score_task(contract, sink)
    return dict(task=task, rep=rep, arm=arm, q=res['q'],
                gate=res['critical_gate'], gate_info=gate_info,
                n_verified=len(verified), n_ev_map=len(ev_map),
                wrong_assert=sum(1 for x in res['rows'] if x['status'].startswith('VALUE')),
                wrong_cit=sum(1 for x in res['rows'] if x['status'].startswith('C_LOC') or x['status'] == 'UNSUPPORTED'),
                abst=sum(1 for x in res['rows'] if x['status'] == 'ABSENT'),
                crit_tp=sum(1 for x in res['rows'] if x.get('critical') and x['status'] == 'TP'),
                cost_yuan=yuan, latency_s=lat)


def real_call(alias, system, user, mt, purpose, sha, tr):
    global _calls, _cost
    if _calls >= CAPS['calls']:
        raise RuntimeError('calls cap')
    if _cost + 0.006 > CAPS['yuan'] * 0.95:
        raise RuntimeError('cost cap')
    import urllib.request
    from stage_d_v2_transport import ds_key, MODEL_CFG
    body = __import__('stage_d_v2_transport').build_request(alias, system, user, mt)
    req = urllib.request.Request(MODEL_CFG[alias]['url'],
                                 data=json.dumps(body).encode(), method='POST')
    req.add_header('content-type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + ds_key())
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as resp:
        d = json.loads(resp.read().decode())
    ch = d['choices'][0]; u = d.get('usage', {})
    c = ch.get('message', {}).get('content', '')
    text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
    tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
    yuan = round(tin * 0.8e-6 + tout * 2.8e-6, 8)
    lat = round(time.monotonic() - t0, 3)
    rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias=alias, purpose=purpose,
               prompt_sha256=sha, usage=dict(input_tokens=tin, output_tokens=tout),
               accounting_yuan=yuan, latency_s=lat, text=text)
    with open(_ledger_path, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    _calls += 1; _cost += yuan
    tr[(purpose, sha)] = {'text': text}
    return text, lat, yuan


def main():
    dag_led = load_dag_ledger()
    tr = {}
    if os.path.exists(_ledger_path):
        for line in open(_ledger_path):
            x = json.loads(line)
            tr[(x['purpose'], x['prompt_sha256'])] = x

    blocks = []
    for t in F.TASKS:
        for rep in (1, 2):
            arms = ['G0', 'G1', 'G2']
            random.Random(SEED + hash(t) % 100).shuffle(arms)
            for a in arms:
                blocks.append((t, rep, a))

    results = []
    status = 'COMPLETE'
    for t, rep, arm in blocks:
        try:
            contract = F.load_contract(t)
            r = run_cell(arm, t, rep, contract, dag_led, tr)
            if 'error' in r:
                results.append(r)
                print(f"  {t:9s} {arm} r{rep} SKIP ({r['error']})", flush=True)
                continue
            results.append(r)
            gi = r.get('gate_info', {})
            print(f"  {t:9s} {arm} r{rep} Q={r['q']:.3f} verified={r['n_verified']:2d} "
                  f"ev={r['n_ev_map']:2d} gate={gi.get('action','?'):11s} "
                  f"cov={gi.get('coverage','?')}", flush=True)
        except Exception as e:
            results.append(dict(task=t, rep=rep, arm=arm, error=str(e)[:160]))
            status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
            print(f"  {t} {arm} r{rep} ERROR {e}", flush=True)
            break
        json.dump(dict(status=status, used=dict(calls=_calls, yuan=round(_cost, 4)), results=results),
                  open(f'{DAG}/GATE_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{DAG}/GATE_PROGRESS.json.tmp', f'{DAG}/GATE_PROGRESS.json')

    json.dump(dict(batch='EVIDENCE_GATING', status=status, caps=CAPS,
                   gate_threshold=GATE_THRESHOLD,
                   used=dict(calls=_calls, yuan=round(_cost, 4)),
                   results=results),
              open(f'{DAG}/GATE_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={_calls}/{CAPS['calls']} ¥{_cost:.4f}/{CAPS['yuan']}")


if __name__ == '__main__':
    main()
