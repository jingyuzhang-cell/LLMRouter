"""QP8: E-layer upgrade causal verification. A (DS E) / B (GLM E) / C (dynamic E).

7 tractable tasks × 2 reps × 3 arms.
A: all-DS E (cached from QP7 single_ds) → read results directly
B: GLM E (fresh) + DS downstream (fresh) → measures E upgrade value
C: DS E start, upgrade to GLM if evidence coverage < 0.40 → dynamic E
Evidence gate (0.40) and format adaptation applied identically to all arms.
Caps: 200 calls / ¥1.40.
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
import qp5a_pure_prep as PP
import scorer_qp1 as Q1
from real_provider_v22 import extract_any

ROOT = '/root/research_outputs/static_pi/stage_d'
QP = f'{ROOT}/quality_phase_v1'
QP7 = f'{ROOT}/qp7'
QP8 = f'{ROOT}/qp8'
os.makedirs(QP8, exist_ok=True)

SEED = 20261104
CAPS = dict(calls=200, tokens=2_500_000, yuan=1.40)
GATE_THRESHOLD = 0.40
TASKS = ['E06', 'MVR1', 'KANGMEI', 'GUOEN', 'ZIJING', 'ZEDA', 'ZHANGZIDAO']
ARMS = ('A_ds_e', 'B_glm_e', 'C_dyn_e')
GLM, DS = 'glm53flash', 'deepseek'
E_SYSTEM = P1.E_SYS + '\n' + P1.EVIDENCE_REQ


def load_contract(ev):
    p = [t for t in json.load(open(f'{ROOT}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if t['event_key'] == ev][0]['contract']
    if not os.path.isabs(p): p = f'{ROOT}/v23a/{p}'
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
        nc = num.replace(',', '').replace('，', '')
        try:
            d = Decimal(nc)
            if unit == '亿元': return str(int(d*100_000_000)) if d==int(d) else str(d*100_000_000)
            if unit == '万元': return str(int(d*10_000)) if d==int(d) else str(d*10_000)
            return nc
        except: return None
    if len(am) > 1: return None
    if len(quote) <= 40:
        cjk = re.findall(r'[\u4e00-\u9fff]{3,}', quote)
        if len(cjk) == 1: return cjk[0]
    return None


def adapt_ds(raw):
    out = []
    if not isinstance(raw, dict): return out
    for b, c in raw.items():
        if isinstance(c, list):
            for i in c:
                if isinstance(i, dict) and i.get('quote'):
                    v = extract_value_gold_blind(i['quote'])
                    out.append(dict(field=b, value=v, raw=str(v) if v else None,
                                    doc=i.get('doc'), page=i.get('page'), quote=i.get('quote','')))
        elif isinstance(c, dict):
            for sk, i in c.items():
                if isinstance(i, dict) and i.get('quote'):
                    v = extract_value_gold_blind(i['quote'])
                    out.append(dict(field=f'{b}/{sk}', value=v, raw=str(v) if v else None,
                                    doc=i.get('doc'), page=i.get('page'), quote=i.get('quote','')))
    return out


def coverage(contract, verified):
    cov = set()
    for f in contract['required_facts']:
        for e in verified:
            if P3.name_matches(e, f) or Q1.value_in_quote(f.get('value'), e.get('quote','')):
                cov.add(f['fact_id']); break
    return len(cov) / len(contract['required_facts'])


class Transport:
    def __init__(self):
        from stage_d_v2_transport import Ledger
        self.ledger = Ledger(f'{QP8}/QP8_LEDGER.jsonl')
        self.index = dict(self.ledger.index)
        for path in (f'{QP7}/QP7_LEDGER.jsonl', f'{QP}/QP4_LEDGER.jsonl'):
            if os.path.exists(path):
                for line in open(path):
                    r = json.loads(line)
                    self.index.setdefault((r['purpose'], r['prompt_sha256']), r)

    def call(self, alias, sys_p, user, mt, purpose):
        from stage_d_v2_transport import build_request, glm_key, ds_key, MODEL_CFG
        body = build_request(alias, sys_p, user, mt)
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hit = self.index.get((purpose, sha))
        if hit: return hit['text'], 0, 0
        if len(self.ledger.records)+1 > CAPS['calls']: raise RuntimeError('calls cap')
        if self.ledger.cost+0.008 > CAPS['yuan']*0.95: raise RuntimeError('cost cap')
        import urllib.request
        req = urllib.request.Request(MODEL_CFG[alias]['url'], data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type','application/json')
        k = glm_key() if alias=='glm53flash' else ds_key()
        req.add_header('authorization','Bearer '+k)
        t0=time.monotonic()
        with urllib.request.urlopen(req,timeout=180) as r: d=json.loads(r.read().decode())
        ch=d['choices'][0]; u=d.get('usage',{})
        c=ch.get('message',{}).get('content','')
        text=''.join(x.get('text','') for x in c if isinstance(x,dict)) if isinstance(c,list) else (c or '')
        tin,tout=u.get('prompt_tokens',0),u.get('completion_tokens',0)
        yuan=round(tin*0.8e-6+tout*2.8e-6,8)
        lat=round(time.monotonic()-t0,3)
        rec=dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'),alias=alias,purpose=purpose,
                 prompt_sha256=sha,usage=dict(input_tokens=tin,output_tokens=tout),
                 accounting_yuan=yuan,latency_s=lat,text=text)
        self.ledger.add(rec)
        self.index[(purpose,sha)]={'text':text}
        return text,lat,yuan


def run_cell(arm, task, rep, contract, tr):
    docs = sorted(contract['source_pages'].keys())
    h = (len(docs)+1)//2
    e0_docs, e1_docs = docs[:h], docs[h:] or docs[:1]
    cost = 0.0; lat = 0.0; e_upgrades = 0

    def do(node, model, sys_p, user, mt):
        nonlocal cost, lat
        p = f'qp8|{task}|{arm}|r{rep}|{node}'
        try:
            text, l, y = tr.call(model, sys_p, user, mt, p)
            cost += y; lat += l
            return extract_any(text)
        except: return None

    # === E layer (the experimental variable) ===
    if arm == 'A_ds_e':
        e0_model, e1_model = DS, DS
        e0 = do('e0', DS, E_SYSTEM, P1.e_user(contract, e0_docs, 'E1'), 2000)
        e1 = do('e1', DS, E_SYSTEM, P1.e_user(contract, e1_docs, 'E1'), 2000)
    elif arm == 'B_glm_e':
        e0_model, e1_model = GLM, GLM
        e0 = do('e0', GLM, E_SYSTEM, P1.e_user(contract, e0_docs, 'E1'), 2000)
        e1 = do('e1', GLM, E_SYSTEM, P1.e_user(contract, e1_docs, 'E1'), 2000)
    else:  # C_dyn_e
        e0_model, e1_model = DS, DS
        e0 = do('e0', DS, E_SYSTEM, P1.e_user(contract, e0_docs, 'E1'), 2000)
        e1 = do('e1', DS, E_SYSTEM, P1.e_user(contract, e1_docs, 'E1'), 2000)
        # check coverage, upgrade if needed
        adapted = adapt_ds(e0) + adapt_ds(e1)
        ver_check, _ = CH.verify_evidence(adapted, contract)
        cov = coverage(contract, ver_check)
        if cov < GATE_THRESHOLD:
            e0 = do('e0_up', GLM, E_SYSTEM, P1.e_user(contract, e0_docs, 'E1'), 2000)
            e1 = do('e1_up', GLM, E_SYSTEM, P1.e_user(contract, e1_docs, 'E1'), 2000)
            e0_model, e1_model = GLM, GLM
            e_upgrades = 2

    # === downstream (fixed DS for all arms) ===
    t = do('t', DS, P1.M_SYS, P1.t_user(contract, e0 or {}), 1500)
    m = do('m', DS, P1.M_SYS, P1.m_user(contract, {'e0': e0 or {}, 'e1': e1 or {}}), 2500)
    r = do('r', DS, P1.R_SYS, P1.r_user(contract, m or {}), 2000)
    v = do('v', DS, P1.V_SYS, P1.v_user(contract, m or {}, t or {}), 2000)

    # evidence table with format adaptation + gating
    if e0_model == DS:
        adapted = adapt_ds(e0) + adapt_ds(e1)
    else:
        adapted = P3.normalize_stage(e0) + P3.normalize_stage(e1)
    verified, _ = CH.verify_evidence(adapted, contract)
    cov = coverage(contract, verified)
    gate_open = cov >= GATE_THRESHOLD

    m_facts = {}
    for e in P3.normalize_stage(m or {}):
        k = PP.fact_key(e)
        if k and e.get('value') not in (None, ''): m_facts.setdefault(k, e.get('value'))

    if gate_open:
        ev_map = PP.match_evidence(m_facts, verified, contract)
        p_user = PP.render(contract, r or {}, m_facts, ev_map, with_evidence=True)
    else:
        ev_map = {}
        p_user = PP.render(contract, r or {}, m_facts, ev_map, with_evidence=False)

    p = do('p', DS, P1.P_SYS, p_user, 4000)

    res = Q1.score_task(contract, p) if p else dict(q=0, rows=[], critical_gate='FAIL')
    return dict(task=task, rep=rep, arm=arm, q=res['q'],
                cost_yuan=round(cost,6), latency_s=round(lat,2),
                e_model='GLM' if e0_model==GLM else 'DS',
                e_upgrades=e_upgrades, evidence_coverage=round(cov,3),
                gate_action='open' if gate_open else 'closed',
                n_verified=len(verified), n_ev_map=len(ev_map),
                crit_tp=sum(1 for x in res.get('rows',[]) if x.get('critical') and x['status']=='TP'),
                wrong_assert=sum(1 for x in res.get('rows',[]) if x['status'].startswith('VALUE')),
                abst=sum(1 for x in res.get('rows',[]) if x['status']=='ABSENT'))


def main():
    tr = Transport()
    blocks = []
    for t in TASKS:
        for rep in (1,2):
            arms = list(ARMS)
            random.Random(SEED+hash(t)%100).shuffle(arms)
            for a in arms: blocks.append((t,rep,a))
    results = []
    status = 'COMPLETE'
    for t,rep,arm in blocks:
        try:
            c = load_contract(t)
            r = run_cell(arm,t,rep,c,tr)
            results.append(r)
            print(f"  {t:12s} {arm:8s} r{rep} Q={r['q']:.3f} cov={r['evidence_coverage']:.2f} "
                  f"gate={r['gate_action']:6s} e={r['e_model']} ¥{r['cost_yuan']:.4f}", flush=True)
        except Exception as e:
            results.append(dict(task=t,rep=rep,arm=arm,error=str(e)[:160]))
            status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
            print(f"  {t} {arm} r{rep} ERROR {e}", flush=True)
            if 'cap' in str(e): break
        json.dump(dict(status=status,used=dict(calls=len(tr.ledger.records),
            yuan=round(tr.ledger.cost,4)),results=results),
            open(f'{QP8}/QP8_PROGRESS.json.tmp','w'),ensure_ascii=False,indent=1)
        os.replace(f'{QP8}/QP8_PROGRESS.json.tmp',f'{QP8}/QP8_PROGRESS.json')
    json.dump(dict(batch='QP8_E_UPGRADE',status=status,caps=CAPS,
                   gate_threshold=GATE_THRESHOLD,tasks=TASKS,
                   used=dict(calls=len(tr.ledger.records),yuan=round(tr.ledger.cost,4)),
                   results=results),
              open(f'{QP8}/QP8_RESULTS.json','w'),ensure_ascii=False,indent=1)
    print(f"\n{status}: calls={len(tr.ledger.records)}/{CAPS['calls']} ¥{tr.ledger.cost:.4f}/{CAPS['yuan']}")


if __name__=='__main__': main()
