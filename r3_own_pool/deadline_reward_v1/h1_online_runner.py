"""H1 online-scheduler scenario-diversity experiment (design frozen v6).

Question: does an ONLINE (Z,R) repair decision rule — driven ONLY by
task-internal observables (never the scoring keys) — beat every fixed
policy (always-accept / always-targeted-repair / always-full-rerun)
across a scenario matrix where the optimal action VARIES?

Scenario matrix (3 scenarios, shared run per (scenario, repeat),
all four policies branch from the SAME shared state — paired):
  S1  fault b0 (timeline branch head, 2-hop) — v4/v5 evidence: repair pays
  S2  fault b2 (penalties branch, 1-hop)     — empirically open: if the
      sink routes around it, accept may be optimal
  S3  no fault (control) — nothing fires; all policies must act identically
      (no spurious repairs)

Policies (from the shared state, given the detection result):
  P_ACCEPT    never repair (0 extra calls)
  P_TARGETED  repair = closure(fault_node) on any detection
  P_FULL      re-execute all non-root nodes on any detection
  ONLINE      pre-registered rule (below) — accept or targeted

ONLINE rule (frozen; observables whitelist ONLY):
  detection   := any node output fails its parse/degeneracy check
                 (unparseable JSON, empty array, or len < 40 chars)
  degrade_sig := the sink output (from the shared run) has any EMPTY
                 category field (key_dates/amounts/penalties/entities)
                 or an explicit missing-info marker (缺失)
  action      := if detection AND degrade_sig -> targeted closure repair
                 else -> accept
  The rule never reads valid_keys/reference data — verified by review R-OBS.

Repeats: 5 per scenario. Calls per (S,rep): S1/S2 = 8 shared + 0 (accept)
  + |closure| (targeted) + 7 (full) + |closure| (online, if it fires)
  = 8+3+7+3 = 21; S3 = 8. Planned total = 5*(21+21+8) = 250 calls,
  cap 300; wall cap 5400s; GLM-5.3-Flash subscription (marginal ¥0,
  tokens/latency recorded).

Criteria (pre-registered, descriptive n=5/scenario):
  C1  ONLINE mean eU >= max(fixed policies' mean eU) OVER ALL scenarios
  C2  ONLINE quality per scenario non-inferior to the best fixed policy
      in that scenario (mean t_q within -0.05)
  C3  S3 control: ONLINE makes 0 repairs in all repeats
  C4  honesty metric: in scenarios/repeats where P_ACCEPT beat
      P_TARGETED, did ONLINE side with accept? (rule-alignment rate)
  Verdict 'online_value_supported' iff C1 AND C2 AND C3.
  Negative verdicts preserved as-is.

Gate: H1ON_GO=1 + --freeze-sha256 + clean tree + evaluator sha bound.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

from deadline_reward_v1.r2fix_runner import (
    HeteroDAG, ROLE, ORDER, ROOT_NODE, FAULT as V3_FAULT, GARBAGE,
    closures as v3_closures, downstream, utility, eval_by_category,
    call_ds, load_env_creds, BILLING, OUT_CAP, DOC_SLOT as V5_SLOT,
    PLANNED_CALLS as _V3_PLANNED, CAP_CNY as _V3_CAP, WALL_S as _V3_WALL)
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.terminal_eval import eval_terminal

HERE = ROOT / 'deadline_reward_v1'
FREEZE = HERE / 'H1ONLINE_FREEZE.json'

SCENARIOS = {
    'S1': dict(fault='b0', label='timeline-branch fault (repair expected to pay)'),
    'S2': dict(fault='b2', label='penalties-branch fault (empirically open)'),
    'S3': dict(fault=None, label='no fault (control)'),
}
POLICIES = ('P_ACCEPT', 'P_TARGETED', 'P_FULL', 'ONLINE')
REPEATS = 5
CAP_CALLS, CAP_WALL_S = 300, 5400.0
D = 350.0
DEGENERATE_LEN = 40


def closure_for(fault):
    if fault is None:
        return set()
    return {fault} | downstream(fault)


def parse_ok(text):
    """Structural detection only — no scoring keys."""
    import re as _re
    t = (text or '').strip()
    if t.startswith('```'):
        parts = t.split('\n', 1)
        t = parts[1].rsplit('```', 1)[0].strip() if len(parts) == 2 else t
    try:
        obj = json.loads(t)
    except Exception:
        return False
    arr = obj if isinstance(obj, list) else (
        obj.get('items') if isinstance(obj, dict) else None)
    return isinstance(arr, list) and len(arr) > 0 and len(t) >= DEGENERATE_LEN


def degrade_signal(sink_text):
    """Sink's own category-field emptiness / missing markers — the
    synthesis contract makes the sink report honestly; this observable
    never touches valid_keys."""
    t = (sink_text or '').strip()
    if t.startswith('```'):
        parts = t.split('\n', 1)
        t = parts[1].rsplit('```', 1)[0].strip() if len(parts) == 2 else t
    try:
        obj = json.loads(t)
    except Exception:
        return True  # unparseable sink = degraded
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
            if isinstance(v, str) and ('缺失' in v or not v.strip()):
                return True
    if '缺失' in t:
        return True
    return False


def build_freeze():
    docs = load_docs()
    ev_sha = hashlib.sha256(
        (HERE / 'terminal_eval.py').read_bytes()).hexdigest()
    return dict(
        version='H1ONLINE_FREEZE_v6',
        doc_slots=[V5_SLOT, 'ydt#D3_E03-yuandao_2026-08-29'],
        doc_note='S1/S2/S3 run on BOTH docs? NO — round 1: primary doc '
                 f'{V5_SLOT} (舜天); ydt reserved for cross-doc round 2',
        scenarios={k: dict(fault=v['fault'], label=v['label'])
                   for k, v in SCENARIOS.items()},
        policies=dict(
            P_ACCEPT='never repair',
            P_TARGETED=f'repair closure(fault) on any detection',
            P_FULL='re-execute all 7 non-root nodes on any detection',
            ONLINE='if detection AND degrade_signal -> targeted closure '
                   'repair, else accept; observables whitelist = '
                   'structural parse/degeneracy of node outputs + sink '
                   'category-field emptiness/缺失 markers; NEVER '
                   'valid_keys/reference data'),
        repeats=REPEATS, D_s=D, utility_C0_tokens=60000,
        model='GLM-5.3-Flash subscription (marginal ¥0; tokens/latency '
              'recorded)', out_caps=OUT_CAP,
        caps=dict(calls=CAP_CALLS, wall_s=CAP_WALL_S),
        fail_policy='per-run fail-stop; >3 INCOMPLETE runs total -> '
                    'batch stop; no retries',
        evaluator_sha256=ev_sha,
        criteria=dict(
            C1='ONLINE mean eU >= max(fixed) over all scenarios',
            C2='per-scenario ONLINE t_q >= best-fixed t_q - 0.05',
            C3='S3 control: ONLINE repairs 0/5',
            C4='alignment: where P_ACCEPT>P_TARGETED, ONLINE chose accept',
            online_value_supported='C1 AND C2 AND C3'),
        boundary='exploratory n=5/scenario, single doc round 1; not '
                 'confirmation; not full (Z,R,pi) — Z is fixed to the '
                 'closure definition, R to {accept, targeted} for ONLINE')


def gates(args):
    if os.environ.get('H1ON_GO') != '1':
        raise PermissionError('requires H1ON_GO=1')
    dirty = subprocess.run(
        ['git', '-C', str(ROOT), 'status', '--porcelain', '--',
         'deadline_reward_v1'], capture_output=True, text=True).stdout.strip()
    if dirty:
        raise PermissionError(f'uncommitted changes:\n{dirty}')
    raw = FREEZE.read_bytes()
    if args.freeze_sha256 != hashlib.sha256(raw).hexdigest():
        raise PermissionError('freeze hash mismatch')
    f = json.loads(raw)
    if f['version'] != 'H1ONLINE_FREEZE_v6':
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
    valid_keys = None  # loaded per-doc below from the v5 freeze keys rule
    # re-derive mechanical keys per doc using the frozen v5 rule
    import re as _re
    from deadline_reward_v1.full_dag_silver import doc_atoms
    creds = load_env_creds()
    doc = load_docs()[freeze['doc_slots'][0]]
    atoms = doc_atoms(doc['text'])
    keys = ([f'd:{k}' for k in atoms['dates'][:4]]
            + [f'a:{k}' for k in atoms['amounts'][:3]]
            + [f'p:{k}' for k in atoms['penalties'][:3]]
            + [f'e:{k}' for k in atoms['entities'][:3]])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    ledger = open(out / 'LEDGER.jsonl', 'w')
    t0 = time.monotonic()
    calls = 0
    results = []
    from copy import deepcopy
    d2_full = set(ORDER) - {ROOT_NODE}

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
                 lat=o['latency_s'],
                 garbage=replace_garbage), ensure_ascii=False) + '\n')
        ledger.flush()
        return o

    def evaluate(dag_outputs, tok, clk):
        full, by_cat = eval_by_category(dag_outputs, keys)
        return dict(t_q=full['terminal_q'], hits=full['terminal_hits'],
                    by_category=by_cat, tokens=int(tok),
                    latency=round(clk, 1), met=clk <= D,
                    eU=round(utility(full['terminal_q'], tok, clk), 4))

    try:
        for sid, sc in SCENARIOS.items():
            fault = sc['fault']
            closure = closure_for(fault)
            for rep in range(1, REPEATS + 1):
                rid = f'{sid}_r{rep}'
                print(f'[{rid}] shared run (fault={fault})...', flush=True)
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
                    {n: dict(answer=v['answer'][:3000]) for n, v in
                     shared.items()}, ensure_ascii=False, indent=1))
                # detection + online decision (observables only)
                detection = any(not parse_ok(shared[n]['answer'])
                                for n in ORDER)
                sig = degrade_signal(shared['sink']['answer'])
                online_repairs = bool(detection and sig)
                for pol in POLICIES:
                    prid = f'{rid}|{pol}'
                    ac = HeteroDAG(doc['text'], doc['doc_id'])
                    ac.outputs = deepcopy(shared)
                    r_clk, r_tok = sh_clk, sh_tok
                    if pol == 'P_TARGETED' and detection:
                        rc = closure
                    elif pol == 'P_FULL' and detection:
                        rc = d2_full
                    elif pol == 'ONLINE' and online_repairs:
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
                    ev = evaluate(ac.outputs, r_tok, r_clk)
                    ev.update(rid=prid, scenario=sid, rep=rep, policy=pol,
                              detection=detection, degrade_signal=sig,
                              online_repaired=online_repairs,
                              extra_calls=len(rc))
                    results.append(ev)
                    print(f'  {pol:>10}: t_q={ev["t_q"]:.3f} '
                          f'eU={ev["eU"]:+.4f} extra={len(rc)}', flush=True)
                if sum(1 for e in results
                       if e['policy'] == 'ONLINE' and False):
                    pass
        # aggregate
        import statistics as st
        agg = {}
        for sid in SCENARIOS:
            for pol in POLICIES:
                rs = [e for e in results
                      if e['scenario'] == sid and e['policy'] == pol]
                agg[f'{sid}|{pol}'] = dict(
                    n=len(rs),
                    t_q_mean=st.mean([e['t_q'] for e in rs]),
                    eU_mean=st.mean([e['eU'] for e in rs]))
        online_all = st.mean([e['eU'] for e in results
                              if e['policy'] == 'ONLINE'])
        fixed_best = max(
            st.mean([e['eU'] for e in results if e['policy'] == p])
            for p in ('P_ACCEPT', 'P_TARGETED', 'P_FULL'))
        c1 = online_all >= fixed_best
        c2 = all(
            agg[f'{sid}|ONLINE']['t_q_mean']
            >= max(agg[f'{sid}|{p}']['t_q_mean'] for p in
                   ('P_ACCEPT', 'P_TARGETED', 'P_FULL')) - 0.05
            for sid in SCENARIOS)
        c3 = all(not e['online_repaired'] for e in results
                 if e['scenario'] == 'S3' and e['policy'] == 'ONLINE')
        verdicts = dict(C1_c1=c1, C2_quality=c2, C3_control=c3,
                        online_value_supported=bool(c1 and c2 and c3),
                        online_eU_mean=online_all,
                        fixed_best_eU_mean=fixed_best)
        (out / 'H1ONLINE_RESULTS.json').write_text(json.dumps(
            dict(status='COMPLETE', results=results, aggregate=agg,
                 verdicts=verdicts, calls=calls, cash_cny=0.0,
                 wall_s=round(time.monotonic() - t0, 1)),
            ensure_ascii=False, indent=1))
        print(json.dumps(verdicts, ensure_ascii=False, indent=1))
        print(f'calls={calls} wall={time.monotonic()-t0:.0f}s ¥0')
    except BaseException as exc:
        (out / 'H1ONLINE_INCOMPLETE.json').write_text(json.dumps(
            dict(reason=repr(exc), results=results, calls=calls,
                 traceback=traceback.format_exc()),
            ensure_ascii=False, indent=1, default=str))
        print(f'INCOMPLETE: {exc}')


if __name__ == '__main__':
    main()
