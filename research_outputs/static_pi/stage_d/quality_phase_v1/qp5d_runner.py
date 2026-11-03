"""QP5-D runner: D5 value-compliance echo + single gold-blind corrective retry.

F1: cached QP5-C C2 upstream (t/m/r/table identical), fresh SINK (B2 prompt verbatim)
F2: same cached upstream, SINK with echo rule + code check + one corrective retry
C0: F1-input SINK duplicate on 6 preregistered cells
Caps: 48 calls / 250k tokens / ¥0.30. Block = (task, rep), arm order randomized.
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
from qp5d_attribution import merged_e_texts, load_ledger
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'
SEED = 20261103
CAPS = dict(calls=48, tokens=250_000, yuan=0.30)
C0_CELLS = {('E06', 1), ('MVR1', 2), ('KANGMEI', 1), ('GUOEN', 2), ('ZIJING', 1), ('ZEDA', 2)}

ECHO_RULE = (
    '值合规回显规则（仅适用于已核验证据表列出的槽位）：\n'
    '1) 槽位 value_kind 为 number/amount/percent 的：value 输出与表条目数值相等的带符号裸数字'
    '（如 24500、-12500.00；禁止单位、前缀"亏损："、括注"（即…）"）。\n'
    '2) value_kind 为 text 的：value 逐字复制表条目的值（保留单位如"万元/亿元/%"，去掉千分位逗号）。\n'
    '3) 未在表中列出的槽位照常作答，不受本规则影响。')


def unit_equal(answer_v, entry_v):
    """Compliance per the preregistered echo rule (gold-blind):
    numeric slots -> the answer NUMBER equals the table NUMBER (sign included,
    e.g. 亏损12,500.00万元 -> -12500 matches -12500.00); text slots -> the
    answer reproduces the table value verbatim (whitespace/separators ignored)."""
    if answer_v in (None, '') or entry_v in (None, ''):
        return False
    a = P3.deco_amount(answer_v)
    b = P3.deco_amount(entry_v)
    if a and b:
        from decimal import Decimal
        return abs(a[0] - b[0]) <= max(abs(b[0]) * Decimal('0.001'), Decimal('0.01'))
    return P3._norm(answer_v) == P3._norm(entry_v)


def build_inputs(led, t, rep):
    """Deterministic cached upstream + table (SHA-identical across F1/F2/C0)."""
    contract = F.load_contract(t)
    texts = merged_e_texts(led, t, rep)
    entries = []
    for tx in texts:
        entries += P3.normalize_stage(extract_any(tx))
    verified, _ = CH.verify_evidence(entries, contract)
    m = extract_any(led[f'qp5c|{t}|C2|r{rep}|m']['text'])
    r = extract_any(led[f'qp5c|{t}|C2|r{rep}|r']['text'])
    m_facts = {}
    for e in P3.normalize_stage(m):
        k = PP.fact_key(e)
        if k and e.get('value') not in (None, ''):
            m_facts.setdefault(k, e.get('value'))
    ev_map = PP.match_evidence(m_facts, verified, contract)
    return contract, r, m_facts, ev_map


def slot_kind(contract, bucket_key):
    f = next((x for x in contract['required_facts'] if (x.get('bucket') or x['fact_id']) == bucket_key), None)
    return f.get('value_kind') if f else None


class Guard:
    def __init__(self):
        from stage_d_v2_transport import Ledger
        self.ledger = Ledger(f'{QP}/QP5D_LEDGER.jsonl')
        self.index = dict(self.ledger.index)
        for path in (f'{QP}/QP5C_LEDGER.jsonl', f'{QP}/QP5A_LEDGER.jsonl', f'{QP}/QP4_LEDGER.jsonl',
                     f'{QP}/QP2_LEDGER.jsonl', f'{QP}/QP1_LEDGER.jsonl'):
            if os.path.exists(path):
                for line in open(path):
                    rec = json.loads(line)
                    self.index.setdefault((rec['purpose'], rec['prompt_sha256']), rec)

    def call(self, system, user, mt, purpose):
        from stage_d_v2_transport import build_request, glm_key, MODEL_CFG
        body = build_request('glm53flash', system, user, mt)
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hit = self.index.get((purpose, sha))
        if hit is not None:
            return hit['text']
        if len(self.ledger.records) + 1 > CAPS['calls']:
            raise RuntimeError('calls cap')
        if self.ledger.cost + 0.006 > CAPS['yuan'] * 0.95:
            raise RuntimeError('cost cap')
        import urllib.request, time
        req = urllib.request.Request(MODEL_CFG['glm53flash']['url'],
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        req.add_header('authorization', 'Bearer ' + glm_key())
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=180) as resp:
            d = json.loads(resp.read().decode())
        ch = d['choices'][0]; u = d.get('usage', {})
        c = ch.get('message', {}).get('content', '')
        text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
        tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
        rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), purpose=purpose, prompt_sha256=sha,
                   usage=dict(input_tokens=tin, output_tokens=tout),
                   accounting_yuan=round(tin * 0.8e-6 + tout * 2.8e-6, 8),
                   latency_s=round(time.monotonic() - t0, 3),
                   stop_reason={'stop': 'end_turn', 'length': 'max_tokens'}.get(
                       ch.get('finish_reason'), ch.get('finish_reason')), text=text)
        self.ledger.add(rec)
        self.index[(purpose, sha)] = {'text': text}
        return text


def score(contract, sink, ev_map, m_facts):
    res = Q1.score_task(contract, sink)
    ans = {}
    for a in (sink or {}).get('answers', []) if isinstance(sink, dict) else []:
        if isinstance(a, dict) and a.get('fact_id'):
            ans.setdefault(a['fact_id'], a)
    # compliance (gold-blind): table slots answered with unit-equal value;
    # slot->table binding via the QP5-A matcher (name first, value-grounding fallback)
    import qp5a_analyze
    f2key = qp5a_analyze.gold_to_evkey(contract, ev_map, m_facts)
    compliant = checked = 0
    bad_slots = []
    for fid, k in f2key.items():
        if k is None:
            continue
        e = ev_map[k]
        f = next((x for x in contract['required_facts'] if x['fact_id'] == fid), None)
        if not f:
            continue
        a = ans.get(fid)
        checked += 1
        if a and unit_equal(a.get('value'), e.get('raw') or e.get('value')):
            compliant += 1
        else:
            bad_slots.append(f'{f["fact_id"]}|{k}|{a.get("value") if a else "ABSENT"}|{e.get("raw") or e.get("value")}')
    return res, dict(checked=checked, compliant=compliant, bad=bad_slots)


def main():
    led = load_ledger()
    g = Guard()
    blocks = []
    for t in F.TASKS:
        for rep in (1, 2):
            arms = ['F1', 'F2'] + (['C0'] if (t, rep) in C0_CELLS else [])
            random.Random(SEED + hash(t) % 100).shuffle(arms)
            blocks.append((t, rep, arms))
    results, status = [], 'COMPLETE'
    retries_used = 0
    for t, rep, arms in blocks:
        try:
            contract, r, m_facts, ev_map = build_inputs(led, t, rep)
            base_prompt = PP.render(contract, r, m_facts, ev_map, with_evidence=True)
            f2_prompt = base_prompt + '\n\n' + ECHO_RULE
            for arm in arms:
                user = base_prompt if arm in ('F1', 'C0') else f2_prompt
                raw = g.call(P1.P_SYS, user, P1.MAXTOK['p'], f'qp5d|{t}|{arm}|r{rep}|p')
                sink = extract_any(raw)
                res, comp = score(contract, sink, ev_map, m_facts)
                retried = 0
                if arm == 'F2' and comp['bad']:
                    list_txt = '\n'.join(f'- {b.split("|")[0]}（槽位 {b.split("|")[1]}；你的输出 {b.split("|")[2]}；表内值 {b.split("|")[3]}）'
                                        for b in comp['bad'][:16])
                    retry_user = (f2_prompt + '\n\n以下表内槽位的 value 未按回显规则输出，请重发 answers '
                                  '（其余槽位保持原答案）：\n' + list_txt)
                    try:
                        raw2 = g.call(P1.P_SYS, retry_user, P1.MAXTOK['p'], f'qp5d|{t}|F2R|r{rep}|p')
                        retries_used += 1
                        retried = 1
                        sink2 = extract_any(raw2)
                        res2, comp2 = score(contract, sink2, ev_map, m_facts)
                        if comp2['compliant'] > comp['compliant']:
                            sink, res, comp = sink2, res2, comp2
                    except Exception:
                        pass
                results.append(dict(task=t, rep=rep, arm=arm, q=res['q'], gate=res['critical_gate'],
                                    compliance=comp['compliant'], checked=comp['checked'],
                                    retried=retried,
                                    wrong_assert=sum(1 for x in res['rows'] if x['status'].startswith('VALUE')),
                                    wrong_cit=sum(1 for x in res['rows'] if x['status'].startswith('C_LOC') or x['status'] == 'UNSUPPORTED'),
                                    abst=sum(1 for x in res['rows'] if x['status'] == 'ABSENT'),
                                    crit_tp=sum(1 for x in res['rows'] if x.get('critical') and x['status'] == 'TP'),
                                    rows=[dict(fact_id=x['fact_id'], status=x['status']) for x in res['rows']]))
                print(f"  {t:9s} {arm} r{rep} Q={res['q']:.3f} comp={comp['compliant']}/{comp['checked']} "
                      f"gate={res["critical_gate"]} retry={retried}", flush=True)
        except Exception as e:
            results.append(dict(task=t, rep=rep, arm=arm if 'arm' in dir() else '?', error=str(e)[:160]))
            status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
            print(f"  {t} r{rep} ERROR {e}", flush=True)
            break
        json.dump(dict(status=status, used=dict(calls=len(g.ledger.records),
                                                yuan=round(g.ledger.cost, 4)), results=results),
                  open(f'{QP}/QP5D_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{QP}/QP5D_PROGRESS.json.tmp', f'{QP}/QP5D_PROGRESS.json')
    json.dump(dict(batch='QP5D_EXECUTION', status=status, caps=CAPS, retries_used=retries_used,
                   used=dict(calls=len(g.ledger.records), tokens=g.ledger.tokens,
                             yuan=round(g.ledger.cost, 4)), results=results),
              open(f'{QP}/QP5D_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={len(g.ledger.records)}/{CAPS['calls']} ¥{g.ledger.cost:.4f}/{CAPS['yuan']} retries={retries_used}")


if __name__ == '__main__':
    main()
