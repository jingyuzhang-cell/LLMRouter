"""H1V8 — independent-task gating validation (operator conditional-GO
2026-10-27: 150 request attempts / ¥0.10 hard cash cap / batch admission).

Question: does input-probe coverage gating (cov) add decision value
BEYOND a fault-location rule (FLR), on an event that never participated
in any tuning (zeda, fetched 2026-10-27, zero API calls)?

Policies (frozen BEFORE any test call):
  P_ACCEPT   never repair                         [real arm, 0 calls]
  P_TARGETED repair closure on detection          [real arm]
  FLR        repair iff fault in timeline chain {b0,x0} else accept.
             Role-semantic generalization of the v7 archive rule
             (b0->repair, b2->accept). INSTANTIATED: =P_TARGETED on
             b0/x0 scenarios, =P_ACCEPT elsewhere (deterministic,
             documented; no duplicate calls — same pattern as v7's
             SIMPLE_COND). Alternative reading ({b0,x0,b1,x1} all
             repair-worthy) reported alongside.
  ONLINE_V8  repair iff detection AND cov < 0.318  [real arm; theta
             FROZEN from v7, no refit]
  P_STRUCT   repair iff detection AND degrade_signal(sink)  [real arm;
             observable = pre-existing v6 code path, never refit]

Divergence structure (expected, test decides):
  fault  FLR   ONLINE  P_STRUCT
  b0     rep   rep?    rep      (doc-axis: cov>=theta would diverge)
  x0     rep   acc?    rep      <- FLR/ONLINE split
  b1     acc   rep?    rep      <- FLR/ONLINE split (other direction)
  b2     acc   acc?    acc
  none   acc   acc     acc      (control: ONLINE must not repair)

Scenario matrix (9 shared real runs, 8 calls each):
  Z=beda main penalty decision (7,967c, probes 8d+40a, share 0.83)
  I=intermediary decision (9,237c, 5d+32a, only 2/5 dates in root win)
  Z-b0 x2, Z-x0 x2, Z-b1 x2, Z-b2 x1, Z-none x1, I-b0 x1
Worst-case calls: 9*8 shared + 59 repair = 131 <= 150.
Cash: GLM-5.3-Flash subscription, exactly ¥0.00/call -> ¥0 <= ¥0.10.
Model/utility/eval identical to v7 (D=350, C0=60000, OUT_CAP 3072).
Fail-stop on any anomaly; no auto-retry. Full pool AND divergent
subsets reported separately; n=2/scenario descriptive, event=n_cluster 1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from copy import deepcopy
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

from deadline_reward_v1.r2fix_runner import (
    HeteroDAG, ROLE, ORDER, ROOT_NODE, GARBAGE, utility,
    eval_by_category, call_ds, load_env_creds, OUT_CAP)
from deadline_reward_v1.h1_online_runner import parse_ok, closure_for
from deadline_reward_v1.h1_online_v7_runner import probe_forms, coverage
from deadline_reward_v1.full_dag_silver import doc_atoms

HERE = ROOT / 'deadline_reward_v1'
DOCS = json.loads((HERE / 'h1v8_docs' / 'zeda_docs.json').read_text())
FREEZE = HERE / 'H1V8_FREEZE.json'
PRECHECK = HERE / 'h1v8_docs' / 'PRECHECK.json'
THETA = 0.318
CAP_CALLS, CAP_WALL_S, CAP_CASH = 150, 5400.0, 0.10
D_S, C0 = 350.0, 60000.0
SCEN = [('Z', 'b0', 2), ('Z', 'x0', 2), ('Z', 'b1', 2),
        ('Z', 'b2', 1), ('Z', None, 1), ('I', 'b0', 1)]
REAL_POLICIES = ('P_ACCEPT', 'P_TARGETED', 'ONLINE_V8', 'P_STRUCT')
FLR_REPAIR_NODES = {'b0', 'x0'}  # timeline chain


def degrade_signal(sink_text):
    import json as _j
    t = (sink_text or '').strip()
    if t.startswith('```'):
        parts = t.split('\n', 1)
        t = parts[1].rsplit('```', 1)[0].strip() if len(parts) == 2 else t
    try:
        obj = _j.loads(t)
    except Exception:
        return True
    arr = obj if isinstance(obj, list) else (
        obj.get('items') if isinstance(obj, dict) else [])
    if not isinstance(arr, list) or not arr:
        return True
    for it in arr:
        if not isinstance(it, dict):
            continue
        for f in ('key_dates', 'amounts', 'penalties', 'entities'):
            v = it.get(f)
            if isinstance(v, list) and not v:
                return True
    return False


def scenario_worst(fault):
    cl = len(closure_for(fault)) if fault else 0
    return 8 + 3 * cl  # shared + P_TARGETED + ONLINE + P_STRUCT all repair


def gates(args):
    if os.environ.get('H1V8_GO') != '1':
        raise PermissionError('requires H1V8_GO=1 (operator conditional-GO)')
    raw = FREEZE.read_bytes()
    if args.freeze_sha256 != hashlib.sha256(raw).hexdigest():
        raise PermissionError('freeze hash mismatch')
    f = json.loads(raw)
    ev = hashlib.sha256(
        (HERE / 'terminal_eval.py').read_bytes()).hexdigest()
    if f.get('evaluator_sha256') != ev:
        raise PermissionError('evaluator drift')
    real_docs = hashlib.sha256(
        (HERE / 'h1v8_docs' / 'zeda_docs.json').read_bytes()).hexdigest()
    if f.get('docs_sha256') != real_docs:
        raise PermissionError('docs drift')
    pc = json.loads(PRECHECK.read_text())
    if not pc.get('all_pass'):
        raise PermissionError('zero-call precheck not all-pass')
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--freeze-sha256', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    gates(args)
    creds = load_env_creds()
    texts = {d['doc_id']: d for d in DOCS['docs']}
    docslot = {'Z': 'zeda_csrc_penalty_2023_29',
               'I': 'zeda_csrc_penalty_2024_kangda'}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    ledger = open(out / 'LEDGER.jsonl', 'w')
    t0 = time.monotonic()
    calls = 0
    cash = 0.0
    results = []

    def call_checked(dag, node, replace_garbage=False):
        nonlocal calls, cash
        if calls >= CAP_CALLS:
            raise RuntimeError('calls cap')
        if time.monotonic() - t0 > CAP_WALL_S:
            raise RuntimeError('wall cap')
        prompt = dag.build_prompt(node)
        o = call_ds(prompt, creds, max_out_tokens=OUT_CAP[ROLE[node]])
        if replace_garbage:
            o = dict(o, answer=GARBAGE, finish_reason='stop')
        dag.outputs[node] = o
        calls += 1
        cash += float(o.get('cash_cny', 0.0) or 0.0)
        if cash > CAP_CASH:
            raise RuntimeError(f'cash cap exceeded: {cash}')
        ledger.write(json.dumps(
            dict(call=calls, node=node, role=ROLE[node],
                 in_tok=o['tokens_in'], out_tok=o['tokens_out'],
                 lat=o['latency_s'], garbage=replace_garbage),
            ensure_ascii=False) + '\n')
        ledger.flush()
        return o

    try:
        for si, (slot, fault, reps) in enumerate(SCEN):
            remaining_worst = sum(
                scenario_worst(f2) * r2
                for _, f2, r2 in SCEN[si:])
            if calls + remaining_worst > CAP_CALLS:
                raise RuntimeError(
                    f'batch admission fail at {slot}-{fault}: '
                    f'{calls}+{remaining_worst}>{CAP_CALLS}')
            dd = texts[docslot[slot]]
            at = doc_atoms(dd['text'])
            probes = list(at['amounts']) + list(at['dates'])
            keys = ([f'd:{k}' for k in at['dates'][:4]]
                    + [f'a:{k}' for k in at['amounts'][:3]]
                    + [f'p:{k}' for k in at['penalties'][:3]]
                    + [f'e:{k}' for k in at['entities'][:3]])
            for rep in range(1, reps + 1):
                rid = f'{slot}-{fault or "none"}_r{rep}'
                chain = HeteroDAG(dd['text'], dd['doc_id'])
                clk = tok = 0.0
                for node in chain.order:
                    o = call_checked(chain, node,
                                     replace_garbage=(node == fault))
                    clk += o['latency_s']
                    tok += o['tokens_in'] + o['tokens_out']
                shared = deepcopy(chain.outputs)
                sh_clk, sh_tok = clk, tok
                (out / f'{rid}_shared.json').write_text(json.dumps(
                    {n: dict(answer=v['answer'][:3000])
                     for n, v in shared.items()},
                    ensure_ascii=False, indent=1))
                detection = any(not parse_ok(shared[n]['answer'])
                                for n in ORDER)
                cov = coverage(probes, shared['sink']['answer'])
                dsig = degrade_signal(shared['sink']['answer'])
                acts = dict(
                    P_ACCEPT=False,
                    P_TARGETED=bool(detection),
                    ONLINE_V8=bool(detection and cov < THETA),
                    P_STRUCT=bool(detection and dsig))
                flr_repair = fault in FLR_REPAIR_NODES
                print(f'[{rid}] fault={fault} det={detection} '
                      f'cov={cov:.3f} dsig={dsig} acts={acts} '
                      f'FLR->{"REP" if flr_repair else "ACC"}', flush=True)
                for pol in REAL_POLICIES:
                    ac = HeteroDAG(dd['text'], dd['doc_id'])
                    ac.outputs = deepcopy(shared)
                    r_clk, r_tok = sh_clk, sh_tok
                    rc = closure_for(fault) if acts[pol] else set()
                    for rn in sorted(n for n in rc if n == fault):
                        o = call_checked(ac, rn)
                        r_clk += o['latency_s']
                        r_tok += o['tokens_in'] + o['tokens_out']
                    for dn in ORDER:
                        if dn in rc and dn != fault:
                            o = call_checked(ac, dn)
                            r_clk += o['latency_s']
                            r_tok += o['tokens_in'] + o['tokens_out']
                    full, by_cat = eval_by_category(ac.outputs, keys)
                    eu = utility(full['terminal_q'], r_tok, r_clk)
                    row = dict(
                        rid=f'{rid}|{pol}', slot=slot, fault=fault,
                        rep=rep, policy=pol, detection=detection,
                        coverage=round(cov, 4), degrade=dsig,
                        action='REPAIR' if acts[pol] else 'ACCEPT',
                        t_q=full['terminal_q'],
                        hits=full['terminal_hits'], n_ref=full['n_ref'],
                        tokens=int(r_tok), latency=round(r_clk, 1),
                        met=r_clk <= D_S, eU=round(eu, 4),
                        extra_calls=len(rc))
                    results.append(row)
                    if pol in ('P_ACCEPT', 'P_TARGETED') and \
                            acts[pol] == flr_repair:
                        results.append(dict(
                            deepcopy(row), policy='FLR',
                            action='REPAIR' if flr_repair else 'ACCEPT',
                            note=f'instantiated by {pol}'))
                    print(f'  {pol:>10}: t_q={full["terminal_q"]:.3f} '
                          f'eU={eu:+.4f} extra={len(rc)}', flush=True)
        verdicts = summarize(results)
        (out / 'H1V8_RESULTS.json').write_text(json.dumps(
            dict(status='COMPLETE', results=results, verdicts=verdicts,
                 calls=calls, cash_cny=cash,
                 wall_s=round(time.monotonic() - t0, 1)),
            ensure_ascii=False, indent=1))
        print(json.dumps(verdicts, ensure_ascii=False, indent=1))
        print(f'calls={calls} cash={cash} wall={time.monotonic()-t0:.0f}s')
    except BaseException as exc:
        (out / 'H1V8_INCOMPLETE.json').write_text(json.dumps(
            dict(reason=repr(exc), results=results, calls=calls,
                 traceback=traceback.format_exc()),
            ensure_ascii=False, indent=1, default=str))
        print(f'INCOMPLETE: {exc}')


def summarize(results):
    import statistics as st
    policies = ['P_ACCEPT', 'P_TARGETED', 'FLR', 'ONLINE_V8', 'P_STRUCT']
    means = {}
    for p in policies:
        rs = [e['eU'] for e in results if e['policy'] == p]
        means[p] = round(st.mean(rs), 4) if rs else None
    # per scenario-rep ex-post optimal action (by eU over accept-vs-repair
    # arms actually executed)
    per_sr = {}
    for e in results:
        per_sr.setdefault(e['rid'].split('|')[0], {})[e['policy']] = e
    divergent, agree, opt_align = [], [], {p: [0, 0] for p in policies}
    for sr, arms in per_sr.items():
        if 'P_ACCEPT' not in arms or 'P_TARGETED' not in arms:
            continue
        best = max((arms['P_ACCEPT']['eU'], 'ACCEPT'),
                   (arms['P_TARGETED']['eU'], 'REPAIR'))
        for p in policies:
            if p in arms:
                opt_align[p][1] += 1
                opt_align[p][0] += int(arms[p]['action'] == best[1])
        on, fl = arms.get('ONLINE_V8'), arms.get('FLR')
        if on and fl:
            rec = dict(sr=sr, fault=on['fault'], cov=on['coverage'],
                       online=on['action'], flr=fl['action'],
                       online_eU=on['eU'], flr_eU=fl['eU'],
                       diff=round(on['eU'] - fl['eU'], 4))
            (divergent if on['action'] != fl['action']
             else agree).append(rec)
    control = [e for e in results
               if e['fault'] is None and e['policy'] == 'ONLINE_V8']
    same_pos = {}
    for e in results:
        if e['policy'] == 'ONLINE_V8':
            same_pos.setdefault(e['fault'], []).append(
                (e['slot'], e['coverage'], e['action']))
    v1 = (sum(1 for d in divergent if d['diff'] >= 0),
          len(divergent)) if divergent else (0, 0)
    return dict(
        eU_means=means,
        V1_online_not_worse_than_FLR_on_divergent=f'{v1[0]}/{v1[1]}',
        V2_online_mean_ge_all=f'{means["ONLINE_V8"]} vs max '
                              f'{max(m for m in means.values() if m is not None)}',
        V2_pass=bool(means['ONLINE_V8'] >= max(
            m for m in means.values() if m is not None)),
        V3_control_zero_repair=all(c['action'] == 'ACCEPT'
                                   for c in control),
        action_alignment={p: f'{a}/{t}' for p, (a, t)
                          in opt_align.items()},
        divergent_subsets=divergent, agree_subsets=agree,
        same_position_action_report={
            f'fault={k}': v for k, v in same_pos.items()})


if __name__ == '__main__':
    main()
