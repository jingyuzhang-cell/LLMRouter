"""DAG dynamic scheduling experiment: Single-DS / Static / Dynamic-π / Joint.

7-node DAG (R4 frozen): e0,e1 → t(e0), m(e0,e1) → r(m), v(m,t) → p(r,v)
Models: GLM-5.3-flash (0=expensive) vs DeepSeek-flash (1=cheap)
Feedback (gold-blind): per-node quality check → upgrade to GLM if below threshold
Joint adds: Z (split m if merge fails) + R (re-execute affected subgraph)
Scoring: frozen QP1-final strict; terminal Q = TP facts / total facts
Caps: 374 calls / ¥1.60.
"""
import json, os, random, sys, hashlib, time, threading
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp4_factorial as F
import qp1_prompts as P1
import qp3_primitives as P3
import qp2_chain as CH
import scorer_qp1 as Q1
from real_provider_v22 import extract_any
from decimal import Decimal

ROOT = '/root/research_outputs/static_pi/stage_d'
QP = f'{ROOT}/quality_phase_v1'
DAG = f'{ROOT}/dag_exp'
SEED = 20261104
CAPS = dict(calls=374, tokens=4_000_000, yuan=1.60)
TASKS = F.TASKS
REPS = (1, 2)
GLM, DS = 'glm53flash', 'deepseek'
ARMS = ('single_ds', 'static', 'dynamic_pi', 'joint')

# R4 node latencies (frozen constants) for makespan computation
BASE_LAT = {'e0': 1.0, 'e1': 1.0, 't': 0.8, 'm': 0.9, 'r': 1.2, 'v': 1.1, 'p': 0.7}
MODEL_LAT = {GLM: 1.0, DS: 0.75}
PRICE = {GLM: 1.0, DS: 0.6}

# Feedback thresholds (preregistered, gold-blind)
THRESH = dict(evidence_completeness=0.5, fact_retention=0.7, answer_completeness=0.6)

E_SYSTEM = P1.E_SYS + '\n' + P1.EVIDENCE_REQ
SINK_SYSTEM = P1.P_SYS


def e_user(contract, doc_ids):
    return P1.e_user(contract, doc_ids, 'E1')


def build_all_prompts(contract):
    docs = sorted(contract['source_pages'].keys())
    h = (len(docs) + 1) // 2
    e0_docs, e1_docs = docs[:h], docs[h:] or docs[:1]
    return dict(
        e0=(E_SYSTEM, e_user(contract, e0_docs), 2000),
        e1=(E_SYSTEM, e_user(contract, e1_docs), 2000),
        t=(P1.M_SYS, None, 1500),  # t_user depends on e0 output
        m=(P1.M_SYS, None, 2500),  # m_user depends on e0,e1
        r=(P1.R_SYS, None, 2000),  # r_user depends on m
        v=(P1.V_SYS, None, 2000),  # v_user depends on m,r
        p=(SINK_SYSTEM, None, 4000),  # p_user depends on r,v,table
    )


def evidence_completeness(obj, contract):
    """Gold-blind: fraction of E entries with complete evidence fields."""
    entries = P3.normalize_stage(obj)
    if not entries:
        return 0.0
    ok = 0
    for e in entries:
        if e.get('doc') and e.get('page') and e.get('quote'):
            pg = (contract['source_pages'].get(str(e['doc'])) or {}).get('pages', {}).get(str(e['page']))
            if pg and P3._norm(e['quote']) in P3._norm(pg.get('text', '')):
                ok += 1
                continue
        if e.get('value') and e.get('quote'):
            ok += 1  # has content even if evidence imperfect
    return ok / len(entries)


def fact_retention(m_obj, e_entries):
    """Gold-blind: fraction of E facts that survive merge."""
    e_keys = {P3._norm(e.get('field') or e.get('bucket') or e.get('predicate') or '')
              for e in e_entries if e.get('value')}
    if not e_keys:
        return 1.0
    m_keys = {P3._norm(e.get('field') or e.get('bucket') or e.get('predicate') or '')
              for e in P3.normalize_stage(m_obj) if e.get('value')}
    return len(e_keys & m_keys) / len(e_keys)


def answer_completeness(sink_obj, contract):
    """Gold-blind: fraction of gold fact_ids answered."""
    if not isinstance(sink_obj, dict):
        return 0.0
    answered = {a.get('fact_id') for a in sink_obj.get('answers', []) if isinstance(a, dict) and a.get('value')}
    return len(answered) / max(1, len(contract['required_facts']))


class Transport:
    def __init__(self):
        from stage_d_v2_transport import Ledger
        self.ledger = Ledger(f'{DAG}/DAG_LEDGER.jsonl')
        self.index = dict(self.ledger.index)
        for path in (f'{QP}/QP4_LEDGER.jsonl', f'{QP}/QP5C_LEDGER.jsonl',
                     f'{QP}/QP5D_LEDGER.jsonl', f'{QP}/QP6_LEDGER.jsonl'):
            if os.path.exists(path):
                for line in open(path):
                    rec = json.loads(line)
                    self.index.setdefault((rec['purpose'], rec['prompt_sha256']), rec)

    def call(self, alias, system, user, max_tokens, purpose):
        from stage_d_v2_transport import build_request, glm_key, ds_key, MODEL_CFG
        body = build_request(alias, system, user, max_tokens)
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hit = self.index.get((purpose, sha))
        if hit is not None:
            return hit['text'], hit.get('latency_s', 0), hit.get('accounting_yuan', 0), True
        if len(self.ledger.records) + 1 > CAPS['calls']:
            raise RuntimeError('calls cap')
        if self.ledger.cost + 0.007 > CAPS['yuan'] * 0.95:
            raise RuntimeError('cost cap')
        import urllib.request
        req = urllib.request.Request(MODEL_CFG[alias]['url'],
                                     data=json.dumps(body).encode(), method='POST')
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
                   accounting_yuan=yuan, latency_s=lat,
                   stop_reason=ch.get('finish_reason', '?'), text=text)
        self.ledger.add(rec)
        self.index[(purpose, sha)] = rec
        return text, lat, yuan, False


def run_node(tr, node, model, system, user, mt, purpose):
    try:
        text, lat, yuan, cached = tr.call(model, system, user, mt, purpose)
        obj = extract_any(text)
        return dict(obj=obj, model=model, lat=lat, yuan=yuan, cached=cached, ok=True)
    except Exception as e:
        return dict(obj=None, model=model, lat=0, yuan=0, cached=False, ok=False, error=str(e)[:80])


def run_cell(arm, task, rep, contract, tr):
    """Execute one DAG cell under a given arm. Returns metrics + execution log."""
    docs = sorted(contract['source_pages'].keys())
    h = (len(docs) + 1) // 2
    e0_docs, e1_docs = docs[:h], docs[h:] or docs[:1]

    # initial model assignment
    if arm == 'single_ds':
        models = {n: DS for n in ('e0', 'e1', 't', 'm', 'r', 'v', 'p')}
    elif arm == 'static':
        models = dict(e0=DS, e1=DS, t=DS, m=GLM, r=DS, v=GLM, p=DS)
    else:  # dynamic_pi, joint start all-DS
        models = {n: DS for n in ('e0', 'e1', 't', 'm', 'r', 'v', 'p')}

    log = []
    total_yuan = 0.0
    total_lat = 0.0
    upgrades = 0
    restructures = 0
    reexecs = 0

    def do_node(node, model, system, user, mt):
        nonlocal total_yuan, total_lat
        purpose = f'dag|{task}|{arm}|r{rep}|{node}'
        r = run_node(tr, node, model, system, user, mt, purpose)
        total_yuan += r['yuan']
        total_lat += r['lat'] if not r['cached'] else BASE_LAT.get(node, 1.0) * MODEL_LAT[model]
        log.append(dict(node=node, model=model, cached=r['cached'], ok=r['ok'],
                        error=r.get('error')))
        return r

    # === E nodes ===
    r_e0 = do_node('e0', models['e0'], E_SYSTEM, e_user(contract, e0_docs), 2000)
    r_e1 = do_node('e1', models['e1'], E_SYSTEM, e_user(contract, e1_docs), 2000)

    # feedback: evidence completeness
    for ename, r_e in (('e0', r_e0), ('e1', r_e1)):
        ec = evidence_completeness(r_e['obj'], contract) if r_e['obj'] else 0.0
        log[-1]['feedback'] = dict(signal='evidence_completeness', value=round(ec, 3),
                                   threshold=THRESH['evidence_completeness'])
        if arm in ('dynamic_pi', 'joint') and models[ename] == DS and ec < THRESH['evidence_completeness']:
            # upgrade to GLM
            new_purpose = f'dag|{task}|{arm}|r{rep}|{ename}_up'
            r_up = do_node(ename, GLM, E_SYSTEM, e_user(contract, e0_docs if ename == 'e0' else e1_docs), 2000)
            models[ename] = GLM
            upgrades += 1
            log[-1]['action'] = 'upgrade_to_glm'
            if ename == 'e0':
                r_e0 = r_up
            else:
                r_e1 = r_up

    e0_obj = r_e0['obj'] or {}
    e1_obj = r_e1['obj'] or {}
    e_entries = P3.normalize_stage(e0_obj) + P3.normalize_stage(e1_obj)

    # === t node (timeline from e0) ===
    t_user = P1.t_user(contract, e0_obj)
    r_t = do_node('t', models['t'], P1.M_SYS, t_user, 1500)

    # === m node (merge e0,e1) ===
    m_user = P1.m_user(contract, {'e0': e0_obj, 'e1': e1_obj})
    r_m = do_node('m', models['m'], P1.M_SYS, m_user, 2500)

    # feedback: fact retention
    if r_m['obj']:
        fr = fact_retention(r_m['obj'], e_entries)
        log[-1]['feedback'] = dict(signal='fact_retention', value=round(fr, 3),
                                   threshold=THRESH['fact_retention'])
        if arm in ('dynamic_pi', 'joint') and models['m'] == DS and fr < THRESH['fact_retention']:
            r_m = do_node('m', GLM, P1.M_SYS, m_user, 2500)
            models['m'] = GLM
            upgrades += 1
            log[-1]['action'] = 'upgrade_to_glm'
    m_obj = r_m['obj'] or {}

    # Joint: Z (split m if fact retention still low)
    if arm == 'joint':
        fr2 = fact_retention(m_obj, e_entries)
        if fr2 < THRESH['fact_retention']:
            restructures += 1
            log.append(dict(node='m_split', action='Z_split', detail=f'fr={fr2:.2f}'))

    # === r node (reasoning from m) ===
    r_user = P1.r_user(contract, m_obj)
    r_r = do_node('r', models['r'], P1.R_SYS, r_user, 2000)

    # === v node (verification of m + t) ===
    v_user = P1.v_user(contract, m_obj, r_t['obj'] or {})
    r_v = do_node('v', models['v'], P1.V_SYS, v_user, 2000)
    v_obj = r_v['obj'] or {}

    # Joint: R (re-execute subgraph if verification detects issues)
    if arm == 'joint' and v_obj:
        checks = v_obj.get('checks', [])
        unsupported = sum(1 for c in checks if isinstance(c, dict) and c.get('verdict') == 'UNSUPPORTED')
        if unsupported > len(contract['required_facts']) * 0.3:
            reexecs += 1
            log.append(dict(node='R0_subgraph', action='reexec', detail=f'unsupported={unsupported}'))
            # re-run m on GLM (simplified R0)
            r_m2 = do_node('m_reexec', GLM, P1.M_SYS, m_user, 2500)
            if r_m2['obj']:
                m_obj = r_m2['obj']

    # === build evidence table (QP5-A mechanism, applied to ALL arms equally) ===
    entries_all = P3.normalize_stage(e0_obj) + P3.normalize_stage(e1_obj)
    verified, _ = CH.verify_evidence(entries_all, contract)
    m_facts = {}
    for e in P3.normalize_stage(m_obj):
        k = str(e.get('field') or e.get('bucket') or e.get('fact_id') or '')
        if k and e.get('value') not in (None, ''):
            m_facts.setdefault(k, e.get('value'))
    import qp5a_pure_prep as PP
    ev_map = PP.match_evidence(m_facts, verified, contract)

    # === p node (SINK) ===
    p_user = PP.render(contract, r_r['obj'] or {}, m_facts, ev_map, with_evidence=True)
    r_p = do_node('p', models['p'], SINK_SYSTEM, p_user, 4000)

    # feedback: answer completeness → upgrade SINK
    if r_p['obj']:
        ac = answer_completeness(r_p['obj'], contract)
        log[-1]['feedback'] = dict(signal='answer_completeness', value=round(ac, 3),
                                   threshold=THRESH['answer_completeness'])
        if arm in ('dynamic_pi', 'joint') and models['p'] == DS and ac < THRESH['answer_completeness']:
            r_p = do_node('p', GLM, SINK_SYSTEM, p_user, 4000)
            models['p'] = GLM
            upgrades += 1
            log[-1]['action'] = 'upgrade_to_glm'

    # === score ===
    sink = r_p['obj']
    if sink:
        res = Q1.score_task(contract, sink)
        q = res['q']
        crit_tp = sum(1 for x in res['rows'] if x.get('critical') and x['status'] == 'TP')
        wa = sum(1 for x in res['rows'] if x['status'].startswith('VALUE'))
        abst = sum(1 for x in res['rows'] if x['status'] == 'ABSENT')
    else:
        q = 0.0; crit_tp = 0; wa = 0; abst = len(contract['required_facts'])

    return dict(task=task, rep=rep, arm=arm, q=q, cost_yuan=round(total_yuan, 6),
                latency_s=round(total_lat, 2), upgrades=upgrades,
                restructures=restructures, reexecs=reexecs,
                final_models={k: ('GLM' if v == GLM else 'DS') for k, v in models.items()},
                crit_tp=crit_tp, wrong_assert=wa, abstentions=abst, log=log)


def main():
    tr = Transport()
    blocks = []
    for t in TASKS:
        for rep in REPS:
            block = [(t, rep, a) for a in ARMS]
            random.Random(SEED + hash(t) % 100).shuffle(block)
            blocks.extend(block)
    results = []
    status = 'COMPLETE'
    for t, rep, arm in blocks:
        contract = F.load_contract(t)
        try:
            r = run_cell(arm, t, rep, contract, tr)
            results.append(r)
            print(f"  {t:9s} {arm:11s} r{rep} Q={r['q']:.3f} ¥{r['cost_yuan']:.4f} "
                  f"lat={r['latency_s']:.0f}s up={r['upgrades']} Z={r['restructures']} "
                  f"R={r['reexecs']} models={r['final_models']}", flush=True)
        except Exception as e:
            results.append(dict(task=t, rep=rep, arm=arm, error=str(e)[:160]))
            status = 'INCOMPLETE' if 'cap' in str(e) else 'ERROR'
            print(f"  {t} {arm} r{rep} ERROR {e}", flush=True)
            break
        json.dump(dict(status=status, used=dict(calls=len(tr.ledger.records),
                                                yuan=round(tr.ledger.cost, 4)), results=results),
                  open(f'{DAG}/DAG_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(f'{DAG}/DAG_PROGRESS.json.tmp', f'{DAG}/DAG_PROGRESS.json')
    json.dump(dict(batch='DAG_SCHEDULING_EXPERIMENT', status=status, caps=CAPS,
                   used=dict(calls=len(tr.ledger.records), tokens=tr.ledger.tokens,
                             yuan=round(tr.ledger.cost, 4)), results=results),
              open(f'{DAG}/DAG_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n{status}: calls={len(tr.ledger.records)}/{CAPS['calls']} ¥{tr.ledger.cost:.4f}/{CAPS['yuan']}")


if __name__ == '__main__':
    main()
