"""P1b-1 analyzer: primary endpoint table, R_regen enrichment, policy replay.

Zero workflow calls — adjudication + replay only. PRIMARY metrics on the 76
clean-test tasks (96 minus 20 dev); full-96 reported as reference.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, '/root/r3_own_pool')
from static_dag_v0.decompose_v1 import exec_calc
from static_dag_v0.graph_forest_v2_p1b_contract import equiv, mismatch_type, to_vref
from static_dag_v0.tool_aware_v1 import decode

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'static_dag_v0/graph_forest_v2_p1b'
SRC = ROOT / 'static_dag_v0/fresh_static_confirmation'
P02 = ROOT / 'static_dag_v0/graph_forest_v2_p02'
POOL = ['medium', 'large', 'coder']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def run():
    ct = json.loads((OUT / 'CONTRACTS_test_v2.json').read_text())['contracts']
    dry = json.loads((P02 / 'DRYRUN.json').read_text())
    rows = {r['uid']: r for r in dry['fresh_rows'] if r['ok']}
    p02 = json.loads((P02 / 'RESULTS.json').read_text())['per_task']
    p02 = {p['uid']: p for p in p02}
    audit = json.loads((P02 / 'P1B_AUDIT.json').read_text())
    oracle_equiv = {}
    for g in audit['groups'].values():
        for t in g['tasks']:
            oracle_equiv[t['uid']] = t['equiv_gold']
    dev = {r['task_uid'] for r in json.loads(
        (ROOT / 'static_dag_v0/graph_forest_v1/RESULTS.json').read_text())['rows']}
    nodes = json.loads((SRC / 'NODES.json').read_text())
    rs = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':rs')}
    tasks = {t['uid']: t for t in json.loads((SRC / 'TASKS.json').read_text())}
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    devs = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    resp = {}
    for slot in POOL:
        for line in (SRC / f'{slot}_RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(line)
            resp[(r['call_key'], slot)] = r

    def top_model(n):
        types = [1.0 if n['node_type'] == t else 0.0
                 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
        x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
        u = x @ devs['NodeRouter_coef'].T + devs['NodeRouter_intercept'] - \
            ALPHA_C * devs['mean_C'] - ALPHA_L * devs['mean_L']
        return int(np.argmax(u))

    # cross-model agreement signal (per task): any other model's stored expr
    # evaluates to the same value as the router model's on gold facts
    xagree = {}
    for uid, r in rows.items():
        node = rs[uid]
        vals = {}
        for slot in POOL:
            try:
                e = decode(resp[(f'{uid}:rs', slot)]['answer'])['expression']
                vals[slot] = exec_calc(e, node['gold_facts'])
            except Exception:
                vals[slot] = None
        mine = vals.get(r['model'])
        xagree[uid] = any(vals[s] is not None and mine is not None and close(vals[s], mine)
                          for s in POOL if s != r['model'])

    # adjudicate every task
    per = []
    for uid, r in rows.items():
        c = ct.get(uid)
        node = rs[uid]
        T = None
        mtype = None
        contract_correct = None
        if c and c['contract'] and c.get('contract_exec'):
            T = c['equiv_stored']
            vexpr = to_vref(c['contract']['canonical_expression'])
            if T is False:
                mtype = mismatch_type(vexpr, r['expr'], node['gold_facts'])
            contract_correct = close(c.get('contract_value'), tasks[uid]['answer'])
        A_ok = close(p02[uid]['A0'], p02[uid]['target'])
        B_ok = close(p02[uid]['B'], p02[uid]['target'])
        per.append(dict(
            uid=uid, dev=uid in dev, stored_correct=r['round1_correct'],
            A=A_ok, B=B_ok,
            cB_tok=p02[uid]['cB_tok'], cB_lat=p02[uid]['cB_lat'],
            v_tokens=c['tokens'] if c else 0.0,
            T_contract=T, contract_correct=contract_correct, mismatch=mtype,
            oracle_equiv=oracle_equiv.get(uid),
            flag_lexical=bool(r['flagged']), xagree=xagree[uid]))
    clean = [p for p in per if not p['dev']]

    def gate_row(sig, subset):
        """sig: fn(p)->bool 'intervene'; on stored-correct subset."""
        sc = [p for p in subset if p['stored_correct']]
        harm = [p for p in sc if not p['A']]
        safe = [p for p in sc if p['A']]
        caught = sum(bool(sig(p)) for p in harm)
        retained = sum(not bool(sig(p)) for p in safe)
        return dict(harm_caught=f'{caught}/{len(harm)}',
                    safe_retained=f'{retained}/{len(safe)}',
                    false_interventions=len(safe) - retained)

    primary = {name: gate_row(sig, clean) for name, sig in [
        ('lexical_checks', lambda p: p['flag_lexical']),
        ('cross_model_agreement', lambda p: not p['xagree']),
        ('semantic_contract', lambda p: p['T_contract'] is not True),
        ('oracle_equiv_gold', lambda p: p['oracle_equiv'] is not True)]}

    # R_regen enrichment on stored-wrong stratum
    sw = [p for p in clean if not p['stored_correct']]
    rec = [p for p in sw if p['B']]
    stay = [p for p in sw if not p['B']]
    enrichment = dict(
        n_stored_wrong=len(sw),
        regen_recover=len(rec),
        contract_correct_among_recover=f'{sum(bool(p["contract_correct"]) for p in rec)}/{len(rec)}',
        contract_correct_among_stay_wrong=f'{sum(bool(p["contract_correct"]) for p in stay)}/{len(stay)}',
        mismatch_types_recover=sorted({str(p['mismatch']) for p in rec}),
        mismatch_types_stay=sorted({str(p['mismatch']) for p in stay}),
        note='contract_correct = contract value matches gold answer (offline label)')

    # pure regen-harm protection
    sc = [p for p in clean if p['stored_correct']]
    harmB = [p for p in sc if not p['B']]
    protection = dict(
        n_regen_harm=len(harmB),
        contract_T_among_harm=f'{sum(p["T_contract"] is True for p in harmB)}/{len(harmB)}',
        note='T=True means the contract endorses the stored expression -> policy keeps reuse, avoiding the harm')

    # policy replay on clean test
    def replay(sig):
        q, cost, lat = [], [], []
        for p in clean:
            act_B = bool(sig(p))
            q.append(float(p['B']) if act_B else float(p['A']))
            cost.append((p['cB_tok'] if act_B else 0.0) + p['v_tokens'])
            lat.append((p['cB_lat'] if act_B else 0.0))
        return dict(Q=float(np.mean(q)), C=float(np.mean(cost)), L=float(np.mean(lat)))

    base = dict(
        always_reuse=dict(Q=float(np.mean([float(p['A']) for p in clean])), C=0.0, L=0.0),
        always_regen=dict(Q=float(np.mean([float(p['B']) for p in clean])),
                          C=float(np.mean([p['cB_tok'] + p['v_tokens'] for p in clean])),
                          L=float(np.mean([p['cB_lat'] for p in clean]))))
    vt = float(np.mean([p['v_tokens'] for p in clean]))
    policies = dict(
        contract_gate=replay(lambda p: p['T_contract'] is not True),
        oracle_semantic_gate=replay(lambda p: p['oracle_equiv'] is not True),
        lexical_gate=replay(lambda p: p['flag_lexical']),
        agreement_gate=replay(lambda p: not p['xagree']))
    amortized = {n: dict(Q=policies['contract_gate']['Q'],
                         C_n=float(np.mean([p['cB_tok'] for p in clean if p['T_contract'] is not True])) * 0
                         + vt / n + float(np.mean([(p['cB_tok'] if p['T_contract'] is not True else 0.0)
                                                   for p in clean])))
                 for n in (1, 2, 5, 10)}

    out = dict(n_clean=len(clean), n_dev_excluded=len(per) - len(clean),
               stored_correct_clean=sum(p['stored_correct'] for p in clean),
               contract_exec_clean=sum(p['T_contract'] is not None for p in clean),
               primary_endpoint=primary, r_regen_enrichment=enrichment,
               regen_harm_protection=protection,
               baselines=base, policies=policies,
               contract_verifier_tokens_mean=vt,
               amortized_cost_C_n=amortized,
               per_task=per)
    (OUT / 'RESULTS.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(dict(primary=primary, enrichment=enrichment, protection=protection,
                          policies={k: {m: round(v, 4) for m, v in p.items()}
                                    for k, p in policies.items()},
                          base={k: {m: round(v, 4) for m, v in p.items()} for k, p in base.items()},
                          verifier_tokens=round(vt, 1)), indent=1))


if __name__ == '__main__':
    run()
