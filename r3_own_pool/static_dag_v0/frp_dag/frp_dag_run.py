"""FRP-DAG simulation v2: correct format parsing, gold from POLICY, simplified model.

e1/e2 fixed to large (dominant Pareto choice). Vary r and v models.
Q per (node, model) = end-to-end success rate from frozen data.
"""
import json, re, sys, time
from collections import defaultdict
from pathlib import Path
import numpy as np
from math import comb

ROOT = Path('/root/r3_own_pool/static_dag_v0')
MDIR = ROOT / 'multidag_dynamic_120'
ADIR = ROOT / 'multidag_ablation_120'
OUT = ROOT / 'frp_dag'

MODELS = ['medium', 'large', 'coder']
R_MODELS = ['medium', 'large', 'coder']
V_MODELS = ['coder', 'medium', 'large']
BEAM_K = 8
EPS = 0.01
SEED = 20260921


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def parse_json_output(text):
    """Parse fenced or raw JSON from model output."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r'^```(?:json)?\s*\n?', '', t)
    t = re.sub(r'\n?```\s*$', '', t)
    try:
        return json.loads(t)
    except Exception:
        return None


def node_value(node, answer):
    """Extract the key value from a node's output based on node type."""
    obj = parse_json_output(answer)
    if obj is None:
        return None
    if node in ('e1', 'e2'):
        # extraction: check facts list is non-empty
        facts = obj.get('facts', [])
        return len(facts) if facts else None
    elif node == 'r':
        # reasoning: return expression string
        return obj.get('expression')
    elif node == 'v':
        # verification: return numeric value
        return obj.get('value')
    return None


def node_ok(node, answer):
    """Deployable quality check: did this node produce parseable output?"""
    val = node_value(node, answer)
    if node in ('e1', 'e2'):
        return val is not None and val > 0
    elif node == 'r':
        return val is not None and isinstance(val, str) and len(val) > 0
    elif node == 'v':
        return val is not None
    return False


def load_all():
    """Load frozen responses + gold + build lookup."""
    policy = json.loads((MDIR / 'POLICY.json').read_text())
    tasks = policy['tasks']  # [{uid, question, derivation, answer, ...}]
    golds = {t['uid']: t['answer'] for t in tasks}
    task_ids = [t['uid'] for t in tasks]

    # load responses from both panels
    frozen = {}
    for d in [MDIR, ADIR]:
        f = d / 'RESPONSES.jsonl'
        if not f.exists():
            continue
        for line in f.open():
            r = json.loads(line)
            parts = r['key'].split(':', 1)
            node = parts[0]
            task_id = parts[1] if len(parts) > 1 else ''
            resp = r.get('response') or {}
            if isinstance(resp, str):
                try:
                    resp = json.loads(resp)
                except Exception:
                    resp = {}
            key = (node, r['model'], task_id)
            if key not in frozen:
                frozen[key] = dict(
                    answer=resp.get('answer', ''),
                    usage=resp.get('usage') or {},
                    latency=resp.get('latency_s', 0),
                )
    return frozen, golds, task_ids


def build_qcl(frozen, golds, task_ids):
    """Build per-(r_model, v_model) end-to-end success + per-(node,model) C/L."""
    # For each task and each (r_model, v_model), try to chain: e1(large) → e2(large) → r(m) → v(m')
    # Task success: v(m')'s value close to gold
    combo_results = {}  # (r_model, v_model, task_id) → dict(ok, tokens, latency)
    for tid in task_ids:
        gold = golds.get(tid)
        if gold is None:
            continue
        e1 = frozen.get(('e1', 'large', tid))
        e2 = frozen.get(('e2', 'large', tid))
        if not e1 or not e2:
            continue
        base_tokens = (e1['usage'].get('total_tokens', 0) +
                       e2['usage'].get('total_tokens', 0))
        base_lat = max(e1['latency'], e2['latency'])

        for rm in R_MODELS:
            r_resp = frozen.get(('r', rm, tid))
            if r_resp is None:
                continue
            r_ok = node_ok('r', r_resp['answer'])
            r_tok = r_resp['usage'].get('total_tokens', 0)
            r_lat = r_resp['latency']

            for vm in V_MODELS:
                v_resp = frozen.get(('v', vm, tid))
                if v_resp is None:
                    continue
                v_val = node_value('v', v_resp['answer'])
                ok = close(v_val, gold)
                v_tok = v_resp['usage'].get('total_tokens', 0)
                v_lat = v_resp['latency']

                total_tok = base_tokens + r_tok + v_tok
                total_lat = base_lat + r_lat + v_lat
                combo_results[(rm, vm, tid)] = dict(
                    ok=bool(ok), tokens=total_tok, latency=total_lat,
                    r_parse=bool(r_ok), v_parse=v_val is not None)

    # Aggregate per (r_model, v_model) combination
    combo_stats = {}
    for rm in R_MODELS:
        for vm in V_MODELS:
            results = [combo_results[(rm, vm, tid)] for tid in task_ids
                       if (rm, vm, tid) in combo_results]
            n = len(results)
            if n < 5:  # need at least 5 tasks
                continue
            combo_stats[(rm, vm)] = dict(
                n=n,
                Q=sum(1 for r in results if r['ok']) / n,
                C=float(np.mean([r['tokens'] for r in results])),
                L=float(np.mean([r['latency'] for r in results])),
                r_parse_rate=sum(1 for r in results if r['r_parse']) / n,
                v_parse_rate=sum(1 for r in results if r['v_parse']) / n,
            )
    return combo_results, combo_stats


# ---- Pareto beam search ----

def dominates(a, b, eps=EPS):
    return (a[0] >= b[0] - eps and a[1] <= b[1] + eps and a[2] <= b[2] + eps and
            (a[0] > b[0] + eps or a[1] < b[1] - eps or a[2] < b[2] - eps))


def pareto_front(candidates):
    """candidates: list of (Q, C, L, label)."""
    front = []
    for c in candidates:
        if not any(dominates(f[:3], c[:3]) for f in front):
            front = [f for f in front if not dominates(c[:3], f[:3])]
            front.append(c)
    return front


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    np.random.seed(SEED)

    frozen, golds, task_ids = load_all()
    print(f'loaded: {len(frozen)} frozen responses, {len(task_ids)} tasks')

    combo_results, combo_stats = build_qcl(frozen, golds, task_ids)

    print('\n=== (r_model, v_model) combination statistics ===')
    print(f"{'r':8s} {'v':8s} {'n':>4s} {'Q':>6s} {'C':>7s} {'L':>6s} {'r_ok':>5s} {'v_ok':>5s}")
    for (rm, vm), s in sorted(combo_stats.items()):
        print(f'{rm:8s} {vm:8s} {s["n"]:4d} {s["Q"]:6.3f} {s["C"]:7.0f} {s["L"]:6.2f} '
              f'{s["r_parse_rate"]:5.2f} {s["v_parse_rate"]:5.2f}')

    # Generate Pareto front
    candidates = [(s['Q'], s['C'], s['L'], (rm, vm))
                  for (rm, vm), s in combo_stats.items()]
    front = pareto_front(candidates)
    print('\n=== Pareto front ===')
    for q, c, l, label in sorted(front, key=lambda x: -x[0]):
        print(f'  r={label[0]:8s} v={label[1]:8s} Q={q:.3f} C={c:.0f} L={l:.2f}')

    # ---- run methods on each task ----
    methods = ['static_frozen', 'frp_static', 'frp_full', 'ws_q_heavy', 'ws_balanced',
               'always_best_q']
    results = defaultdict(dict)
    budget_mult = 1.2

    # Frozen Static: r=medium, v=coder
    static_key = ('medium', 'coder')
    static_tokens_mean = combo_stats.get(static_key, {}).get('C', 2600)

    for tid in task_ids:
        gold = golds.get(tid)
        if gold is None:
            continue

        # --- Static frozen (r=medium, v=coder) ---
        r = combo_results.get((static_key[0], static_key[1], tid))
        if r:
            results['static_frozen'][tid] = dict(ok=r['ok'], tokens=r['tokens'])
        else:
            # no data for this combo+task → use mean
            s = combo_stats.get(static_key, dict(Q=0.15, C=2600))
            results['static_frozen'][tid] = dict(
                ok=np.random.random() < s['Q'], tokens=s['C'])

        # --- FRP-Static: best Q from Pareto front, no feedback ---
        if front:
            best_q = max(front, key=lambda x: x[0])
            rm, vm = best_q[3]
            r = combo_results.get((rm, vm, tid))
            if r:
                results['frp_static'][tid] = dict(ok=r['ok'], tokens=r['tokens'],
                                                  assign=dict(r=rm, v=vm))
            else:
                s = combo_stats.get((rm, vm), dict(Q=0.2, C=2600))
                results['frp_static'][tid] = dict(
                    ok=np.random.random() < s['Q'], tokens=s['C'],
                    assign=dict(r=rm, v=vm))

        # --- FRP-Full: initial Pareto + feedback re-optimization ---
        # Step 1: select initial plan from Pareto (max Q)
        if front:
            initial = max(front, key=lambda x: x[0])
            rm_init, vm_init = initial[3]
        else:
            rm_init, vm_init = 'medium', 'coder'

        # Step 2: execute; if r fails, try next best r; if v fails, try next v
        budget = static_tokens_mean * budget_mult
        tokens_used = 0
        reopts = 0
        final_ok = False

        # Try initial assignment
        r_result = combo_results.get((rm_init, vm_init, tid))
        if r_result:
            final_ok = r_result['ok']
            tokens_used = r_result['tokens']
        else:
            s = combo_stats.get((rm_init, vm_init), dict(Q=0.2, C=2600))
            final_ok = np.random.random() < s['Q']
            tokens_used = s['C']

        # If failed, re-optimize: try alternatives ordered by Q
        if not final_ok and reopts < 2:
            # Sort Pareto front by Q descending, skip the current assignment
            alternatives = sorted(front, key=lambda x: -x[0])
            for alt_q, alt_c, alt_l, (alt_rm, alt_vm) in alternatives:
                if (alt_rm, alt_vm) == (rm_init, vm_init):
                    continue
                if tokens_used + alt_c > budget:
                    continue
                alt_result = combo_results.get((alt_rm, alt_vm, tid))
                if alt_result:
                    tokens_used += alt_result['tokens']
                    if alt_result['ok']:
                        final_ok = True
                        reopts += 1
                        break
                    reopts += 1
                if reopts >= 2:
                    break

        results['frp_full'][tid] = dict(ok=final_ok, tokens=tokens_used, reopts=reopts,
                                         assign=dict(r=rm_init, v=vm_init))

        # --- Weighted Sum variants ---
        for wname, (alpha, beta, gamma) in {
            'ws_q_heavy': (1.0, 0.0001, 0.001),
            'ws_balanced': (1.0, 0.001, 0.01),
        }.items():
            if front:
                best_ws = max(front, key=lambda x: alpha * x[0] - beta * x[1] - gamma * x[2])
                rm, vm = best_ws[3]
                r = combo_results.get((rm, vm, tid))
                if r:
                    results[wname][tid] = dict(ok=r['ok'], tokens=r['tokens'])
                else:
                    s = combo_stats.get((rm, vm), dict(Q=0.2, C=2600))
                    results[wname][tid] = dict(ok=np.random.random() < s['Q'],
                                               tokens=s['C'])

        # --- Always Best Q (oracle-like: always pick highest Q combo) ---
        if combo_stats:
            best_combo = max(combo_stats.items(), key=lambda x: x[1]['Q'])
            rm, vm = best_combo[0]
            r = combo_results.get((rm, vm, tid))
            if r:
                results['always_best_q'][tid] = dict(ok=r['ok'], tokens=r['tokens'])
            else:
                results['always_best_q'][tid] = dict(
                    ok=np.random.random() < best_combo[1]['Q'],
                    tokens=best_combo[1]['C'])

    # ---- analysis ----
    print('\n' + '=' * 70)
    print('FRP-DAG SIMULATION RESULTS (120 tasks, frozen data)')
    print('=' * 70)
    print(f"{'method':22s} {'n':>4s} {'Q':>7s} {'C':>7s} {'reopts':>7s}")
    summary = {}
    for m in methods:
        tasks = results[m]
        n = len(tasks)
        if n == 0:
            continue
        q = sum(1 for t in tasks.values() if t['ok']) / n
        c = np.mean([t['tokens'] for t in tasks.values()])
        ro = np.mean([t.get('reopts', 0) for t in tasks.values()])
        summary[m] = dict(n=n, Q=round(q, 4), C=round(float(c), 1), mean_reopts=round(float(ro), 2))
        print(f'{m:22s} {n:4d} {q:7.4f} {c:7.0f} {ro:7.2f}')

    # paired comparisons
    def paired(meth_a, meth_b, label):
        common = set(results[meth_a]) & set(results[meth_b])
        if not common:
            return
        pairs = [(results[meth_a][t]['ok'], results[meth_b][t]['ok']) for t in common]
        d = np.array([int(b) - int(a) for a, b in pairs], dtype=float)
        rng = np.random.default_rng(20260916)
        means = [rng.choice(d, len(d)).mean() for _ in range(10000)]
        ci = (np.percentile(means, 2.5), np.percentile(means, 97.5))
        b = sum(1 for a, bb in pairs if a and not bb)
        c = sum(1 for a, bb in pairs if not a and bb)
        nd = b + c
        p = 1.0
        if nd > 0:
            p_obs = comb(nd, min(b, c)) * 0.5 ** nd
            p = min(1.0, 2 * sum(comb(nd, k) * 0.5 ** nd for k in range(nd + 1)
                                 if comb(nd, k) * 0.5 ** nd <= p_obs + 1e-12))
        print(f'\n  {label}: ΔQ={d.mean():+.4f} CI=[{ci[0]:+.4f},{ci[1]:+.4f}] '
              f'Help={c} Harm={b} McNemar p={p:.4f}')

    paired('static_frozen', 'frp_full', 'FRP-Full vs Static-Frozen')
    paired('static_frozen', 'frp_static', 'FRP-Static vs Static-Frozen')
    paired('frp_static', 'frp_full', 'FRP-Full vs FRP-Static')

    # Pareto front for visualization
    pareto_viz = [dict(Q=q, C=c, L=l, r_model=rm, v_model=vm)
                  for q, c, l, (rm, vm) in front]
    all_points = [dict(Q=s['Q'], C=s['C'], L=s['L'], r_model=rm, v_model=vm)
                  for (rm, vm), s in combo_stats.items()]

    json.dump(dict(
        summary=summary,
        pareto_front=pareto_viz,
        all_combinations=all_points,
        combo_stats={f'{rm}|{vm}': s for (rm, vm), s in combo_stats.items()},
    ), open(OUT / 'FRP_DAG_RESULTS.json', 'w'), indent=1)
    print('\nresults written to FRP_DAG_RESULTS.json')

    # generate Pareto frontier plot
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fp = '/root/.local/share/fonts/NotoSansCJKsc-Regular.otf'
    font_manager.fontManager.addfont(fp)
    plt.rcParams['font.family'] = font_manager.FontProperties(fname=fp).get_name()

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    # Q vs C
    ax = axes[0]
    for pt in all_points:
        color = 'red' if pt in pareto_viz else 'gray'
        ax.scatter(pt['C'], pt['Q'], c=color, s=80 if pt in pareto_viz else 40,
                   zorder=3 if pt in pareto_viz else 1)
        ax.annotate(f"r={pt['r_model'][:3]}\nv={pt['v_model'][:3]}",
                    (pt['C'], pt['Q']), fontsize=7, ha='center', va='bottom')
    if pareto_viz:
        pf = sorted(pareto_viz, key=lambda x: x['C'])
        ax.plot([p['C'] for p in pf], [p['Q'] for p in pf], 'r--', alpha=0.5, lw=1.5)
    ax.set_xlabel('Cost (tokens)')
    ax.set_ylabel('Quality (task success)')
    ax.set_title('Quality–Cost Pareto Frontier')
    # Q vs L
    ax = axes[1]
    for pt in all_points:
        color = 'red' if pt in pareto_viz else 'gray'
        ax.scatter(pt['L'], pt['Q'], c=color, s=80 if pt in pareto_viz else 40,
                   zorder=3 if pt in pareto_viz else 1)
    if pareto_viz:
        pf = sorted(pareto_viz, key=lambda x: x['L'])
        ax.plot([p['L'] for p in pf], [p['Q'] for p in pf], 'r--', alpha=0.5, lw=1.5)
    ax.set_xlabel('Latency (s, critical path)')
    ax.set_ylabel('Quality (task success)')
    ax.set_title('Quality–Latency Pareto Frontier')
    plt.tight_layout()
    plt.savefig(str(OUT / 'pareto_frontier.pdf'), dpi=200, bbox_inches='tight')
    plt.savefig(str(OUT / 'pareto_frontier.png'), dpi=200, bbox_inches='tight')
    print('pareto_frontier.pdf/png saved')


def main():
    run()


if __name__ == '__main__':
    main()
