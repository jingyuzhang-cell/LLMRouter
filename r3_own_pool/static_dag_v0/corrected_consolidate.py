"""Consolidated analysis on the CORRECTED arms (fixed json_value parser).

Reads corrected_replay/CORRECTED_ARMS.json and computes, zero model calls:
  1. main table Q/tokens/calls/latency for static, dynamic, sm, rd, fg;
  2. paired comparisons with task bootstrap CI + McNemar (dynamic vs static,
     sm vs static, rd vs sm, fg vs rd, fg vs sm);
  3. FG scope audit on corrected rounds (unaffected-branch repeats, redundant
     calls) and post-hoc budget violations vs 1.2x static realized;
  4. determinism audit on the corrected FG key set (vs mapped RD/base calls);
  5. supplementary E1 (recovery effectiveness, N_initially_wrong recomputed
     with the fixed parser), E2 (budget sweep), E3 (detection evaluation on
     initial-pass outputs with fixed parsing + deterministic evidence
     injection check).

Writes corrected_replay/CORRECTED_CONSOLIDATED.json.
"""
import json
import math
import random
import time

from . import core
from . import tool_aware_v1 as v
from .multidag_dynamic import OUT, close, parse_facts_safe, value_of
from .multidag_ablation import ABL
from .multidag_fullgraph import FG
from .tatqa_benchmark_build import literals
from .decompose_v1 import exec_calc
from .corrected_replay import RES, json_value_fixed

SEED = 20260918
B = 10000
CLOSURE = {'e1': ['r', 'v'], 'e2': ['r', 'v'], 'r': ['v'], 'v': []}


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n * 2)


def load_responses():
    out = {}
    for folder in (OUT, ABL, FG):
        for l in (folder / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            out[r['key']] = r
    return out


def run():
    corrected = json.loads((RES / 'CORRECTED_ARMS.json').read_text())
    arms = corrected['arms']
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    uids = [t['uid'] for t in tasks]
    n = len(tasks)
    gold = {t['uid']: t['answer'] for t in tasks}
    resp = load_responses()
    base_raw = json.loads((OUT / 'RAW_TAIL.json').read_text())

    ok = {arm: [int(arms[arm][u]['ok']) for u in uids] for arm in arms}
    used = {arm: {u: arms[arm][u]['used'] for u in uids} for arm in arms}
    lat = {arm: {u: arms[arm][u]['latency'] for u in uids} for arm in arms}
    n_adapt = {arm: sum(len(arms[arm][u]['keys']) - 4 for u in uids) for arm in arms}

    def q(arm):
        return round(sum(ok[arm]) / n, 4)

    rng = random.Random(SEED)

    def boot_ci_paired(a, b):
        diffs = [x - y for x, y in zip(a, b)]
        out = []
        for _ in range(B):
            out.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
        out.sort()
        return [round(out[int(0.025 * B)], 4), round(out[int(0.975 * B) - 1], 4)]

    def paired(a_arm, b_arm):
        a, b = ok[a_arm], ok[b_arm]
        dQ = round(sum(x - y for x, y in zip(a, b)) / n, 4)
        ci = boot_ci_paired(a, b)
        b_cnt = sum(1 for x, y in zip(a, b) if y == 0 and x == 1)
        c_cnt = sum(1 for x, y in zip(a, b) if y == 1 and x == 0)
        return dict(dQ=dQ, ci=ci, help=b_cnt, harm=c_cnt,
                    mcnemar=dict(b=b_cnt, c=c_cnt, p_exact=round(mcnemar_exact(b_cnt, c_cnt), 6)))

    # ---- FG scope audit on corrected rounds ----
    round_stats = {}
    branch_repeats = []
    redundant_calls = 0
    for u in uids:
        task_rep = 0
        for rnd in arms['fg'][u]['rounds']:
            round_stats[rnd['round']] = round_stats.get(rnd['round'], 0) + 1
            trig = set(rnd['triggered'])
            needed = set(trig)
            for nd in trig:
                needed.update(CLOSURE[nd])
            for nd in ('e1', 'e2', 'r', 'v'):
                if nd not in needed:
                    redundant_calls += 1
            if not (trig <= {'e1', 'e2'}):
                task_rep += 2
            else:
                task_rep += len({'e1', 'e2'} - trig)
        branch_repeats.append(task_rep)
    sb = {u: sum(float((resp[k]['response'].get('usage') or {}).get('total_tokens') or 0)
                 for k in base_raw['static'][u]['keys']) for u in uids}
    budget = {}
    for arm in ('sm', 'rd', 'fg'):
        ratios = {u: used[arm][u] / sb[u] for u in uids}
        sweep = {}
        for m in (1.0, 1.2, 1.5, 2.0, 2.5):
            sweep[str(m)] = dict(violations=sum(1 for u in uids if ratios[u] > m + 1e-9),
                                 rate=round(sum(1 for u in uids if ratios[u] > m + 1e-9) / n, 4))
        budget[arm] = dict(max_ratio=round(max(ratios.values()), 3), sweep=sweep)

    # ---- determinism audit on corrected FG key set ----
    reqs = {}
    ans = {}
    for folder in (OUT, ABL, FG):
        for l in (folder / 'REQUESTS.jsonl').read_text().splitlines():
            r = json.loads(l)
            reqs[r['key']] = r
        for l in (folder / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            ans[r['key']] = r
    abl_raw = json.loads((ABL / 'RAW_TAIL.json').read_text())
    det_checked = 0
    det_mismatch = 0
    same_prompt_mismatch = 0
    for u in uids:
        evs = abl_raw['rd'][u]['events']
        e_failed = {e['node'] for e in evs if e['node'] in ('e1', 'e2') and e['kind'] == 'fb'}
        r_esc = any(e['node'] == 'r' and e['kind'] == 'esc' for e in evs)
        v_esc = any(e['node'] == 'v' and e['kind'] == 'esc' for e in evs)
        fg_keys = set(arms['fg'][u]['keys'])
        mapping = {}
        if e_failed:
            for node in ('e1', 'e2'):
                mapping[f'{node}:fg:{u}:e'] = f'{node}:rd:{u}:fb' if node in e_failed else f'{node}:{u}'
            mapping[f'r:fg:{u}:e'] = f'r:rd:{u}:fb-d'
            if not r_esc:
                mapping[f'v:fg:{u}:e'] = f'v:rd:{u}:fb-d'
        if r_esc:
            for node in ('e1', 'e2'):
                mapping[f'{node}:fg:{u}:r'] = f'{node}:rd:{u}:fb' if node in e_failed else f'{node}:{u}'
            mapping[f'r:fg:{u}:r'] = f'r:rd:{u}:esc'
            mapping[f'v:fg:{u}:r'] = f'v:rd:{u}:fb-d'
        if v_esc:
            for node in ('e1', 'e2'):
                mapping[f'{node}:fg:{u}:v'] = f'{node}:rd:{u}:fb' if node in e_failed else f'{node}:{u}'
            if r_esc:
                mapping[f'r:fg:{u}:v'] = f'r:rd:{u}:esc'
            elif e_failed:
                mapping[f'r:fg:{u}:v'] = f'r:rd:{u}:fb-d'
            else:
                mapping[f'r:fg:{u}:v'] = f'r:{u}'
            mapping[f'v:fg:{u}:v'] = f'v:rd:{u}:esc'
        for fg_key, src_key in mapping.items():
            if fg_key not in fg_keys or fg_key not in ans:
                continue
            det_checked += 1
            if ans[fg_key]['response'].get('answer') != ans[src_key]['response'].get('answer'):
                det_mismatch += 1
                if reqs[fg_key]['prompt'] == reqs[src_key]['prompt']:
                    same_prompt_mismatch += 1

    # ---- E1 recovery effectiveness (fixed parser; N = initially wrong) ----
    init_v_ok = {u: close(json_value_fixed(resp[f'v:{u}']['response']['answer']), gold[u]) for u in uids}
    n_wrong = sum(1 for u in uids if not init_v_ok[u])
    e1_out = {}
    for arm in arms:
        m_cnt = 0
        n_det = 0
        missed = 0
        toks = []
        for u in uids:
            if init_v_ok[u]:
                continue
            fired = arms[arm][u]['v_fired'] or any(
                e.get('node') in ('e1', 'e2', 'r') and e.get('attempted') for e in arms[arm][u]['events'])
            if fired:
                n_det += 1
            if arms[arm][u]['ok']:
                m_cnt += 1
                toks.append(used[arm][u])
            elif not fired:
                missed += 1
        e1_out[arm] = dict(
            recovery_rate=round(m_cnt / n_wrong, 4), m_recovered=m_cnt, N_wrong=n_wrong,
            rr_detected=round(m_cnt / n_det, 4) if n_det else None, n_detected_engaged=n_det,
            missed_detection_tasks=missed,
            tokens_per_recovery=round(sum(toks) / len(toks), 1) if toks else None)
    # recovery coverage (node level, corrected arms)
    cover = {}
    for arm in arms:
        covs = []
        missed_nodes = {}
        for u in uids:
            # true affected region from initial pass (fixed parsing)
            f1, _ = parse_facts_safe(resp[f'e1:{u}']['response']['answer'])
            f2, _ = parse_facts_safe(resp[f'e2:{u}']['response']['answer'])
            t = next(x for x in tasks if x['uid'] == u)
            combined = f1['facts'] + f2['facts']
            gold_lits = [x for x in literals(t['derivation']) if x not in (0.0, 1.0, 100.0)]
            recall_ok = all(any(abs(fv - g) <= 1e-6 for fv in [f['value'] for f in combined]) for g in gold_lits)
            region = set()
            if not f1['facts']:
                region.update(['e1', 'r', 'v'])
            if not f2['facts']:
                region.update(['e2', 'r', 'v'])
            if f1['facts'] and f2['facts'] and not recall_ok:
                region.update(['e1', 'e2', 'r', 'v'])
            rval, rerr = value_of(resp[f'r:{u}']['response']['answer'], {'facts': combined})
            if rerr or not close(rval, gold[u]):
                region.update(['r', 'v'])
            if not init_v_ok[u]:
                region.add('v')
            if not region:
                continue
            executed = {k.split(':')[0] for k in arms[arm][u]['keys'] if f':{arm}:' in k or ':fg:' in k}
            covs.append(len(executed & region) / len(region))
            for nd in region - executed:
                missed_nodes[nd] = missed_nodes.get(nd, 0) + 1
        cover[arm] = dict(coverage_mean=round(sum(covs) / len(covs), 4) if covs else None,
                          n_region_tasks=len(covs), missed_nodes_by_type=missed_nodes)

    # ---- E2 budget sweep (reported above in `budget`) ----

    # ---- E3 detection evaluation on initial-pass outputs (fixed parsing) ----
    def prf(tp, fp, fn):
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
        return dict(tp=tp, fp=fp, fn=fn,
                    precision=round(prec, 4) if prec is not None else None,
                    recall=round(rec, 4) if rec is not None else None,
                    f1=round(f1, 4) if f1 is not None else None)

    ev_tp = ev_fn = 0
    reas_fn = 0
    exec_tp = 0
    ver_tp = ver_fp = ver_fn = 0
    inj_exec = inj_break = inj_tasks = 0
    for u in uids:
        f1, _ = parse_facts_safe(resp[f'e1:{u}']['response']['answer'])
        f2, _ = parse_facts_safe(resp[f'e2:{u}']['response']['answer'])
        t = next(x for x in tasks if x['uid'] == u)
        combined = f1['facts'] + f2['facts']
        gold_lits = [x for x in literals(t['derivation']) if x not in (0.0, 1.0, 100.0)]
        recall_ok = all(any(abs(fv - g) <= 1e-6 for fv in [f['value'] for f in combined]) for g in gold_lits)
        if not f1['facts'] or not f2['facts']:
            ev_tp += 1
        elif not recall_ok:
            ev_fn += 1
        rval, rerr = value_of(resp[f'r:{u}']['response']['answer'], {'facts': combined})
        if rerr:
            exec_tp += 1
        elif not close(rval, gold[u]):
            reas_fn += 1
        vv = json_value_fixed(resp[f'v:{u}']['response']['answer'])
        v_fires = (vv is None) or (not rerr and not close(vv, rval))
        v_wrong = not close(vv, gold[u])
        if v_wrong:
            if v_fires:
                ver_tp += 1
            else:
                ver_fn += 1
        else:
            if v_fires:
                ver_fp += 1
        if f1['facts'] and f2['facts'] and recall_ok:
            facts = [dict(f) for f in combined]
            if facts:
                facts[0]['value'] = facts[0]['value'] * 0.8
                try:
                    exec_calc(v.decode(resp[f'r:{u}']['response']['answer'])['expression'], {'facts': facts})
                    inj_exec += 1
                except Exception:
                    inj_break += 1
                inj_tasks += 1
    e3_out = dict(
        evidence=dict(n=ev_tp + ev_fn, **prf(ev_tp, 0, ev_fn),
                      note='GT: e output empty/unparseable (TP) or well-formed with operand-recall gap (FN); e detector fires only on empty/unparseable'),
        reasoning=dict(n=reas_fn, **prf(0, 0, reas_fn),
                       note='GT: r executable but wrong value; r detector fires only on unexecutable (recall 0 by design)'),
        execution=dict(n=exec_tp, **prf(exec_tp, 0, 0),
                       note='GT: r unparseable/unexecutable; detector targets exactly this'),
        verification=dict(n=ver_tp + ver_fp + ver_fn, **prf(ver_tp, ver_fp, ver_fn),
                          note='GT: v wrong; fires on unparseable or v!=r; FP = v corrected a wrong r'),
        structure=dict(n=0, note='N/A on fixed-DAG panel; requires an injection run'),
        evidence_injection_check=dict(tasks=inj_tasks, r_expression_still_executes=inj_exec,
                                      r_expression_breaks=inj_break,
                                      note='x0.8 perturbation of one fact value; deterministic execution of the real r expression on perturbed facts'))

    rep = dict(
        generated_unix=time.time(), n=n,
        basis='corrected_replay/CORRECTED_ARMS.json (v-stage re-decision, fixed json_value parser, zero new calls)',
        main_table={arm: dict(Q=q(arm),
                              mean_tokens=round(sum(used[arm].values()) / n, 1),
                              total_tokens=round(sum(used[arm].values()), 1),
                              adaptation_calls=n_adapt[arm],
                              mean_latency_s=round(sum(lat[arm].values()) / n, 2))
                    for arm in arms},
        paired=dict(dynamic_vs_static=paired('dynamic', 'static'),
                    sm_vs_static=paired('sm', 'static'),
                    rd_vs_sm=paired('rd', 'sm'),
                    rd_vs_static=paired('rd', 'static'),
                    fg_vs_rd=paired('fg', 'rd'),
                    fg_vs_sm=paired('fg', 'sm')),
        fg_scope_audit=dict(rounds=round_stats,
                            unaffected_branch_repeats=sum(branch_repeats),
                            mean_branch_repeats_per_task=round(sum(branch_repeats) / n, 3),
                            redundant_calls=redundant_calls,
                            tokens_saved_by_local_scope=round(sum(used['fg'].values()) / n - sum(used['rd'].values()) / n, 1),
                            calls_saved_by_local_scope=n_adapt['fg'] - n_adapt['rd'],
                            latency_saved_by_local_scope=round(sum(lat['fg'].values()) / n - sum(lat['rd'].values()) / n, 2)),
        budget_violations=budget,
        determinism_audit=dict(mapped_checked=det_checked, answer_mismatches=det_mismatch,
                               same_prompt_mismatches=same_prompt_mismatch),
        E1_recovery_effectiveness=e1_out,
        E1_recovery_coverage=cover,
        E3_detection_evaluation=e3_out,
        retention_rd=dict(value=round((q('rd') - q('static')) / (q('dynamic') - q('static')), 4) if q('dynamic') != q('static') else None,
                          note='(Q_RD - Q_static)/(Q_dynamic - Q_static) on corrected arms'))
    (RES / 'CORRECTED_CONSOLIDATED.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:5000])


if __name__ == '__main__':
    run()
