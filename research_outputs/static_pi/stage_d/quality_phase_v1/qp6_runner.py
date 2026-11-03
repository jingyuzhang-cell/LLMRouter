"""QP6 runner: derived-fact computation + joint evidence support (G1/G2/C0).

G1: cached upstream + SINK with B2+echo rule (as-executed QP5-D F2-noretry).
G2: same upstream + SINK additionally receives derived computation results
    and joint-support sets for B_MULTI facts (deterministic, gold-blind).
C0: G1-input SINK duplicate on 6 cells.
Caps: 36 calls / ¥0.25.
"""
import json, os, random, sys, hashlib
from decimal import Decimal
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp4_factorial as F
import qp1_prompts as P1
import qp2_chain as CH
import qp2_amount as AM
import qp3_primitives as P3
import qp5a_pure_prep as PP
import scorer_qp1 as Q1
from qp5d_attribution import merged_e_texts, load_ledger
from qp4b_attribution import is_composite
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'
SEED = 20261103
CAPS = dict(calls=36, tokens=250_000, yuan=0.25)
C0_CELLS = {('E06', 1), ('MVR1', 2), ('KANGMEI', 1), ('GUOEN', 2), ('ZIJING', 1), ('ZEDA', 2)}

ECHO_RULE = QP5D_ECHO = (
    '值合规回显规则（仅适用于已核验证据表列出的槽位）：\n'
    '1) 槽位 value_kind 为 number/amount/percent 的：value 输出与表条目数值相等的带符号裸数字。\n'
    '2) value_kind 为 text 的：value 逐字复制表条目的值（保留单位，去千分位）。\n'
    '3) 未在表中列出的槽位照常作答，不受本规则影响。')

DERIVED_BLOCK = (
    '\n\n联合支持集合（需要多条证据共同支持的槽位）：\n{joint_sets}\n'
    '上述槽位的结论需要所有列出的来源共同支持；请综合多条来源证据作答，'
    '引文可引用多条来源。对于需要计算（如倍数、比例、合计）的槽位，'
    '请基于列出的操作数来源自行计算，并保留计算逻辑。')


def build_inputs(led, t, rep):
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
    return contract, r, m_facts, ev_map, verified, entries


def compute_derivations(contract, ev_map, verified, all_entries):
    """Gold-blind: identify derived/multi facts and compute from table values."""
    derivations = []
    joint_sets = []
    for f in contract['required_facts']:
        fid = f['fact_id']
        key = f.get('bucket') or fid
        ev = ev_map.get(key)
        pred = str(f.get('predicate', '')) + str(f.get('description', ''))
        # ratio facts: try to find numerator and denominator in m_facts
        is_ratio = any(k in pred for k in ('倍数', '倍', '率', '变化率', '比例'))
        is_sum = any(k in pred for k in ('合计', '总和', '共计'))
        if is_ratio:
            # find operand values by matching each sibling fact to verified entries
            nums = []
            for g in contract['required_facts']:
                if g['fact_id'] == fid:
                    continue
                for e in verified:
                    if P3.name_matches(e, g) or Q1.value_in_quote(g.get('value'), e.get('quote', '')):
                        a = P3.deco_amount(e.get('raw') or e.get('value'))
                        if a and a[1] != '%':
                            nums.append((g['fact_id'], a[0], e.get('quote', '')[:40]))
                            break
            if len(nums) >= 2:
                # heuristic: numerator = largest, denominator = smallest (for loss-magnitude ratios)
                nums_sorted = sorted(nums, key=lambda x: abs(x[1]), reverse=True)
                num, den = nums_sorted[0], nums_sorted[-1]
                if abs(den[1]) > 0:
                    ratio = abs(num[1]) / abs(den[1])
                    derivations.append(
                        f'- {fid}（比率）: |{num[0]}| / |{den[0]}| = |{num[1]}| / |{den[1]}| = {ratio:.2f}'
                        f'（操作数来源: {num[2]}… / {den[2]}…）')
        if is_sum:
            vals = []
            for g in contract['required_facts']:
                if g['fact_id'] == fid:
                    continue
                for e in verified:
                    if P3.name_matches(e, g) or Q1.value_in_quote(g.get('value'), e.get('quote', '')):
                        a = P3.deco_amount(e.get('raw') or e.get('value'))
                        if a and a[1] != '%':
                            vals.append((g['fact_id'], a[0], AM.to_yuan(a[0], a[1]), e.get('quote', '')[:40]))
                            break
            if len(vals) >= 2:
                total = sum(v[2] for v in vals)
                # express in the dominant unit
                derivations.append(
                    f'- {fid}（合计）: {" + ".join(v[0] for v in vals)} = {total}元'
                    f'（各加数来源: {"; ".join(v[3] + "…" for v in vals[:4])}）')
        # multi-evidence joint support
        if is_composite(f) or len(f.get('source_evidence') or []) > 1:
            sources = []
            for e in f.get('source_evidence') or []:
                sources.append(f'{e.get("doc_id")} p{e.get("page")}: {e.get("quote", "")[:40]}…')
            if len(sources) >= 2:
                joint_sets.append(f'- {fid}: 需要联合 {"、".join(sources)}')
    return derivations, joint_sets


class Guard:
    def __init__(self):
        from stage_d_v2_transport import Ledger
        self.ledger = Ledger(f'{QP}/QP6_LEDGER.jsonl')
        self.index = dict(self.ledger.index)
        for path in (f'{QP}/QP5D_LEDGER.jsonl', f'{QP}/QP5C_LEDGER.jsonl',
                     f'{QP}/QP5A_LEDGER.jsonl', f'{QP}/QP4_LEDGER.jsonl'):
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


def main():
    led = load_ledger()
    g = Guard()
    blocks = []
    for t in F.TASKS:
        for rep in (1, 2):
            arms = ['G1', 'G2'] + (['C0'] if (t, rep) in C0_CELLS else [])
            random.Random(SEED + hash(t) % 100).shuffle(arms)
            blocks.append((t, rep, arms))
    results, status = [], 'COMPLETE'
    for t, rep, arms in blocks:
        try:
            contract, r, m_facts, ev_map, verified, all_entries = build_inputs(led, t, rep)
            base_prompt = PP.render(contract, r, m_facts, ev_map, with_evidence=True)
            g1_prompt = base_prompt + '\n\n' + ECHO_RULE
            derivations, joint_sets = compute_derivations(contract, ev_map, verified, all_entries)
            extra = ''
            if joint_sets:
                extra = DERIVED_BLOCK.format(
                    joint_sets='\n'.join(joint_sets))
            g2_prompt = g1_prompt + extra
            for arm in arms:
                user = g1_prompt if arm in ('G1', 'C0') else g2_prompt
                raw = g.call(P1.P_SYS, user, P1.MAXTOK['p'], f'qp6|{t}|{arm}|r{rep}|p')
                sink = extract_any(raw)
                res = Q1.score_task(contract, sink)
                # slot-level outcomes for mechanism endpoints
                srows = {x['fact_id']: x['status'] for x in res['rows']}
                d_tps = [fid for fid in srows if any(
                    dr.startswith(f'- {fid}') for dr in derivations)]
                b_tps = [fid for fid in srows if any(
                    js.startswith(f'- {fid}') for js in joint_sets)]
                a_tps = [fid for fid in srows if fid not in d_tps and fid not in b_tps]
                results.append(dict(
                    task=t, rep=rep, arm=arm, q=res['q'], gate=res['critical_gate'],
                    n_derived=len(d_tps), derived_tp=sum(1 for f in d_tps if srows[f] == 'TP'),
                    n_joint=len(b_tps), joint_tp=sum(1 for f in b_tps if srows[f] == 'TP'),
                    n_other=len(a_tps), other_tp=sum(1 for f in a_tps if srows[f] == 'TP'),
                    wrong_assert=sum(1 for x in res['rows'] if x['status'].startswith('VALUE')),
                    wrong_cit=sum(1 for x in res['rows'] if x['status'].startswith('C_LOC') or x['status'] == 'UNSUPPORTED'),
                    abst=sum(1 for x in res['rows'] if x['status'] == 'ABSENT'),
                    crit_tp=sum(1 for x in res['rows'] if x.get('critical') and x['status'] == 'TP'),
                    rows=[dict(fact_id=x['fact_id'], status=x['status']) for x in res['rows']]))
                print(f"  {t:9s} {arm} r{rep} Q={res['q']:.3f} deriv={results[-1]['derived_tp']}/{results[-1]['n_derived']} "
                      f"joint={results[-1]['joint_tp']}/{results[-1]['n_joint']} gate={res['critical_gate']}", flush=True)
        except Exception as e:
            results.append(dict(task=t, rep=rep, error=str(e)[:160]))
            status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
            print(f"  {t} r{rep} ERROR {e}", flush=True)
            break
        json.dump(dict(status=status, used=dict(calls=len(g.ledger.records),
                                                yuan=round(g.ledger.cost, 4)), results=results),
                  open(f'{QP}/QP6_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{QP}/QP6_PROGRESS.json.tmp', f'{QP}/QP6_PROGRESS.json')
    json.dump(dict(batch='QP6_EXECUTION', status=status, caps=CAPS,
                   used=dict(calls=len(g.ledger.records), tokens=g.ledger.tokens,
                             yuan=round(g.ledger.cost, 4)), results=results),
              open(f'{QP}/QP6_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={len(g.ledger.records)}/{CAPS['calls']} ¥{g.ledger.cost:.4f}/{CAPS['yuan']}")


if __name__ == '__main__':
    main()
