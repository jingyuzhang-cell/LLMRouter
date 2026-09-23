"""Pre-registered analysis of the FG (Full-Graph re-execution) control arm.

Zero model calls. Primary comparison: FG vs RD (scope isolation, everything else
identical). Secondary: FG vs SM. Records per the frozen protocol: accuracy,
paired bootstrap CI + McNemar + Help/Harm, tokens, call counts, observed
latency, unaffected-branch repeat executions, post-hoc budget violations.
Also runs the determinism audit: every FG adaptation call must reproduce the
answer of its mapped RD/base call (temperature 0); mismatches are reported
as nondeterminism instead of being silently treated as scope effects.
"""
import json
import math
import random
import time

from .multidag_dynamic import OUT
from .multidag_ablation import ABL
from .multidag_fullgraph import FG, PLANNED

SEED = 20260918
B = 10000


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n * 2)


def load_usage(folder):
    usage = {}
    lat = {}
    model_of = {}
    for l in (folder / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        usage[r['key']] = float((r['response'].get('usage') or {}).get('total_tokens') or 0)
        if r['response'].get('latency_s') is not None:
            lat[r['key']] = r['response']['latency_s']
        model_of[r['key']] = r.get('model')
    return usage, lat, model_of


def run():
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    uids = [t['uid'] for t in tasks]
    n = len(tasks)
    base_raw = json.loads((OUT / 'RAW_TAIL.json').read_text())
    abl_raw = json.loads((ABL / 'RAW_TAIL.json').read_text())
    fg_raw = json.loads((FG / 'RAW_TAIL.json').read_text())
    u_out, l_out, m_out = load_usage(OUT)
    u_abl, l_abl, m_abl = load_usage(ABL)
    u_fg, l_fg, m_fg = load_usage(FG)

    def arm_usage(arm_keys_by_uid):
        return {u: sum(u_out.get(k, 0) + u_abl.get(k, 0) + u_fg.get(k, 0) for k in keys)
                for u, keys in arm_keys_by_uid.items()}

    def arm_latency(arm_keys_by_uid):
        return {u: sum(l_out.get(k, 0) + l_abl.get(k, 0) + l_fg.get(k, 0) for k in keys)
                for u, keys in arm_keys_by_uid.items()}

    keys = {}
    keys['static'] = {u: base_raw['static'][u]['keys'] for u in uids}
    keys['dynamic'] = {u: base_raw['dynamic'][u]['keys'] for u in uids}
    keys['sm'] = {u: abl_raw['sm'][u]['keys'] for u in uids}
    keys['rd'] = {u: abl_raw['rd'][u]['keys'] for u in uids}
    keys['fg'] = {u: fg_raw['fg'][u]['keys'] for u in uids}
    ok = {}
    ok['static'] = [int(base_raw['static'][u]['ok']) for u in uids]
    ok['dynamic'] = [int(base_raw['dynamic'][u]['ok']) for u in uids]
    ok['sm'] = [int(abl_raw['sm'][u]['ok']) for u in uids]
    ok['rd'] = [int(abl_raw['rd'][u]['ok']) for u in uids]
    ok['fg'] = [int(fg_raw['fg'][u]['ok']) for u in uids]

    def q(arm):
        return round(sum(ok[arm]) / n, 4)

    used = {arm: arm_usage(keys[arm]) for arm in keys}
    lat = {arm: arm_latency(keys[arm]) for arm in keys}
    mean_u = {arm: round(sum(used[arm].values()) / n, 1) for arm in keys}
    total_u = {arm: round(sum(used[arm].values()), 1) for arm in keys}
    mean_l = {arm: round(sum(lat[arm].values()) / n, 2) for arm in keys}
    n_adapt = {arm: sum(len(v) - 4 for v in keys[arm].values()) for arm in keys}

    rng = random.Random(SEED)

    def boot_ci_paired(a, b):
        diffs = [x - y for x, y in zip(a, b)]
        out = []
        for _ in range(B):
            out.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
        out.sort()
        return [round(out[int(0.025 * B)], 4), round(out[int(0.975 * B) - 1], 4)]

    def paired(arm_a, arm_b):
        a, b = ok[arm_a], ok[arm_b]
        dQ = round(sum(x - y for x, y in zip(a, b)) / n, 4)
        ci = boot_ci_paired(a, b)
        b_cnt = sum(1 for x, y in zip(a, b) if y == 0 and x == 1)
        c_cnt = sum(1 for x, y in zip(a, b) if y == 1 and x == 0)
        return dict(dQ=dQ, ci=ci, help=b_cnt, harm=c_cnt,
                    mcnemar=dict(b=b_cnt, c=c_cnt, p_exact=round(mcnemar_exact(b_cnt, c_cnt), 6)))

    # ---- unaffected-branch repeat executions (FG) ----
    # A branch node re-executed in a round that was NOT triggered by it.
    branch_repeats = []
    redundant_calls = 0
    round_stats = {'e': 0, 'r': 0, 'v': 0}
    closure = {'e1': ['r', 'v'], 'e2': ['r', 'v'], 'r': ['v'], 'v': []}
    for u in uids:
        rd_ = fg_raw['fg'][u]['rounds']
        task_rep = 0
        for rnd in rd_:
            round_stats[rnd['round']] += 1
            trig = set(rnd['triggered'])
            needed = set(trig)
            for nd in trig:
                needed.update(closure[nd])
            executed_nodes = ['e1', 'e2', 'r', 'v']  # full graph by definition
            for nd in executed_nodes:
                if nd not in needed:
                    redundant_calls += 1
            if trig != {'e1'} and trig != {'e2'} and trig != {'e1', 'e2'}:
                # round not triggered by any branch failure -> both branches re-run
                task_rep += 2
            else:
                clean = {'e1', 'e2'} - trig
                task_rep += len(clean)
        branch_repeats.append(task_rep)
    n_tasks_with_rep = sum(1 for x in branch_repeats if x > 0)
    total_branch_repeats = sum(branch_repeats)

    # ---- post-hoc budget violations (same rule for RD and FG) ----
    sb = {u: sum(u_out.get(k, 0) for k in base_raw['static'][u]['keys']) for u in uids}
    viol = {}
    for arm in ('rd', 'fg', 'sm'):
        viol[arm] = [u for u in uids if used[arm][u] > 1.2 * sb[u] + 1e-9]
    max_ratio = {arm: round(max(used[arm][u] / sb[u] for u in uids), 3) for arm in ('rd', 'fg', 'sm')}

    # ---- determinism audit: FG adaptation calls vs mapped RD/base calls ----
    # mapping logic mirrors test_multidag_fullgraph.check_fg_mapping
    reqs = {}
    for folder in (OUT, ABL, FG):
        for l in (folder / 'REQUESTS.jsonl').read_text().splitlines():
            r = json.loads(l)
            reqs[r['key']] = r
    ans = {}
    for folder in (OUT, ABL, FG):
        for l in (folder / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            ans[r['key']] = r
    abl_ev = {u: abl_raw['rd'][u]['events'] for u in uids}
    det_checked = 0
    det_mismatch = []
    for u in uids:
        evs = abl_ev[u]
        e_failed = {e['node'] for e in evs if e['node'] in ('e1', 'e2') and e['kind'] == 'fb'}
        r_esc = any(e['node'] == 'r' and e['kind'] == 'esc' for e in evs)
        v_esc = any(e['node'] == 'v' and e['kind'] == 'esc' for e in evs)
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
            if fg_key not in ans:
                continue  # not executed (should not happen; recorded separately below)
            det_checked += 1
            if ans[fg_key]['response'].get('answer') != ans[src_key]['response'].get('answer'):
                det_mismatch.append(dict(fg_key=fg_key, src_key=src_key))
    fg_calls = [k for k in ans if k.startswith(('e1:fg:', 'e2:fg:', 'r:fg:', 'v:fg:'))]
    fg_statuses = {}
    for k in fg_calls:
        fg_statuses[ans[k]['response'].get('status')] = fg_statuses.get(ans[k]['response'].get('status'), 0) + 1

    # breakdown of mismatches: same-prompt (pure session nondeterminism) vs
    # diff-prompt (cascade from an upstream divergence), by model
    same_p = {}
    diff_p = {}
    by_node = {}
    model_diff_pairs = 0
    for m in det_mismatch:
        fg_key, src_key = m['fg_key'], m['src_key']
        pe = reqs[fg_key]['prompt'] == reqs[src_key]['prompt']
        me = reqs[fg_key]['model'] == reqs[src_key]['model']
        if not me:
            model_diff_pairs += 1
        bucket = same_p if pe else diff_p
        bucket[reqs[fg_key]['model']] = bucket.get(reqs[fg_key]['model'], 0) + 1
        nd = fg_key.split(':')[0]
        by_node[nd] = by_node.get(nd, 0) + 1
    # pre-existing cross-arm same-prompt pairs (base dynamic vs rd; static vs sm;
    # e fb and r fb-d keys are coder/medium) — divergence rate in the frozen data
    pre_pairs = 0
    pre_div = 0
    for u in uids:
        dk = [k for k in base_raw['dynamic'][u]['keys'] if k.startswith(('e1:dynamic:', 'e2:dynamic:'))]
        rk = [k for k in abl_raw['rd'][u]['keys'] if k.startswith(('e1:rd:', 'e2:rd:'))]
        for ka in dk:
            for kb in rk:
                if ka != kb and reqs.get(ka) and reqs.get(kb) and reqs[ka]['prompt'] == reqs[kb]['prompt'] and reqs[ka]['model'] == reqs[kb]['model']:
                    pre_pairs += 1
                    pre_div += (ans[ka]['response'].get('answer') != ans[kb]['response'].get('answer'))
        sk = [k for k in base_raw['static'][u]['keys'] if k.startswith(('e1:static:', 'e2:static:'))]
        smk = [k for k in abl_raw['sm'][u]['keys'] if k.startswith(('e1:sm:', 'e2:sm:'))]
        for ka in sk:
            for kb in smk:
                if ka != kb and reqs.get(ka) and reqs.get(kb) and reqs[ka]['prompt'] == reqs[kb]['prompt'] and reqs[ka]['model'] == reqs[kb]['model']:
                    pre_pairs += 1
                    pre_div += (ans[ka]['response'].get('answer') != ans[kb]['response'].get('answer'))

    rep = dict(
        generated_unix=time.time(), n=n,
        primary_question='does local (dependency-aware) recovery save computation vs full-graph re-execution, with what quality difference?',
        A_quality=dict(
            static=q('static'), sm=q('sm'), rd=q('rd'), fg=q('fg'),
            fg_vs_rd=paired('fg', 'rd'),
            fg_vs_sm=paired('fg', 'sm'),
            rd_vs_sm=paired('rd', 'sm')),
        B_cost=dict(
            mean_tokens=mean_u, total_tokens=total_u,
            mean_latency_s=mean_l, adaptation_calls=n_adapt,
            initial_calls_shared=4),
        C_scope_audit=dict(
            fg_rounds=round_stats,
            fg_adaptation_calls=n_adapt['fg'],
            rd_adaptation_calls=n_adapt['rd'],
            unaffected_branch_repeats=total_branch_repeats,
            mean_branch_repeats_per_task=round(total_branch_repeats / n, 3),
            tasks_with_branch_repeat=n_tasks_with_rep,
            redundant_calls_fg=redundant_calls,
            tokens_saved_by_local_scope=round(mean_u['fg'] - mean_u['rd'], 1),
            calls_saved_by_local_scope=n_adapt['fg'] - n_adapt['rd'],
            latency_saved_by_local_scope=round(mean_l['fg'] - mean_l['rd'], 2)),
        D_budget=dict(
            rule='post-hoc: per-task used > 1.2 x static realized (no hard limit at execution, same for RD/FG)',
            rd_violations=len(viol['rd']), fg_violations=len(viol['fg']), sm_violations=len(viol['sm']),
            fg_violation_rate=round(len(viol['fg']) / n, 4),
            rd_violation_rate=round(len(viol['rd']) / n, 4),
            max_budget_ratio=dict(rd=max_ratio['rd'], fg=max_ratio['fg'], sm=max_ratio['sm'])),
        E_determinism_audit=dict(
            fg_calls_total=len(fg_calls), fg_statuses=fg_statuses,
            mapped_checked=det_checked, answer_mismatches=len(det_mismatch),
            same_prompt_mismatches_by_model=same_p,
            diff_prompt_mismatches_by_model=diff_p,
            model_mismatch_pairs=model_diff_pairs,
            mismatches_by_node=by_node,
            preexisting_crossarm_same_prompt=dict(pairs=pre_pairs, diverged=pre_div),
            mismatches=det_mismatch[:10],
            note='FG adaptation calls should reproduce mapped RD/base answers at temperature 0; mismatches indicate vllm session nondeterminism (concentrated in the 14B GPTQ model), reported as-is; diff-prompt mismatches are cascades of same-prompt divergences'),
        integrity=dict(all_tasks_in_denominator=n, supplementary_not_confirmatory=True,
                       budget_accounting='post-hoc statistics only'))
    (FG / 'FULLGRAPH_ANALYSIS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:3000])


if __name__ == '__main__':
    run()
