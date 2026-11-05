"""QP5-C V2.1 runner: sandwich pairing with noise calibration (authorized).

Arms per (task, rep) block, arm order randomized within block:
  C1' : cached QP4-D E -> fresh t/m/r/p   (purposes qp5c|T|C1|rN|node)
  C2  : E-v2 (+gold-blind retry <=1/E node) -> fresh t/m/r/p
        (qp5c|T|C2|rN|node; retry ...|R|...)
  C0  : cached E -> fresh t/m/r/p again   (qp5c|T|C0|rN|node) on 6 preregistered cells

Preflight (--audit): SHA-identity of C1' request bodies vs QP4-D (t/m/r) and
QP5-A B2 (p) records — purpose keys must be the ONLY difference.
"""
import json, os, random, sys, hashlib
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp4_factorial as F
import qp1_prompts as P1
import qp2_chain as CH
import qp3_primitives as P3
import qp5a_pure_prep as PP
import scorer_qp1 as Q1
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'
SEED = 20261103
CAPS = dict(calls=170, tokens=3_500_000, yuan=1.00)
RESERVE = 0.05
C0_CELLS = {('E06', 1), ('MVR1', 2), ('KANGMEI', 1), ('GUOEN', 2), ('ZIJING', 1), ('ZEDA', 2)}

EVIDENCE_CONTRACT = (
    '证据合同（每个方面必须逐项给出）：doc（文书ID）、page（整数页码）、quote（该方面对应文书'
    '中的连续逐字原文，禁止省略号、禁止拼接）。缺任一字段视为未完成。')
SCHEMA_RULE = ('输出模式（强制）：只输出 JSON 对象 {"facts":[{"field":"...","value":"...",'
               '"doc":"...","page":1,"quote":"..."}]}；不得嵌套、不得用方面名作外层键。')
RETRY_TMPL = ('以下方面的证据不完整（缺 doc/page/quote、引文未逐字出现在所引页、或值未出现在引文中）：\n{fields}\n'
              '请仅为这些方面重新抽取并给出完整证据，输出同模式 JSON（{{"facts":[...]}}）。')


def load_led(path):
    led = {}
    if os.path.exists(path):
        for line in open(path):
            x = json.loads(line)
            led[x['purpose']] = x
    return led


def e2_user(contract, doc_ids):
    u = P1.e_user(contract, doc_ids, 'E1')
    return u + '\n\n' + EVIDENCE_CONTRACT + '\n' + SCHEMA_RULE


def gold_blind_failures(entries, contract):
    """Fields whose entries fail schema/verbatim/self-grounding (NO gold)."""
    bad, seen = [], {}
    for e in entries:
        k = e.get('field') or e.get('bucket') or e.get('predicate')
        if k is None:
            continue
        v = e.get('raw') or e.get('value')
        q = e.get('quote', '') or ''
        pg = (contract['source_pages'].get(str(e.get('doc'))) or {}).get('pages', {}).get(str(e.get('page')))
        ok = bool(pg and q and Q1._norm(q) in Q1._norm(pg.get('text', ''))
                  and v not in (None, '') and Q1.value_in_quote(v, q))
        seen[k] = seen.get(k, False) or ok
    for k, ok in seen.items():
        if not ok:
            bad.append(k)
    return bad


def run_arm(arm, t, rep, contract, call, led4, recovery_state=None):
    ledkey = f'qp4|{t}|D|r{rep}|'
    if arm in ('Local', 'Full'):
        if recovery_state is None:
            raise ValueError('Local/Full requires a frozen recovery state')
        generated = {}
        for node, doc_ids in zip(('e0', 'e1'), docs_half(t, contract)):
            if arm == 'Local' and node != recovery_state['defect_node']:
                generated[node] = extract_any(recovery_state['texts'][node])
            else:
                generated[node] = extract_any(call(
                    node, P1.E_SYS, e2_user(contract, doc_ids), P1.MAXTOK['E'],
                    f'localfull|{t}|{arm}|r{rep}|{node}'))
        e0, e1 = generated['e0'], generated['e1']
    elif arm in ('C1', 'C0'):
        e0 = extract_any(led4[ledkey + 'e0']['text'])
        e1 = extract_any(led4[ledkey + 'e1']['text'])
    else:
        e0 = extract_any(call('e0', P1.E_SYS, e2_user(contract, docs_half(t, contract)[0]), P1.MAXTOK['E'],
                              f'qp5c|{t}|C2|r{rep}|e0'))
        e1 = extract_any(call('e1', P1.E_SYS, e2_user(contract, docs_half(t, contract)[1]), P1.MAXTOK['E'],
                              f'qp5c|{t}|C2|r{rep}|e1'))
        # gold-blind retry
        for node, obj in (('e0', e0), ('e1', e1)):
            entries = P3.normalize_stage(obj)
            bad = gold_blind_failures(entries, contract)
            if bad and bad != [None]:
                retry_user = (P1.e_user(contract, docs_half(t, contract)[0 if node == 'e0' else 1], 'E1')
                              + '\n\n' + EVIDENCE_CONTRACT + '\n' + SCHEMA_RULE + '\n\n'
                              + RETRY_TMPL.format(fields='\n'.join(f'- {b}' for b in bad[:12])))
                try:
                    extra = extract_any(call(node, P1.E_SYS, retry_user, P1.MAXTOK['E'],
                                             f'qp5c|{t}|C2|R|r{rep}|{node}'))
                    merged = {'facts': (obj.get('facts') or []) + (extra.get('facts') or [])}
                    if node == 'e0':
                        e0 = merged
                    else:
                        e1 = merged
                except Exception:
                    pass
    tt = extract_any(call('t', P1.M_SYS, P1.t_user(contract, e0), P1.MAXTOK['t'],
                          f'qp5c|{t}|{arm}|r{rep}|t'))
    mm = extract_any(call('m', P1.M_SYS, P1.m_user(contract, {'e0': e0, 'e1': e1}), P1.MAXTOK['m'],
                          f'qp5c|{t}|{arm}|r{rep}|m'))
    rr = extract_any(call('r', P1.R_SYS, P1.r_user(contract, mm), P1.MAXTOK['r'],
                          f'qp5c|{t}|{arm}|r{rep}|r'))
    entries = P3.normalize_stage(e0) + P3.normalize_stage(e1)
    verified, _ = CH.verify_evidence(entries, contract)
    m_facts = {}
    for e in P3.normalize_stage(mm):
        k = PP.fact_key(e)
        if k and e.get('value') not in (None, ''):
            m_facts.setdefault(k, e.get('value'))
    ev_map = PP.match_evidence(m_facts, verified, contract)
    p_user = PP.render(contract, rr, m_facts, ev_map, with_evidence=True)
    pp = extract_any(call('p', P1.P_SYS, p_user, P1.MAXTOK['p'], f'qp5c|{t}|{arm}|r{rep}|p'))
    res = Q1.score_task(contract, pp)
    ev_keys = set(ev_map.keys())
    gold_map = {f.get('bucket') or f['fact_id']: f['fact_id'] for f in contract['required_facts']}
    rows_ev = [x for x in res['rows'] if gold_map.get(x['fact_id'], x['fact_id']) and
               next((f.get('bucket') or f['fact_id'] for f in contract['required_facts']
                     if f['fact_id'] == x['fact_id']), None) in ev_keys]
    rows_no = [x for x in res['rows'] if x not in rows_ev]
    return dict(task=t, rep=rep, arm=arm, q=res['q'], gate=res['critical_gate'],
                n_verified=len(verified), ev_mapped=len(ev_map),
                q_ev=round(sum(1 for x in rows_ev if x['status'] == 'TP') / len(rows_ev), 4) if rows_ev else None,
                q_no=round(sum(1 for x in rows_no if x['status'] == 'TP') / len(rows_no), 4) if rows_no else None,
                wrong_assert=sum(1 for x in res['rows'] if x['status'].startswith('VALUE')),
                wrong_cit=sum(1 for x in res['rows'] if x['status'].startswith('C_LOC') or x['status'] == 'UNSUPPORTED'),
                abst=sum(1 for x in res['rows'] if x['status'] == 'ABSENT'),
                crit_tp=sum(1 for x in res['rows'] if x.get('critical') and x['status'] == 'TP'),
                e0=e0, e1=e1, sink=pp, rows=res['rows'])


def docs_half(t, contract):
    docs = sorted(contract['source_pages'].keys())
    h = (len(docs) + 1) // 2
    return docs[:h], docs[h:] or docs[:1]


def build_guard():
    from stage_d_v2_transport import Ledger
    ledger = Ledger(f'{QP}/QP5C_LEDGER.jsonl')
    index = dict(ledger.index)
    for path in (f'{QP}/QP1_LEDGER.jsonl', f'{QP}/QP2_LEDGER.jsonl', f'{QP}/QP4_LEDGER.jsonl',
                 f'{QP}/QP5A_LEDGER.jsonl'):
        if os.path.exists(path):
            for line in open(path):
                rec = json.loads(line)
                index.setdefault((rec['purpose'], rec['prompt_sha256']), rec)
    return ledger, index


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--local-full':
        return local_full_main(sys.argv[2:])
    mode = sys.argv[1] if len(sys.argv) > 1 else 'run'
    led4 = {}
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        led4[x['purpose']] = x

    if mode == '--audit':
        # SHA-identity: C1' t/m/r bodies == QP4-D; C1' p body == QP5-A B2
        led5a = load_led(f'{QP}/QP5A_LEDGER.jsonl')
        ok = True
        for t in F.TASKS:
            for rep in (1, 2):
                contract = F.load_contract(t)
                e0 = extract_any(led4[f'qp4|{t}|D|r{rep}|e0']['text'])
                e1 = extract_any(led4[f'qp4|{t}|D|r{rep}|e1']['text'])
                m = extract_any(led4[f'qp4|{t}|D|r{rep}|m']['text'])
                r = extract_any(led4[f'qp4|{t}|D|r{rep}|r']['text'])
                checks = [
                    ('t', P1.M_SYS, P1.t_user(contract, e0), P1.MAXTOK['t'], f'qp4|{t}|D|r{rep}|t'),
                    ('m', P1.M_SYS, P1.m_user(contract, {'e0': e0, 'e1': e1}), P1.MAXTOK['m'], f'qp4|{t}|D|r{rep}|m'),
                    ('r', P1.R_SYS, P1.r_user(contract, m), P1.MAXTOK['r'], f'qp4|{t}|D|r{rep}|r'),
                ]
                from stage_d_v2_transport import build_request
                for node, sysx, userx, mt, hist_purpose in checks:
                    body = build_request('glm53flash', sysx, userx, mt)
                    sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    if sha != led4[hist_purpose]['prompt_sha256']:
                        ok = False
                        print(f'SHA MISMATCH {t} r{rep} {node}')
                # p vs QP5-A B2
                entries = P3.normalize_stage(e0) + P3.normalize_stage(e1)
                verified, _ = CH.verify_evidence(entries, contract)
                m_facts = {}
                for e in P3.normalize_stage(m):
                    k = PP.fact_key(e)
                    if k and e.get('value') not in (None, ''):
                        m_facts.setdefault(k, e.get('value'))
                ev_map = PP.match_evidence(m_facts, verified, contract)
                p_user = PP.render(contract, r, m_facts, ev_map, with_evidence=True)
                body = build_request('glm53flash', P1.P_SYS, p_user, P1.MAXTOK['p'])
                sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                if sha != led5a[f'qp5a|{t}|B2|r{rep}|p']['prompt_sha256']:
                    ok = False
                    print(f'SHA MISMATCH {t} r{rep} p (vs QP5-A B2)')
        print('SHA-IDENTITY AUDIT:', 'PASS' if ok else 'FAIL')
        return 0 if ok else 1

    ledger, index = build_guard()

    def call(node, system, user, mt, purpose):
        from stage_d_v2_transport import build_request, glm_key, MODEL_CFG
        body = build_request('glm53flash', system, user, mt)
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hit = index.get((purpose, sha))
        if hit is not None:
            return hit['text']
        if len(ledger.records) + 1 > CAPS['calls']:
            raise RuntimeError('calls cap')
        if ledger.cost + 0.006 > CAPS['yuan'] * (1 - RESERVE):
            raise RuntimeError('cost cap')
        import urllib.request, time
        req = urllib.request.Request(MODEL_CFG['glm53flash']['url'],
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        req.add_header('authorization', 'Bearer ' + glm_key())
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=180) as resp:
            d = json.loads(resp.read().decode())
        ch = d['choices'][0]
        u = d.get('usage', {})
        c = ch.get('message', {}).get('content', '')
        text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
        tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
        rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), purpose=purpose, prompt_sha256=sha,
                   usage=dict(input_tokens=tin, output_tokens=tout),
                   accounting_yuan=round(tin * 0.8e-6 + tout * 2.8e-6, 8),
                   latency_s=round(time.monotonic() - t0, 3),
                   stop_reason={'stop': 'end_turn', 'length': 'max_tokens'}.get(
                       ch.get('finish_reason'), ch.get('finish_reason')),
                   text=text)
        ledger.add(rec)
        index[(purpose, sha)] = {'text': text}
        return text

    blocks = []
    for t in F.TASKS:
        for rep in (1, 2):
            arms = ['C1', 'C2'] + (['C0'] if (t, rep) in C0_CELLS else [])
            random.Random(SEED + hash(t) % 100).shuffle(arms)
            blocks.append((t, rep, arms))
    results, status = [], 'COMPLETE'
    for t, rep, arms in blocks:
        contract = F.load_contract(t)
        for arm in arms:
            try:
                r = run_arm(arm, t, rep, contract, call, led4)
                e_dump = {k: r.pop(k) for k in ('e0', 'e1', 'sink') if k in r}
                r['rows'] = e_dump and None  # store rows only in file
                results.append(r)
                print(f"  {t:9s} {arm} r{rep} Q={r['q']:.3f} ev={r['n_verified']:2d} "
                      f"gate={r['gate']}", flush=True)
            except Exception as e:
                results.append(dict(task=t, rep=rep, arm=arm, error=str(e)[:160]))
                status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
                print(f"  {t} {arm} r{rep} ERROR {e}", flush=True)
                break
        if status != 'COMPLETE':
            break
        json.dump(dict(status=status, used=dict(calls=len(ledger.records),
                                                yuan=round(ledger.cost, 4)), results=results),
                  open(f'{QP}/QP5C_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{QP}/QP5C_PROGRESS.json.tmp', f'{QP}/QP5C_PROGRESS.json')
    json.dump(dict(batch='QP5C_V2', status=status, caps=CAPS,
                   used=dict(calls=len(ledger.records), tokens=ledger.tokens,
                             yuan=round(ledger.cost, 4)), results=results),
              open(f'{QP}/QP5C_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={len(ledger.records)}/{CAPS['calls']} ¥{ledger.cost:.4f}/{CAPS['yuan']}")


def local_full_main(argv):
    """Explicit GO-only isolated batch; uses run_arm's unchanged downstream path."""
    import argparse, time, urllib.request
    from pathlib import Path
    from stage_d_v2_transport import build_request, glm_key, MODEL_CFG
    ap = argparse.ArgumentParser()
    ap.add_argument('--authorization', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args(argv)
    base = Path('/root/research_outputs/QP5C_RECOVERY_MECHANISMS_20261103')
    cfg_path = base / 'LOCAL_FULL_CONFIG.json'
    cfg = json.loads(cfg_path.read_text())
    auth = json.loads(Path(args.authorization).read_text())
    sha = lambda b: hashlib.sha256(b).hexdigest()
    if (auth.get('decision') != 'GO' or auth.get('max_calls') != 66
        or auth.get('estimate_stop_cny') != 4.5
        or auth.get('config_sha256') != sha(cfg_path.read_bytes())
        or auth.get('runner_sha256') != sha(Path(__file__).read_bytes())
        or not (auth.get('billing_confirmed') or auth.get('public_price_estimation_authorized'))
        or not (auth.get('output_cap_includes_thinking') is True or auth.get('thinking_accounting_unknown_accepted'))
        or not auth.get('nonabsolute_cash_cap_accepted')):
        raise ValueError('Explicit matching batch GO and billing confirmation required')
    rates = auth['rates_cny_per_million']
    if rates != {'input': 0.8, 'output': 2.8}:
        raise ValueError('Rates differ: frozen budget requires new approval, no silent adaptation')
    key = glm_key()  # Existing credential precedence unchanged; never recorded.
    if auth.get('credential_sha256') != sha(key.encode()):
        raise ValueError('Confirmed credential does not match current configured account')
    snapshot = json.loads(Path('/root/research_outputs/QP5C_RESULT_RECONSTRUCTION_20261103/SOURCE_SNAPSHOT.json').read_text())
    archived = [json.loads(l) for l in snapshot['QP5C_LEDGER.jsonl']['text'].splitlines()]
    states = {}
    for state in cfg['states']:
        texts = {}
        for node, detail in state['details'].items():
            record = archived[detail['index'] - 1]
            if record['purpose'] != detail['purpose'] or sha(record['text'].encode()) != detail['response_sha']:
                raise ValueError('Frozen state mismatch')
            texts[node] = record['text']
        states[state['task']] = dict(texts=texts, defect_node=state['affected'][0])
    target = Path(args.output).resolve()
    if target.parent != base.resolve():
        raise ValueError('Output must be a new child of the isolated recovery directory')
    target.mkdir(exist_ok=False)  # No restart, resume, overwrite, or old cache lookup.
    (target / 'AUTHORIZATION.json').write_text(json.dumps(auth, ensure_ascii=False, indent=2))
    (target / 'CONFIG.json').write_bytes(cfg_path.read_bytes())
    batch_start = time.monotonic()
    used = {'calls': 0, 'estimate_cny': 0.0}
    results = []
    class StopBatch(Exception): pass
    class StopArm(Exception): pass
    def save():
        data = dict(status='RUNNING', used=used, actual_settlement='UNKNOWN', thinking_accounting='UNKNOWN', results=results,
                    batch_wall_s=time.monotonic()-batch_start)
        (target/'RESULTS.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
    def append(record):
        with (target/'LEDGER.jsonl').open('a') as f:
            f.write(json.dumps(record, ensure_ascii=False)+'\n'); f.flush(); os.fsync(f.fileno())
    status = 'COMPLETE'
    try:
        for task_index, task in enumerate(('KANGMEI', 'MVR1')):
            for rep in (1, 2, 3):
                order = ('Local', 'Full') if (task_index + rep) % 2 else ('Full', 'Local')
                for arm in order:
                    start = time.monotonic()
                    run_id = f'{task}_{rep}_{arm}'
                    def call(node, system, user, mt, purpose):
                        now = time.monotonic()
                        if now-batch_start >= 14400: raise StopBatch('BATCH_DEADLINE')
                        if now-start >= 1080: raise StopArm('ARM_DEADLINE')
                        body = build_request('glm53flash', system, user, mt)
                        # Conservative byte-based input bound; no prompt truncation or altered content.
                        content_bytes = sum(len(m['content'].encode()) for m in body['messages'])
                        if content_bytes + 4096 > 65536:
                            raise StopBatch('INPUT_RESERVATION_UNCERTIFIED')
                        reserve = (65536*.8 + (131072 if auth.get('thinking_accounting_unknown_accepted') else mt)*2.8)/1e6
                        if used['calls'] >= 66 or used['estimate_cny']+reserve > 4.5*.95:
                            raise StopBatch('BUDGET_OR_CALL_STOP')
                        ident = f'{run_id}_{node}'
                        (target/f'{ident}.request.json').write_text(json.dumps(body, ensure_ascii=False))
                        used['calls'] += 1
                        append(dict(event='DISPATCHED', id=ident, purpose=purpose,
                                    request_sha256=sha(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()),
                                    ts=time.time(), reserve_cny=reserve))
                        req = urllib.request.Request(MODEL_CFG['glm53flash']['url'],
                            data=json.dumps(body).encode(), method='POST',
                            headers={'content-type':'application/json','authorization':'Bearer '+key})
                        t0 = time.monotonic()
                        try:
                            with urllib.request.urlopen(req, timeout=min(180,1080-(t0-start),14400-(t0-batch_start))) as response:
                                raw = response.read()
                            (target/f'{ident}.response.bin').write_bytes(raw)
                            payload = json.loads(raw)
                            usage = payload.get('usage')
                            if not isinstance(usage,dict) or any(type(usage.get(k)) is not int or usage[k]<0 for k in ('prompt_tokens','completion_tokens')):
                                raise StopBatch('UNKNOWN_USAGE')
                            tin,tout=usage['prompt_tokens'],usage['completion_tokens']
                            cost=(tin*.8+tout*2.8)/1e6
                            used['estimate_cny'] += cost
                            append(dict(event='RESPONSE',id=ident,usage=usage,estimate_cny=cost,
                                        actual_settlement='UNKNOWN',latency_s=time.monotonic()-t0,ts=time.time()))
                            if tin>65536 or tout>mt or used['estimate_cny']>=4.5:
                                raise StopBatch('USAGE_OR_BUDGET_BOUND_EXCEEDED')
                            if time.monotonic()-batch_start>=14400: raise StopBatch('BATCH_DEADLINE')
                            if time.monotonic()-start>=1080: raise StopArm('ARM_DEADLINE')
                            choice=payload['choices'][0]
                            text=choice['message'].get('content','')
                            if not isinstance(text,str): raise ValueError('NON_TEXT_RESPONSE')
                            return text
                        except (StopBatch,StopArm): raise
                        except urllib.error.HTTPError as e:
                            error_body = e.read().decode('utf-8', errors='replace').replace(key, '[REDACTED]')
                            (target/f'{ident}.error.txt').write_text(error_body)
                            append(dict(event='SYSTEM_FAILURE',id=ident,error_type='HTTPError',
                                        http_status=e.code,actual_settlement='UNKNOWN'))
                            raise StopBatch('HTTP_ERROR_'+str(e.code)) from None
                        except Exception as e:
                            append(dict(event='SYSTEM_FAILURE',id=ident,error_type=type(e).__name__,actual_settlement='UNKNOWN'))
                            raise StopBatch('TRANSPORT_OR_PROVIDER_FAILURE') from None
                    try:
                        contract = F.load_contract(task)
                        result=run_arm(arm,task,rep,contract,call,{},recovery_state=states[task])
                        results.append(dict(run_id=run_id,status='COMPLETED',result=result,
                                            recovery_wall_s=time.monotonic()-start))
                    except StopBatch as e:
                        results.append(dict(run_id=run_id,status='STOPPED',reason=str(e),recovery_wall_s=time.monotonic()-start))
                        raise
                    except Exception as e:
                        results.append(dict(run_id=run_id,status='INCOMPLETE',reason=type(e).__name__,
                                            recovery_wall_s=time.monotonic()-start,terminal_Q=None))
                    save()
    except StopBatch as e:
        status='STOPPED:'+str(e)
    except BaseException:
        status='INTERRUPTED_OR_SYSTEM_FAILURE'
        raise
    finally:
        save()
        data=json.loads((target/'RESULTS.json').read_text());data['status']=status
        data['not_started']=[f'{t}_{r}_{a}' for t in ('KANGMEI','MVR1') for r in (1,2,3)
                             for a in ('Local','Full') if f'{t}_{r}_{a}' not in {x['run_id'] for x in results}]
        (target/'RESULTS.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
        (target/'CLOSED.json').write_text(json.dumps({'status':status,'resume_allowed':False}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
