"""H1 ONLINE v7 — small-scale real trial (operator pre-scoped round 2:
S1/S2/S3 x 2 repeats, ~100 calls; GLM-Flash subscription, ¥0 marginal).

v7 rule (input-derived gating; archive-validated):
  detection  := structural parse/degeneracy failure of any node output
  coverage   := fraction of INPUT-DOCUMENT probes (ALL doc amounts + ALL
               dates, normalized multi-form matching) present in the
               already-paid D0 sink text — the scheduler self-assesses
               against the INPUT document; never reads scoring keys,
               reference labels, or future results
  action     := repair targeted closure iff detection AND coverage < 0.318
               (theta fit on the ydt archive where it separated its runs;
               the trial doc 舜天 is genuinely out-of-sample for theta)

Archive gate record (zero-call, honest): held-out Shuntian 4/5 correct
(1 correct skip of the -0.064 run, 3 correct repairs); fit-doc ydt shows
NO separation (its single NEG run cov equals POS runs); combined 6/10.
Gate passed at the pre-registered minimum, not convincingly.

Policies per (scenario, repeat) — all fork from the SAME paid shared run:
  P_ACCEPT / P_TARGETED / P_FULL / ONLINE_v7
  SIMPLE_COND (repair minimal closure iff contract-detection, else accept)
  is INSTANTIATED BY P_TARGETED: under this fault model detection fires
  iff a fault was injected, making the two rules deterministically
  identical given the same shared state (documented in the freeze; no
  duplicate calls burned for a provably-identical arm).

Criteria (pre-registered, descriptive n=2/scenario):
  C1 ONLINE_v7 mean eU (all scenario-repeats) >= max fixed-policy mean
  C2 per-scenario t_q >= best-fixed - 0.05
  C3 S3: ONLINE_v7 repairs 0/2
  C5 decision-correctness (descriptive): alignment of ONLINE choices with
     ex-post optimal action per scenario-repeat
  online_value_supported := C1 AND C2 AND C3. Negatives preserved.

Caps: 120 calls / 3600s wall. Gate: H1V7_GO=1 + --freeze-sha256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

from deadline_reward_v1.r2fix_runner import (
    HeteroDAG, ROLE, ORDER, ROOT_NODE, GARBAGE, downstream, utility,
    eval_by_category, call_ds, load_env_creds, OUT_CAP)
from deadline_reward_v1.h1_online_runner import (
    parse_ok, closure_for)
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.full_dag_silver import doc_atoms

HERE = ROOT / 'deadline_reward_v1'
FREEZE = HERE / 'H1ONLINE_FREEZE_V7.json'
DOC_SLOT = '舜天#st_announce_2024_020'
SCENARIOS = {'S1': 'b0', 'S2': 'b2', 'S3': None}
REPEATS = 2
THETA = 0.318
CAP_CALLS, CAP_WALL_S = 120, 3600.0
D = 350.0
POLICIES = ('P_ACCEPT', 'P_TARGETED', 'P_FULL', 'ONLINE_V7')


def probe_forms(p):
    m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', p)
    if m:
        y, mo, dd = m.groups()
        return [p, f'{y}-{int(mo):02d}-{int(dd):02d}',
                f'{y}{int(mo):02d}{int(dd):02d}']
    m2 = re.match(r'(\d{4})[-.](\d{1,2})[-.](\d{1,2})', p)
    if m2:
        y, mo, dd = m2.groups()
        return [p, f'{y}年{int(mo)}月{int(dd)}日']
    return [p]


def coverage(probes, sink_text):
    clean = re.sub(r'[\s,，]', '', str(sink_text or ''))
    hit = 0
    for p in probes:
        if any(re.sub(r'[\s,，]', '', f) in clean
               for f in probe_forms(p)):
            hit += 1
    return hit / max(1, len(probes))


def build_freeze():
    ev_sha = hashlib.sha256(
        (HERE / 'terminal_eval.py').read_bytes()).hexdigest()
    return dict(
        version='H1ONLINE_FREEZE_V7',
        supersedes='H1ONLINE_FREEZE_v6 (preserved unchanged)',
        doc_slot=DOC_SLOT,
        theta=THETA,
        theta_provenance='fit on v4/ydt archive (0.318 between POS '
                         '0.333 and NEG/POS 0.303); trial doc Shuntian '
                         'is out-of-sample for theta',
        archive_gate_record='held-out Shuntian 4/5 correct (1 skip + 3 '
                            'repairs); fit-doc ydt NO separation; '
                            'combined 6/10 — passed at pre-registered '
                            'minimum, honestly weak',
        scenarios=dict(S1='b0 fault', S2='b2 fault', S3='no fault'),
        policies=dict(
            P_ACCEPT='never repair', P_TARGETED='closure repair on '
            'detection', P_FULL='all-7 rerun on detection',
            ONLINE_V7='repair iff detection AND input-probe coverage of '
                      'the paid D0 sink < theta',
            SIMPLE_COND='INSTANTIATED BY P_TARGETED — deterministic '
                        'equivalence under this fault model (detection '
                        'fires iff fault injected); no duplicate calls'),
        repeats=REPEATS, D_s=D, utility_C0_tokens=60000,
        model='GLM-5.3-Flash subscription, ¥0 marginal',
        out_caps=OUT_CAP,
        caps=dict(calls=CAP_CALLS, wall_s=CAP_WALL_S),
        fail_policy='per-run fail-stop; >2 INCOMPLETE -> batch stop',
        evaluator_sha256=ev_sha,
        criteria=dict(
            C1='ONLINE_V7 mean eU >= max(P_ACCEPT,P_TARGETED,P_FULL)',
            C2='per-scenario t_q >= best-fixed - 0.05',
            C3='S3: ONLINE repairs 0/2',
            C5='decision-correctness reported descriptively',
            online_value_supported='C1 AND C2 AND C3'),
        boundary='exploratory n=2/scenario, single doc, single model; '
                 'no deadline axis (fault-position-conditional only); '
                 'not full (Z,R,pi)')


def gates(args):
    if os.environ.get('H1V7_GO') != '1':
        raise PermissionError('requires H1V7_GO=1')
    dirty = subprocess.run(
        ['git', '-C', str(ROOT), 'status', '--porcelain', '--',
         'deadline_reward_v1'], capture_output=True, text=True).stdout
    if dirty.strip():
        raise PermissionError(f'uncommitted changes:\n{dirty}')
    raw = FREEZE.read_bytes()
    if args.freeze_sha256 != hashlib.sha256(raw).hexdigest():
        raise PermissionError('freeze hash mismatch')
    f = json.loads(raw)
    if f['version'] != 'H1ONLINE_FREEZE_V7':
        raise PermissionError('freeze version mismatch')
    ev = hashlib.sha256(
        (HERE / 'terminal_eval.py').read_bytes()).hexdigest()
    if f['evaluator_sha256'] != ev:
        raise PermissionError('evaluator drift')
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write-freeze', action='store_true')
    ap.add_argument('--freeze-sha256')
    ap.add_argument('--out')
    args = ap.parse_args()
    if args.write_freeze:
        FREEZE.write_text(json.dumps(build_freeze(),
                                     ensure_ascii=False, indent=1))
        print('freeze written:', FREEZE)
        print('sha256:', hashlib.sha256(FREEZE.read_bytes()).hexdigest())
        return 0
    freeze = gates(args)
    if not args.out:
        raise SystemExit('need --out')
    creds = load_env_creds()
    doc = load_docs()[DOC_SLOT]
    at = doc_atoms(doc['text'])
    probes = list(at['amounts']) + list(at['dates'])
    keys = ([f'd:{k}' for k in at['dates'][:4]]
            + [f'a:{k}' for k in at['amounts'][:3]]
            + [f'p:{k}' for k in at['penalties'][:3]]
            + [f'e:{k}' for k in at['entities'][:3]])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    ledger = open(out / 'LEDGER.jsonl', 'w')
    t0 = time.monotonic()
    calls = 0
    results = []
    from copy import deepcopy
    full_set = set(ORDER) - {ROOT_NODE}

    def call_checked(dag, node, replace_garbage=False):
        nonlocal calls
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
        ledger.write(json.dumps(
            dict(call=calls, node=node, role=ROLE[node],
                 in_tok=o['tokens_in'], out_tok=o['tokens_out'],
                 lat=o['latency_s'], garbage=replace_garbage),
            ensure_ascii=False) + '\n')
        ledger.flush()
        return o

    try:
        for sid, fault in SCENARIOS.items():
            closure = closure_for(fault)
            for rep in range(1, REPEATS + 1):
                rid = f'{sid}_r{rep}'
                chain = HeteroDAG(doc['text'], doc['doc_id'])
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
                online_repair = bool(detection and cov < THETA)
                print(f'[{rid}] fault={fault} det={detection} '
                      f'cov={cov:.3f} theta={THETA} '
                      f'ONLINE->{"REPAIR" if online_repair else "ACCEPT"}',
                      flush=True)
                for pol in POLICIES:
                    ac = HeteroDAG(doc['text'], doc['doc_id'])
                    ac.outputs = deepcopy(shared)
                    r_clk, r_tok = sh_clk, sh_tok
                    if pol == 'P_TARGETED' and detection:
                        rc = closure
                    elif pol == 'P_FULL' and detection:
                        rc = full_set
                    elif pol == 'ONLINE_V7' and online_repair:
                        rc = closure
                    else:
                        rc = set()
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
                    results.append(dict(
                        rid=f'{rid}|{pol}', scenario=sid, rep=rep,
                        policy=pol, detection=detection, coverage=cov,
                        online_action='REPAIR' if online_repair
                                      else 'ACCEPT',
                        t_q=full['terminal_q'],
                        hits=full['terminal_hits'], n_ref=full['n_ref'],
                        tokens=int(r_tok), latency=round(r_clk, 1),
                        met=r_clk <= D, eU=round(eu, 4),
                        extra_calls=len(rc)))
                    print(f'  {pol:>10}: t_q={full["terminal_q"]:.3f} '
                          f'eU={eu:+.4f} extra={len(rc)}', flush=True)
        import statistics as st
        agg = {}
        for sid in SCENARIOS:
            for pol in POLICIES:
                rs = [e for e in results
                      if e['scenario'] == sid and e['policy'] == pol]
                agg[f'{sid}|{pol}'] = dict(
                    n=len(rs), t_q_mean=st.mean([e['t_q'] for e in rs]),
                    eU_mean=st.mean([e['eU'] for e in rs]))
        on_all = st.mean([e['eU'] for e in results
                          if e['policy'] == 'ONLINE_V7'])
        fixed_best = max(
            st.mean([e['eU'] for e in results if e['policy'] == p])
            for p in ('P_ACCEPT', 'P_TARGETED', 'P_FULL'))
        c1 = on_all >= fixed_best
        c2 = all(agg[f'{s}|ONLINE_V7']['t_q_mean']
                 >= max(agg[f'{s}|{p}']['t_q_mean'] for p in
                        ('P_ACCEPT', 'P_TARGETED', 'P_FULL')) - 0.05
                 for s in SCENARIOS)
        c3 = all(not e['online_action'] == 'REPAIR' for e in results
                 if e['scenario'] == 'S3' and e['policy'] == 'ONLINE_V7')
        # C5: ex-post optimal per scenario-repeat + alignment
        align = tot = 0
        for sid in SCENARIOS:
            for rep in range(1, REPEATS + 1):
                arms = {e['policy']: e for e in results
                        if e['scenario'] == sid and e['rep'] == rep}
                if len(arms) < len(POLICIES):
                    continue
                best = max(arms, key=lambda p: arms[p]['eU'])
                if best in ('P_ACCEPT', 'P_TARGETED'):
                    optimal_action = ('ACCEPT' if best == 'P_ACCEPT'
                                      else 'REPAIR')
                    tot += 1
                    align += int(arms['ONLINE_V7']['online_action']
                                 == optimal_action)
        verdicts = dict(C1=on_all >= fixed_best, C2_quality=c2,
                        C3_control=c3, online_eU_mean=on_all,
                        fixed_best_eU_mean=fixed_best,
                        C5_alignment=f'{align}/{tot}',
                        online_value_supported=bool(c1 and c2 and c3))
        (out / 'H1V7_RESULTS.json').write_text(json.dumps(
            dict(status='COMPLETE', results=results, aggregate=agg,
                 verdicts=verdicts, calls=calls, cash_cny=0.0,
                 wall_s=round(time.monotonic() - t0, 1)),
            ensure_ascii=False, indent=1))
        print(json.dumps(verdicts, ensure_ascii=False, indent=1))
        print(f'calls={calls} wall={time.monotonic()-t0:.0f}s ¥0')
    except BaseException as exc:
        (out / 'H1V7_INCOMPLETE.json').write_text(json.dumps(
            dict(reason=repr(exc), results=results, calls=calls,
                 traceback=traceback.format_exc()),
            ensure_ascii=False, indent=1, default=str))
        print(f'INCOMPLETE: {exc}')


if __name__ == '__main__':
    main()
