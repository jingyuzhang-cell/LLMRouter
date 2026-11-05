"""QP7: Evidence-aware heterogeneous DAG dynamic joint scheduling.
Four arms × 12 tasks × 2 reps. 7-node DAG (R4 frozen).
Evidence gating (threshold 0.40) integrated into Dynamic-π and Joint.
Format adaptation for DS E outputs. Caps: 500 calls / ¥3.50.
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
from real_provider_v22 import extract_any

ROOT = '/root/research_outputs/static_pi/stage_d'
QP = f'{ROOT}/quality_phase_v1'
QP7 = f'{ROOT}/qp7'
DAG = f'{ROOT}/dag_exp'
os.makedirs(QP7, exist_ok=True)

SEED = 20261104
CAPS = dict(calls=500, tokens=6_000_000, yuan=3.50)
GATE_THRESHOLD = 0.40

ALL_TASKS = ['E06', 'MVR1', 'KANGMEI', 'GUOEN', 'ZIJING', 'ZEDA',
             'ZHANGZIDAO', 'KDX', 'YJT', 'MVR2', 'E04', 'E08']
ARMS = ('single_ds', 'static', 'dynamic_pi', 'joint')
GLM, DS = 'glm53flash', 'deepseek'

E_SYSTEM = P1.E_SYS + '\n' + P1.EVIDENCE_REQ


def load_contract(ev):
    p = [t for t in json.load(open(f'{ROOT}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if t['event_key'] == ev][0]['contract']
    if not os.path.isabs(p):
        p = f'{ROOT}/v23a/{p}'
    return json.load(open(p))


def extract_value_gold_blind(quote):
    if not quote: return None
    dm = re.search(r'(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})\s*日?', quote)
    if dm: return f'{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}'
    nm = re.search(r'([证处]监?\w*字\s*[\[〔【]?\d{4}[\]〕】]?\s*\d+\s*号)', quote)
    if nm: return re.sub(r'\s+', '', nm.group(1))
    am = re.findall(r'(\d[\d,，.]+)\s*(亿元|万元|元|%)', quote)
    if len(am) == 1:
        num, unit = am[0]
        num_clean = num.replace(',', '').replace('，', '')
        try:
            d = Decimal(num_clean)
            if unit == '亿元': return str(int(d * 100_000_000)) if d == int(d) else str(d * 100_000_000)
            if unit == '万元': return str(int(d * 10_000)) if d == int(d) else str(d * 10_000)
            return num_clean
        except Exception: return None
    if len(am) > 1: return None
    if len(quote) <= 40:
        cjk = re.findall(r'[\u4e00-\u9fff]{3,}', quote)
        if len(cjk) == 1: return cjk[0]
    return None


def adapt_ds_output(raw_obj):
    adapted = []
    if not isinstance(raw_obj, dict): return adapted
    for bucket, content in raw_obj.items():
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('quote'):
                    v = extract_value_gold_blind(item['quote'])
                    adapted.append(dict(field=bucket, value=v, raw=str(v) if v else None,
                                        doc=item.get('doc'), page=item.get('page'), quote=item.get('quote', '')))
        elif isinstance(content, dict):
            for sk, item in content.items():
                if isinstance(item, dict) and item.get('quote'):
                    v = extract_value_gold_blind(item['quote'])
                    adapted.append(dict(field=f'{bucket}/{sk}', value=v, raw=str(v) if v else None,
                                        doc=item.get('doc'), page=item.get('page'), quote=item.get('quote', '')))
    return adapted


def evidence_completeness(obj, contract):
    entries = P3.normalize_stage(obj)
    if not entries: return 0.0
    ok = sum(1 for e in entries if e.get('doc') and e.get('quote'))
    return ok / len(entries)


def fact_retention(m_obj, e_keys):
    m_keys = {P3._norm(e.get('field') or e.get('bucket') or e.get('predicate') or '')
              for e in P3.normalize_stage(m_obj) if e.get('value')}
    return len(e_keys & m_keys) / len(e_keys) if e_keys else 1.0


def answer_completeness(sink_obj, contract):
    if not isinstance(sink_obj, dict): return 0.0
    answered = {a.get('fact_id') for a in sink_obj.get('answers', []) if isinstance(a, dict) and a.get('value')}
    return len(answered) / max(1, len(contract['required_facts']))


def compute_coverage(contract, verified):
    covered = set()
    for f in contract['required_facts']:
        for e in verified:
            if P3.name_matches(e, f) or Q1.value_in_quote(f.get('value'), e.get('quote', '')):
                covered.add(f['fact_id']); break
    return len(covered) / len(contract['required_facts'])


class Transport:
    def __init__(self):
        from stage_d_v2_transport import Ledger
        self.ledger = Ledger(f'{QP7}/QP7_LEDGER.jsonl')
        self.index = dict(self.ledger.index)
        for path in (f'{DAG}/DAG_LEDGER.jsonl', f'{QP}/QP4_LEDGER.jsonl', f'{QP}/QP5C_LEDGER.jsonl'):
            if os.path.exists(path):
                for line in open(path):
                    rec = json.loads(line)
                    self.index.setdefault((rec['purpose'], rec['prompt_sha256']), rec)

    def call(self, alias, system, user, mt, purpose):
        from stage_d_v2_transport import build_request, glm_key, ds_key, MODEL_CFG
        body = build_request(alias, system, user, mt)
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hit = self.index.get((purpose, sha))
        if hit is not None:
            return hit['text'], 0, 0, True
        if len(self.ledger.records) + 1 > CAPS['calls']:
            raise RuntimeError('calls cap')
        if self.ledger.cost + 0.008 > CAPS['yuan'] * 0.95:
            raise RuntimeError('cost cap')
        import urllib.request
        req = urllib.request.Request(MODEL_CFG[alias]['url'], data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        key = glm_key() if alias == 'glm53flash' else ds_key()
        req.add_header('authorization', 'Bearer ' + key)
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
        self.ledger.add(rec)
        self.index[(purpose, sha)] = {'text': text}
        return text, lat, yuan, False


def run_cell(arm, task, rep, contract, tr):
    docs = sorted(contract['source_pages'].keys())
    h = (len(docs) + 1) // 2
    e0_docs, e1_docs = docs[:h], docs[h:] or docs[:1]

    if arm == 'single_ds':
        models = {n: DS for n in ('e0','e1','t','m','r','v','p')}
    elif arm == 'static':
        models = dict(e0=DS, e1=DS, t=DS, m=GLM, r=DS, v=GLM, p=DS)
    else:
        models = {n: DS for n in ('e0','e1','t','m','r','v','p')}

    total_yuan = 0.0; total_lat = 0.0; upgrades = 0; z_count = 0; r_count = 0
    gate_action = 'n/a'; gate_coverage = None

    def do(node, model, system, user, mt):
        nonlocal total_yuan, total_lat
        purpose = f'qp7|{task}|{arm}|r{rep}|{node}'
        try:
            text, lat, yuan, cached = tr.call(model, system, user, mt, purpose)
            total_yuan += yuan
            total_lat += lat if not cached else 0
            obj = extract_any(text)
            return dict(obj=obj, ok=True)
        except Exception as e:
            return dict(obj=None, ok=False, error=str(e)[:60])

    # E nodes
    r_e0 = do('e0', models['e0'], E_SYSTEM, P1.e_user(contract, e0_docs, 'E1'), 2000)
    r_e1 = do('e1', models['e1'], E_SYSTEM, P1.e_user(contract, e1_docs, 'E1'), 2000)

    # Dynamic upgrade for E
    for ename, r_e, e_docs in (('e0', r_e0, e0_docs), ('e1', r_e1, e1_docs)):
        if arm in ('dynamic_pi', 'joint') and models[ename] == DS:
            ec = evidence_completeness(r_e['obj'], contract) if r_e['obj'] else 0.0
            if ec < 0.5:
                r_up = do(f'{ename}_up', GLM, E_SYSTEM, P1.e_user(contract, e_docs, 'E1'), 2000)
                models[ename] = GLM; upgrades += 1
                if ename == 'e0': r_e0 = r_up
                else: r_e1 = r_up

    e0_obj = r_e0['obj'] or {}
    e1_obj = r_e1['obj'] or {}

    # Format adaptation for evidence table
    adapted = adapt_ds_output(e0_obj) + adapt_ds_output(e1_obj)
    raw_entries = P3.normalize_stage(e0_obj) + P3.normalize_stage(e1_obj)
    # Use adapted if available, else raw
    entries_for_verify = adapted if len(adapted) > len(raw_entries) else raw_entries
    verified, _ = CH.verify_evidence(entries_for_verify, contract)

    # t node
    r_t = do('t', models['t'], P1.M_SYS, P1.t_user(contract, e0_obj), 1500)

    # m node
    r_m = do('m', models['m'], P1.M_SYS, P1.m_user(contract, {'e0': e0_obj, 'e1': e1_obj}), 2500)
    e_keys = {P3._norm(e.get('field') or e.get('bucket') or '') for e in raw_entries if e.get('value')}
    if arm in ('dynamic_pi', 'joint') and models['m'] == DS and r_m['obj']:
        fr = fact_retention(r_m['obj'], e_keys)
        if fr < 0.7:
            r_up = do('m_up', GLM, P1.M_SYS, P1.m_user(contract, {'e0': e0_obj, 'e1': e1_obj}), 2500)
            models['m'] = GLM; upgrades += 1
            r_m = r_up
    m_obj = r_m['obj'] or {}

    # Joint: Z (split m if retention still low)
    if arm == 'joint':
        fr2 = fact_retention(m_obj, e_keys)
        if fr2 < 0.7:
            z_count += 1  # record but don't actually split (structural marker)

    # r node
    r_r = do('r', models['r'], P1.R_SYS, P1.r_user(contract, m_obj), 2000)

    # v node
    r_v = do('v', models['v'], P1.V_SYS, P1.v_user(contract, m_obj, r_t['obj'] or {}), 2000)
    v_obj = r_v['obj'] or {}

    # Joint: R (re-execute if verification detects many unsupported)
    if arm == 'joint' and v_obj:
        checks = v_obj.get('checks', [])
        unsupported = sum(1 for c in checks if isinstance(c, dict) and c.get('verdict') == 'UNSUPPORTED')
        if unsupported > len(contract['required_facts']) * 0.3:
            r_count += 1
            r_m2 = do('m_reexec', GLM, P1.M_SYS, P1.m_user(contract, {'e0': e0_obj, 'e1': e1_obj}), 2500)
            if r_m2['obj']: m_obj = r_m2['obj']

    # Evidence gating
    m_facts = {}
    for e in P3.normalize_stage(m_obj):
        k = PP.fact_key(e)
        if k and e.get('value') not in (None, ''): m_facts.setdefault(k, e.get('value'))

    coverage = compute_coverage(contract, verified)
    if arm in ('dynamic_pi', 'joint'):
        gate_action = 'open' if coverage >= GATE_THRESHOLD else 'closed'
        gate_coverage = round(coverage, 3)
    else:
        gate_action = 'always_on'  # static/single always provide
        gate_coverage = round(coverage, 3)

    if gate_action in ('open', 'always_on'):
        ev_map = PP.match_evidence(m_facts, verified, contract)
        p_user = PP.render(contract, r_r['obj'] or {}, m_facts, ev_map, with_evidence=True)
    else:
        ev_map = {}
        p_user = PP.render(contract, r_r['obj'] or {}, m_facts, ev_map, with_evidence=False)

    # p node (SINK)
    r_p = do('p', models['p'], P1.P_SYS, p_user, 4000)

    # Dynamic upgrade for SINK
    if arm in ('dynamic_pi', 'joint') and models['p'] == DS and r_p['obj']:
        ac = answer_completeness(r_p['obj'], contract)
        if ac < 0.6:
            r_up = do('p_up', GLM, P1.P_SYS, p_user, 4000)
            models['p'] = GLM; upgrades += 1
            r_p = r_up

    sink = r_p['obj']
    if sink:
        res = Q1.score_task(contract, sink)
        q = res['q']
        crit_tp = sum(1 for x in res['rows'] if x.get('critical') and x['status'] == 'TP')
        wa = sum(1 for x in res['rows'] if x['status'].startswith('VALUE'))
        wc = sum(1 for x in res['rows'] if x['status'].startswith('C_LOC') or x['status'] == 'UNSUPPORTED')
        abst = sum(1 for x in res['rows'] if x['status'] == 'ABSENT')
    else:
        q = 0.0; crit_tp = 0; wa = 0; wc = 0; abst = len(contract['required_facts'])

    return dict(task=task, rep=rep, arm=arm, q=q, cost_yuan=round(total_yuan, 6),
                latency_s=round(total_lat, 2), upgrades=upgrades, z_count=z_count, r_count=r_count,
                gate_action=gate_action, gate_coverage=gate_coverage,
                final_models={k: ('GLM' if v == GLM else 'DS') for k, v in models.items()},
                crit_tp=crit_tp, wrong_assert=wa, wrong_cit=wc, abstentions=abst)


def main():
    tr = Transport()
    blocks = []
    for t in ALL_TASKS:
        for rep in (1, 2):
            cell_arms = list(ARMS)
            random.Random(SEED + hash(t) % 100).shuffle(cell_arms)
            for a in cell_arms:
                blocks.append((t, rep, a))

    results = []
    status = 'COMPLETE'
    for t, rep, arm in blocks:
        try:
            contract = load_contract(t)
            r = run_cell(arm, t, rep, contract, tr)
            results.append(r)
            print(f"  {t:12s} {arm:11s} r{rep} Q={r['q']:.3f} ¥{r['cost_yuan']:.4f} "
                  f"lat={r['latency_s']:.0f}s up={r['upgrades']} Z={r['z_count']} R={r['r_count']} "
                  f"gate={r['gate_action']}", flush=True)
        except Exception as e:
            results.append(dict(task=t, rep=rep, arm=arm, error=str(e)[:160]))
            status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
            print(f"  {t} {arm} r{rep} ERROR {e}", flush=True)
            if 'cap' in str(e): break
        json.dump(dict(status=status, used=dict(calls=len(tr.ledger.records),
                                                yuan=round(tr.ledger.cost, 4)), results=results),
                  open(f'{QP7}/QP7_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{QP7}/QP7_PROGRESS.json.tmp', f'{QP7}/QP7_PROGRESS.json')

    json.dump(dict(batch='QP7_DAG_SCHEDULING', status=status, caps=CAPS,
                   gate_threshold=GATE_THRESHOLD, tasks=ALL_TASKS,
                   used=dict(calls=len(tr.ledger.records), tokens=tr.ledger.tokens,
                             yuan=round(tr.ledger.cost, 4)), results=results),
              open(f'{QP7}/QP7_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={len(tr.ledger.records)}/{CAPS['calls']} ¥{tr.ledger.cost:.4f}/{CAPS['yuan']}")


if __name__ == '__main__':
    main()
