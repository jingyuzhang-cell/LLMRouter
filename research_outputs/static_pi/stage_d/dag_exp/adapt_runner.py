"""Format adaptation causal verification: A (raw DS) vs B (adapted DS).

Upstream: cached DAG single_ds e0/e1 outputs (identical for both arms).
Adaptation: code-level mapping of DS nested {bucket: [{doc,page,quote}]} → flat
{field, value, doc, page, quote}; value extracted gold-blindly from quote
(deterministic: dates→ISO, numbers→bare, text→longest non-ambiguously grounded
token). Ambiguous values left as None (never guessed).
SINK: same model, same prompt, same evidence table builder, same scorer.
24 calls (12 cells × 2 arms). Caps: 30 calls / ¥0.20.
"""
import json, os, random, sys, hashlib, re
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp4_factorial as F
import qp1_prompts as P1
import qp3_primitives as P3
import qp2_chain as CH
import qp5a_pure_prep as PP
import scorer_qp1 as Q1
from decimal import Decimal
from real_provider_v22 import extract_any

ROOT = '/root/research_outputs/static_pi/stage_d'
QP = f'{ROOT}/quality_phase_v1'
DAG = f'{ROOT}/dag_exp'
SEED = 20261104
CAPS = dict(calls=30, tokens=200_000, yuan=0.20)


def load_dag_ledger():
    led = {}
    for line in open(f'{DAG}/DAG_LEDGER.jsonl'):
        x = json.loads(line)
        led[x['purpose']] = x
    return led


def extract_value_gold_blind(quote, bucket_hint=''):
    """Deterministic value extraction from a quote. Gold-blind.
    Returns the extracted value or None if ambiguous."""
    if not quote:
        return None
    # dates
    dm = re.search(r'(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})\s*日?', quote)
    if dm:
        return f'{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}'
    # document numbers (证监立案字/处罚字 etc.)
    nm = re.search(r'([证处]监?\w*字\s*[\[〔【]?\d{4}[\]〕】]?\s*\d+\s*号)', quote)
    if nm:
        return re.sub(r'\s+', '', nm.group(1))
    # amounts with units
    am = re.findall(r'(\d[\d,，.]+)\s*(亿元|万元|元|%)', quote)
    if len(am) == 1:
        num, unit = am[0]
        num_clean = num.replace(',', '').replace('，', '')
        try:
            d = Decimal(num_clean)
            # normalize to yuan for number-kind, keep unit for text
            if unit == '亿元':
                return str(int(d * 100_000_000)) if d == int(d) else str(d * 100_000_000)
            if unit == '万元':
                return str(int(d * 10_000)) if d == int(d) else str(d * 10_000)
            return num_clean
        except Exception:
            return None
    if len(am) > 1:
        return None  # ambiguous: multiple amounts in one quote
    # single long text token (≥4 chars CJK) that's the "content" word
    # only if the quote is short enough to be unambiguous
    if len(quote) <= 40:
        cjk = re.findall(r'[\u4e00-\u9fff]{3,}', quote)
        if len(cjk) == 1:
            return cjk[0]
    return None


def adapt_ds_output(raw_obj):
    """Map DS nested {bucket: [{doc,page,quote}]} → flat list with gold-blind values."""
    adapted = []
    if not isinstance(raw_obj, dict):
        return adapted
    for bucket, content in raw_obj.items():
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('quote'):
                    v = extract_value_gold_blind(item['quote'], bucket)
                    adapted.append(dict(
                        field=bucket,
                        value=v,  # may be None (ambiguous → unverified)
                        raw=str(v) if v else None,
                        doc=item.get('doc'),
                        page=item.get('page'),
                        quote=item.get('quote', '')))
        elif isinstance(content, dict):
            for sub_key, item in content.items():
                if isinstance(item, dict) and item.get('quote'):
                    v = extract_value_gold_blind(item['quote'], f'{bucket}/{sub_key}')
                    adapted.append(dict(
                        field=f'{bucket}/{sub_key}',
                        value=v,
                        raw=str(v) if v else None,
                        doc=item.get('doc'),
                        page=item.get('page'),
                        quote=item.get('quote', '')))
                elif isinstance(item, str) and len(item) > 2:
                    adapted.append(dict(
                        field=f'{bucket}/{sub_key}',
                        value=item, raw=item,
                        doc=None, page=None, quote=''))
    return adapted


def build_evidence(raw_entries, adapted_entries, contract, use_adapted):
    """Build verified evidence table. Arm A: raw DS entries as-is.
    Arm B: adapted entries with gold-blind values."""
    if use_adapted:
        entries = adapted_entries
    else:
        entries = raw_entries
    verified, rejected = CH.verify_evidence(entries, contract)
    return verified, rejected


def run_cell(arm, task, rep, contract, dag_led, tr):
    """One cell: cached upstream + fresh SINK."""
    key = f'dag|{task}|single_ds|r{rep}|'
    e0_raw = extract_any(dag_led[key + 'e0']['text'])
    e1_raw = extract_any(dag_led[key + 'e1']['text'])
    m = extract_any(dag_led[key + 'm']['text'])
    r = extract_any(dag_led[key + 'r']['text'])

    raw_entries = P3.normalize_stage(e0_raw) + P3.normalize_stage(e1_raw)
    adapted = adapt_ds_output(e0_raw) + adapt_ds_output(e1_raw)

    use_adapted = (arm == 'B')
    verified, rejected = build_evidence(raw_entries, adapted, contract, use_adapted)

    m_facts = {}
    for e in P3.normalize_stage(m):
        k = PP.fact_key(e)
        if k and e.get('value') not in (None, ''):
            m_facts.setdefault(k, e.get('value'))
    ev_map = PP.match_evidence(m_facts, verified, contract)
    p_user = PP.render(contract, r, m_facts, ev_map, with_evidence=True)

    purpose = f'adapt|{task}|{arm}|r{rep}|p'
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
                gate=res['critical_gate'],
                n_verified=len(verified), n_rejected=len(rejected),
                n_ev_map=len(ev_map),
                wrong_assert=sum(1 for x in res['rows'] if x['status'].startswith('VALUE')),
                wrong_cit=sum(1 for x in res['rows'] if x['status'].startswith('C_LOC') or x['status'] == 'UNSUPPORTED'),
                abst=sum(1 for x in res['rows'] if x['status'] == 'ABSENT'),
                crit_tp=sum(1 for x in res['rows'] if x.get('critical') and x['status'] == 'TP'),
                cost_yuan=yuan)


_ledger_path = f'{DAG}/ADAPT_LEDGER.jsonl'
_ledger_calls = 0
_ledger_cost = 0.0


def real_call(alias, system, user, mt, purpose, sha, tr):
    global _ledger_calls, _ledger_cost
    if _ledger_calls >= CAPS['calls']:
        raise RuntimeError('calls cap')
    if _ledger_cost + 0.006 > CAPS['yuan'] * 0.95:
        raise RuntimeError('cost cap')
    import urllib.request, time
    from stage_d_v2_transport import build_request, ds_key, MODEL_CFG
    body = build_request(alias, system, user, mt)
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
    _ledger_calls += 1
    _ledger_cost += yuan
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
            pair = [('A',), ('B',)]
            random.Random(SEED + hash(t) % 100).shuffle(pair)
            for (arm,) in pair:
                blocks.append((t, rep, arm))

    results = []
    status = 'COMPLETE'
    for t, rep, arm in blocks:
        try:
            contract = F.load_contract(t)
            r = run_cell(arm, t, rep, contract, dag_led, tr)
            results.append(r)
            print(f"  {t:9s} {arm} r{rep} Q={r['q']:.3f} verified={r['n_verified']:2d} "
                  f"ev_map={r['n_ev_map']:2d} gate={r['gate']}", flush=True)
        except Exception as e:
            results.append(dict(task=t, rep=rep, arm=arm, error=str(e)[:160]))
            status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
            print(f"  {t} {arm} r{rep} ERROR {e}", flush=True)
            break

    json.dump(dict(batch='FORMAT_ADAPTATION', status=status, caps=CAPS,
                   used=dict(calls=_ledger_calls, yuan=round(_ledger_cost, 4)),
                   results=results),
              open(f'{DAG}/ADAPT_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={_ledger_calls}/{CAPS['calls']} ¥{_ledger_cost:.4f}/{CAPS['yuan']}")


if __name__ == '__main__':
    main()
