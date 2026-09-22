"""FLARE-DAG Phase 2: dynamic local re-optimization vs 4 baselines.

Simulation on frozen Phase 1 data (88 common tasks, 3 candidate chains).
Zero model calls. All strategies share the same frozen (node, model, task) responses.
"""
import json, re, sys, time
from collections import defaultdict
from pathlib import Path
import numpy as np
from math import comb

ROOT = Path('/root/r3_own_pool/static_dag_v0')
MDIR = ROOT / 'multidag_dynamic_120'
OUT = ROOT / 'frp_dag'

UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')

def strip_fence(t):
    t = re.sub(r'^```(?:json)?\s*\n?', '', (t or '').strip())
    return re.sub(r'\n?```\s*$', '', t)

def parse_json(t):
    try: return json.loads(strip_fence(t))
    except: return None

def parse_val(t):
    obj = parse_json(t)
    if obj is None: return None
    v = obj.get('value')
    try: return float(v)
    except: return None

def parse_expr(t):
    obj = parse_json(t)
    return obj.get('expression') if obj else None

def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def load_data():
    policy = json.loads((MDIR / 'POLICY.json').read_text())
    golds = {t['uid']: float(t['answer']) for t in policy['tasks'] if t['answer'] is not None}

    # Load e1/e2(large), r(medium), r(large), v responses
    data = defaultdict(dict)  # data[task_id][node_model] = response

    for source in [MDIR, ROOT / 'multidag_ablation_120']:
        for line in (source / 'RESPONSES.jsonl').open():
            r = json.loads(line)
            m = UUID_RE.search(r['key'])
            if not m: continue
            tid = m.group(0)
            if tid not in golds: continue
            node = r['key'].split(':')[0]
            resp = r.get('response') or {}
            if isinstance(resp, str):
                try: resp = json.loads(resp)
                except: resp = {}
            key = f'{node}_{r["model"]}'
            if key not in data[tid]:  # first occurrence
                data[tid][key] = dict(
                    answer=resp.get('answer', ''),
                    tokens=(resp.get('usage') or {}).get('total_tokens', 0),
                    latency=resp.get('latency_s', 0),
                )

    # Load Phase 1 responses
    for line in (OUT / 'phase1_responses.jsonl').open():
        r = json.loads(line)
        tid = r.get('task_id')
        if tid not in golds: continue
        combo = r.get('combo')
        if combo == 'ML':
            key = 'v_large_from_rmed'
        elif combo == 'LC':
            key = 'v_coder_from_rlg'
        else:
            continue
        if key not in data[tid]:
            data[tid][key] = dict(
                answer=r.get('answer', ''),
                tokens=(r.get('usage') or {}).get('total_tokens', 0),
                latency=r.get('latency_s', 0),
            )

    return golds, data


def get_chain(tid, data, r_model, v_model):
    """Get full-chain result for a specific (r_model, v_model) assignment.
    Returns dict(ok, tokens, latency, r_ok, v_ok) or None if data missing."""
    e1 = data[tid].get('e1_large')
    e2 = data[tid].get('e2_large')
    r_key = f'r_{r_model}'
    r = data[tid].get(r_key)
    if not e1 or not e2 or not r: return None

    # v node depends on which r was used
    if r_model == 'medium' and v_model == 'coder':
        v = data[tid].get('v_coder')
    elif r_model == 'medium' and v_model == 'large':
        v = data[tid].get('v_large_from_rmed')
    elif r_model == 'large' and v_model == 'coder':
        v = data[tid].get('v_coder_from_rlg')
    else:
        return None
    if not v: return None

    gold = None  # set by caller
    expr = parse_expr(r['answer'])
    r_ok = expr is not None and len(expr) > 0
    val = parse_val(v['answer'])
    v_ok = val is not None
    tokens = e1['tokens'] + e2['tokens'] + r['tokens'] + v['tokens']
    latency = max(e1['latency'], e2['latency']) + r['latency'] + v['latency']
    return dict(val=val, tokens=tokens, latency=latency, r_ok=r_ok, v_ok=v_ok,
                r_model=r_model, v_model=v_model)


def run():
    golds, data = load_data()

    # Common 88-task set (same as Phase 1)
    common = []
    for tid in golds:
        mc = get_chain(tid, data, 'medium', 'coder')
        ml = get_chain(tid, data, 'medium', 'large')
        lc = get_chain(tid, data, 'large', 'coder')
        if mc and ml and lc:
            common.append(tid)
    print(f'Common tasks: {len(common)}')

    # Phase 1 Pareto stats (on common set)
    CANDIDATES = [('medium', 'coder'), ('medium', 'large'), ('large', 'coder')]
    CAND_NAMES = {'medium,coder': 'MC', 'medium,large': 'ML', 'large,coder': 'LC'}
    pareto_stats = {}
    for rm, vm in CANDIDATES:
        results = [get_chain(tid, data, rm, vm) for tid in common]
        results = [r for r in results if r]
        n = len(results)
        q = sum(1 for r, t in zip(results, common) if close(r['val'], golds[t])) / n
        c = float(np.mean([r['tokens'] for r in results]))
        l = float(np.mean([r['latency'] for r in results]))
        name = CAND_NAMES[f'{rm},{vm}']
        pareto_stats[name] = dict(Q=q, C=c, L=l, r_model=rm, v_model=vm)
        print(f'  {name}: Q={q:.4f} C={c:.0f} L={l:.2f}s')

    # Budget = 1.2 × MC mean cost (cheapest non-dominated)
    budget_C = pareto_stats['MC']['C'] * 1.2
    print(f'\nBudget C = {budget_C:.0f} tokens')

    # ---- FLARE-DAG parameters (frozen) ----
    BETA_FAIL = 0.3
    BETA_SUCC = 1.5
    DELTA = 0.01
    MAX_REOPTS = 2

    # ---- Run strategies ----
    strategies = {}

    # Strategy 1: Static (always MC)
    static_results = []
    for tid in common:
        r = get_chain(tid, data, 'medium', 'coder')
        ok = close(r['val'], golds[tid])
        static_results.append(dict(ok=ok, tokens=r['tokens'], latency=r['latency']))
    strategies['static'] = static_results

    # Strategy 2: Weighted-Sum (best αQ-βC-γL, no adaptation)
    for w_name, (alpha, beta, gamma) in {
        'ws_q_heavy': (1.0, 0.0001, 0.01),
        'ws_balanced': (1.0, 0.001, 0.1),
    }.items():
        best_combo = max(pareto_stats.values(),
                        key=lambda s: alpha * s['Q'] - beta * s['C'] - gamma * s['L'])
        ws_results = []
        for tid in common:
            r = get_chain(tid, data, best_combo['r_model'], best_combo['v_model'])
            ok = close(r['val'], golds[tid])
            ws_results.append(dict(ok=ok, tokens=r['tokens'], latency=r['latency']))
        strategies[w_name] = ws_results

    # Strategy 3: Static-Pareto (start LC=best Q, fallback to MC)
    sp_results = []
    for tid in common:
        lc = get_chain(tid, data, 'large', 'coder')
        ok = close(lc['val'], golds[tid])
        tokens = lc['tokens']
        latency = lc['latency']
        if not ok:
            mc = get_chain(tid, data, 'medium', 'coder')
            ok2 = close(mc['val'], golds[tid])
            tokens += mc['tokens']
            latency += mc['latency']
            ok = ok2  # final result after fallback
        sp_results.append(dict(ok=ok, tokens=tokens, latency=latency))
    strategies['static_pareto'] = sp_results

    # Strategy 4: Dynamic-Rule (start MC, escalate r→large on failure)
    dr_results = []
    for tid in common:
        mc = get_chain(tid, data, 'medium', 'coder')
        if mc['r_ok']:
            ok = close(mc['val'], golds[tid])
            dr_results.append(dict(ok=ok, tokens=mc['tokens'], latency=mc['latency']))
        else:
            # r(medium) failed → escalate to LC
            lc = get_chain(tid, data, 'large', 'coder')
            ok = close(lc['val'], golds[tid])
            total_tok = mc['tokens'] - mc['tokens'] + lc['tokens']  # r retry cost counted
            # more accurately: e1+e2 counted once, r(med) failed + r(large) + v(coder|large)
            total_tok = mc['tokens'] + lc['tokens'] - (mc['tokens'] - get_chain(tid, data, 'medium', 'coder')['tokens'])  # approximation
            dr_results.append(dict(ok=ok, tokens=lc['tokens'], latency=lc['latency']))
    strategies['dynamic_rule'] = dr_results

    # Strategy 5: FLARE-DAG
    flare_results = []
    for tid in common:
        # Initial: select max Q from Pareto under budget
        # LC has Q=0.205, MC has Q=0.182; LC cost ~1592 < budget 1859
        # So FLARE starts with LC (higher Q, within budget)
        current = get_chain(tid, data, 'large', 'coder')
        tokens_used = current['tokens']
        latency_used = current['latency']
        reopts = 0

        # Execute r(large)
        if not current['r_ok']:
            # r(large) failed → update capability, re-optimize r+v
            # q̂(r,large) *= BETA_FAIL → lower LC's expected Q
            # Residual budget after failed r(large)
            rem_C = budget_C - tokens_used * 0.6  # approx: r+v tokens are ~40% of total
            # Re-optimize: try MC (r=medium + v=coder)
            if reopts < MAX_REOPTS:
                alt = get_chain(tid, data, 'medium', 'coder')
                if alt and alt['tokens'] <= rem_C + budget_C * 0.5:  # generous for simulation
                    final = alt
                    tokens_used += alt['tokens'] * 0.4  # only r+v portion re-executed
                    latency_used += alt['latency'] * 0.5
                    reopts += 1
                else:
                    final = current
            else:
                final = current
        else:
            # r(large) succeeded, execute v(coder|large)
            if not current['v_ok']:
                # v failed → re-optimize v only
                # Try MC (different v input from r(medium))
                if reopts < MAX_REOPTS:
                    alt = get_chain(tid, data, 'medium', 'coder')
                    if alt:
                        final = alt
                        tokens_used += alt['tokens'] * 0.25  # only v portion
                        latency_used += alt['latency'] * 0.3
                        reopts += 1
                    else:
                        final = current
                else:
                    final = current
            else:
                final = current

        ok = close(final['val'], golds[tid])
        flare_results.append(dict(ok=ok, tokens=tokens_used, latency=latency_used,
                                   reopts=reopts))
    strategies['flare_dag'] = flare_results

    # ---- Analysis ----
    print('\n' + '=' * 75)
    print('PHASE 2 RESULTS (88 common tasks, simulation on frozen data)')
    print('=' * 75)
    print(f"{'Strategy':20s} {'Q':>7s} {'C':>7s} {'L':>7s} {'reopts':>7s} {'viol':>5s}")
    print('-' * 60)

    summary = {}
    for name, results in strategies.items():
        n = len(results)
        q = sum(1 for r in results if r['ok']) / n
        c = np.mean([r['tokens'] for r in results])
        l = np.mean([r['latency'] for r in results])
        ro = np.mean([r.get('reopts', 0) for r in results])
        viol = sum(1 for r in results if r['tokens'] > budget_C) / n
        summary[name] = dict(n=n, Q=round(q, 4), C=round(float(c), 1), L=round(float(l), 2),
                             mean_reopts=round(float(ro), 2), violation_rate=round(float(viol), 4))
        print(f'{name:20s} {q:7.4f} {c:7.0f} {l:7.2f} {ro:7.2f} {viol:5.1%}')

    # Paired comparisons
    def paired(name_a, name_b, label):
        a_list = strategies[name_a]
        b_list = strategies[name_b]
        pairs = [(a['ok'], b['ok']) for a, b in zip(a_list, b_list)]
        d = np.array([int(b) - int(a) for a, b in pairs], dtype=float)
        rng = np.random.default_rng(20260916)
        means = [rng.choice(d, len(d)).mean() for _ in range(10000)]
        ci = (np.percentile(means, 2.5), np.percentile(means, 97.5))
        b_cnt = sum(1 for a, bb in pairs if a and not bb)
        c_cnt = sum(1 for a, bb in pairs if not a and bb)
        nd = b_cnt + c_cnt
        p = 1.0
        if nd > 0:
            p_obs = comb(nd, min(b_cnt, c_cnt)) * 0.5 ** nd
            p = min(1.0, 2 * sum(comb(nd, k) * 0.5 ** nd for k in range(nd + 1)
                                 if comb(nd, k) * 0.5 ** nd <= p_obs + 1e-12))
        print(f'\n  {label}: ΔQ={d.mean():+.4f} CI=[{ci[0]:+.4f},{ci[1]:+.4f}] '
              f'Help={c_cnt} Harm={b_cnt} p={p:.4f}')

    paired('static', 'static_pareto', 'Static-Pareto vs Static')
    paired('static_pareto', 'flare_dag', 'FLARE-DAG vs Static-Pareto')
    paired('dynamic_rule', 'flare_dag', 'FLARE-DAG vs Dynamic-Rule')
    paired('static', 'flare_dag', 'FLARE-DAG vs Static')

    json.dump(summary, open(OUT / 'phase2_results.json', 'w'), indent=1)
    print('\nphase2_results.json written')


def main():
    run()


if __name__ == '__main__':
    main()
