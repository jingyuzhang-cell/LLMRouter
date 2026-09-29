"""Reference Cube (clean) analyzer: independent zero-call recomputation.

Rebuilds per-config (Q_workflow, C_workflow, L_critical_path) directly from
the response ledgers (frozen200 seed + cube_clean own), mirroring the frozen
scoring semantics but sharing no code with the runner's scoring block, so
CUBE_CLEAN.json gets an independent cross-check. Then:

  - exact ND front, 15x15 dominance matrix, exact 3D hypervolume
  - Q/C/L summaries by topology / X family / Z label
  - clean-dedup check (DynamicDAG NONE vs LOCAL_REROUTE identical)
  - anchors: SINGLE (frozen200) and DYNAMICDAG__HETEROGENEOUS vs frozen200
    clean_static (same planned models, same panel; Q/C should match, L uses
    the cube critical-path definition vs legacy serial sum -> documented)
  - partial mode: per-config coverage while the run is still writing

Run: python3 -m collab_scheduler_v1.cube_analyze [--partial]
"""
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
CUBE = ROOT / 'collab_scheduler_v1/cube_clean'
FZ = ROOT / 'static_dag_v0/frozen200'
OUT = ROOT / 'collab_scheduler_v1'

X_MAP = {
    'BALANCED': {'e': 'medium', 'r': 'large', 'v': 'medium'},
    'HETEROGENEOUS': {'e': 'large', 'r': 'medium', 'v': 'coder'},
    'QUALITY': {'e': 'large', 'r': 'large', 'v': 'large'},
}
FAMS = ('BALANCED', 'HETEROGENEOUS', 'QUALITY')
SINGLE_ANCHOR = dict(Q=0.55, C=612.8, L=0.46, n=200, source='frozen200 clean_single')
LEGACY_STATIC_ANCHOR = dict(Q=0.335, C=1485.7, L=4.56, n=200,
                            source='frozen200 clean_static (e:large,r:medium,v:coder)')


def load_ledgers(by_policy='last', prompt_policy='first'):
    """by_policy/prompt_policy in {'first','last'} control which server-session
    record wins for duplicated keys / duplicated (model, prompt) executions
    (the ledger contains an earlier partial session plus the final run).
    Defaults replicate the runner's observable semantics (by_key: own calls
    last; by_mp: first execution of each prompt)."""
    sys.path.insert(0, str(ROOT))
    from static_dag_v0.multidag_dynamic import close, json_value, parse_facts_safe, value_of
    from static_dag_v0 import tool_aware_v1 as v
    import hashlib
    by_key = {}
    for l in (FZ / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        by_key[r['key']] = r
    for l in (CUBE / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        if by_policy == 'first' and r['key'] in by_key:
            continue
        by_key[r['key']] = r
    # prompt-indexed alias target records (delivered, non-injected), so keys the
    # runner served from its by_mp cache (no RESPONSES line written) still resolve.
    # IMPORTANT: restricted to cube_clean's own ledger IN EXECUTION ORDER — the
    # runner's by_mp was populated only by its own new calls (frozen200 seeds
    # entered by_key under their own keys, never by_mp), so including frozen200
    # here would resolve aliases the runner never made.
    sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
    prompt_rec = {}
    for folder in (CUBE,):
        rp = folder / 'RESPONSES.jsonl'
        qp = folder / 'REQUESTS.jsonl'
        if not rp.exists() or not qp.exists():
            continue
        resp = {json.loads(l)['key']: json.loads(l) for l in rp.read_text().splitlines()}
        for l in qp.read_text().splitlines():
            q = json.loads(l)
            r = resp.get(q['key'])
            if r is None or r.get('model') != q['model']:
                continue
            response = r['response']
            if response.get('status') != 'delivered' or response.get('injected_fault'):
                continue
            h = sha(q['prompt']) if 'prompt' in q else q.get('prompt_sha256')
            if h:
                kk = (q['model'], h)
                if prompt_policy == 'last' or kk not in prompt_rec:
                    prompt_rec[kk] = r

    tasks_by_uid = {t['uid']: t for t in
                    json.loads((FZ / 'FROZEN200_POLICY.json').read_text())['tasks']}

    def _model_of(key):
        from collab_scheduler_v1.fault30_protocol import X_MAP
        _, pfx, fam, node, uid = key.split(':')
        xm = X_MAP[fam]
        if node in ('e', 'e1', 'e2'):
            return xm['e']
        if node == 'r':
            return xm['r']
        return xm['v']

    def build_prompt(key):
        """Reconstruct the prompt for a cube execution key (None if upstream
        answers are still missing)."""
        _, pfx, fam, node, uid = key.split(':')
        t = tasks_by_uid.get(uid)
        if t is None:
            return None
        if node == 'e':
            return v.eprompt(dict(question=t['question'],
                                  context=t['ctx_table'] + '\n' + t['ctx_text']))
        if node in ('e1', 'e2'):
            ctx = t['ctx_table'] if node == 'e1' else t['ctx_text']
            return v.eprompt(dict(question=t['question'], context=ctx))
        if node == 'r':
            if pfx == 'SER':
                a = resolve(f'cube:SER:{fam}:e:{uid}')
                f = parse_facts_safe(a)[0] if a is not None else None
                if f is None:
                    return None
            else:
                a1 = resolve(f'cube:PAR:{fam}:e1:{uid}')
                a2 = resolve(f'cube:PAR:{fam}:e2:{uid}')
                if a1 is None or a2 is None:
                    return None
                f = {'facts': parse_facts_safe(a1)[0]['facts'] + parse_facts_safe(a2)[0]['facts']}
            return v.sprompt(dict(question=t['question']), f)
        # v node
        rpfx = 'SER' if pfx == 'SERV' else 'PAR'
        ra = resolve(f'cube:{rpfx}:{fam}:r:{uid}')
        if ra is None:
            return None
        a1 = resolve(f'cube:{rpfx}:{fam}:e:{uid}') if rpfx == 'SER' else \
            resolve(f'cube:{rpfx}:{fam}:e1:{uid}')
        a2 = resolve(f'cube:{rpfx}:{fam}:e:{uid}') if rpfx == 'SER' else \
            resolve(f'cube:{rpfx}:{fam}:e2:{uid}')
        if a1 is None or a2 is None:
            return None
        if rpfx == 'SER':
            facts = parse_facts_safe(a1)[0]['facts']
        else:
            facts = parse_facts_safe(a1)[0]['facts'] + parse_facts_safe(a2)[0]['facts']
        try:
            expr = v.decode(ra)['expression']  # mirrors runner phase-V: decode-only
        except Exception:
            expr = 'UNPARSEABLE'
        from static_dag_v0.multidag_dynamic import VPROMPT
        return VPROMPT.format(q=t['question'], facts=json.dumps(facts), expr=expr)

    memo = {}

    def resolve(key):
        if key in memo:
            return memo[key]
        rec = by_key.get(key)
        if rec is None:
            p = build_prompt(key)
            if p is not None:
                rec = prompt_rec.get((_model_of(key), sha(p)))
        memo[key] = rec['response'].get('answer') if rec else None
        return memo[key]

    def cost(key):
        rec = by_key.get(key)
        if rec is None:
            p = build_prompt(key)
            rec = prompt_rec.get((_model_of(key), sha(p))) if p is not None else None
        return float(rec['response'].get('usage', {}).get('total_tokens') or 0) if rec else None

    def lat(key):
        rec = by_key.get(key)
        if rec is None:
            p = build_prompt(key)
            rec = prompt_rec.get((_model_of(key), sha(p))) if p is not None else None
        return float(rec['response'].get('latency_s') or 0) if rec else None

    return resolve, cost, lat, close, json_value, parse_facts_safe, value_of, v


def evaluate(tasks, coverage_only=False, led=None):
    ans, cost, lat, close, json_value, parse_facts_safe, value_of, v = \
        led if led is not None else load_ledgers()
    rctx = {}
    results = {}
    per_task = {}
    for t in tasks:
        uid, q = t['uid'], t['question']
        for fam in FAMS:
            a = ans(f'cube:SER:{fam}:e:{uid}')
            f_ser = parse_facts_safe(a)[0] if a is not None else None
            rctx[(uid, fam, 'SER')] = f_ser
            a1, a2 = ans(f'cube:PAR:{fam}:e1:{uid}'), ans(f'cube:PAR:{fam}:e2:{uid}')
            f_par = None
            if a1 is not None and a2 is not None:
                f1, _ = parse_facts_safe(a1)
                f2, _ = parse_facts_safe(a2)
                f_par = {'facts': f1['facts'] + f2['facts']}
            rctx[(uid, fam, 'PAR')] = f_par

    for topo in ('SER', 'SERV', 'PARALLELER', 'DYNAMICDAG'):
        for fam in FAMS:
            zs = ['NONE'] if topo != 'DYNAMICDAG' else ['NONE', 'LOCAL_REROUTE']
            for z in zs:
                cid = f'{topo}__{fam}__{z}__FRESH'
                qs, cs, ls, ok_rows = [], [], [], []
                for t in tasks:
                    uid, gold = t['uid'], t['answer']
                    try:
                        if topo == 'SER':
                            val, err = value_of(ans(f'cube:SER:{fam}:r:{uid}'),
                                                rctx[(uid, fam, 'SER')])
                            q = int(not err and close(val, gold))
                            c = cost(f'cube:SER:{fam}:e:{uid}') + cost(f'cube:SER:{fam}:r:{uid}')
                            l = lat(f'cube:SER:{fam}:e:{uid}') + lat(f'cube:SER:{fam}:r:{uid}')
                        elif topo == 'PARALLELER':
                            val, err = value_of(ans(f'cube:PAR:{fam}:r:{uid}'),
                                                rctx[(uid, fam, 'PAR')])
                            q = int(not err and close(val, gold))
                            c = sum(cost(f'cube:PAR:{fam}:{nd}:{uid}') for nd in ('e1', 'e2', 'r'))
                            l = max(lat(f'cube:PAR:{fam}:e1:{uid}'),
                                    lat(f'cube:PAR:{fam}:e2:{uid}')) + lat(f'cube:PAR:{fam}:r:{uid}')
                        else:
                            pfx = 'SER' if topo == 'SERV' else 'PAR'
                            vval = json_value(ans(f'cube:{topo}:{fam}:v:{uid}'))
                            q = int(vval is not None and close(vval, gold))
                            nds = ('e',) if pfx == 'SER' else ('e1', 'e2')
                            c = sum(cost(f'cube:{pfx}:{fam}:{nd}:{uid}') for nd in nds) + \
                                cost(f'cube:{pfx}:{fam}:r:{uid}') + cost(f'cube:{topo}:{fam}:v:{uid}')
                            l = max(lat(f'cube:{pfx}:{fam}:{nd}:{uid}') for nd in nds) + \
                                lat(f'cube:{pfx}:{fam}:r:{uid}') + lat(f'cube:{topo}:{fam}:v:{uid}')
                        if q is None or c is None or l is None:
                            raise KeyError('pending')
                    except Exception:
                        q = c = l = None
                    qs.append(q)
                    cs.append(c)
                    ls.append(l)
                    ok_rows.append(dict(uid=uid, ok=q, c=c, l=l))
                done = [x for x in qs if x is not None]
                results[cid] = dict(
                    Q=round(sum(done) / len(done), 4) if done else None,
                    C=round(sum(x for x in cs if x is not None) / len(done), 1) if done else None,
                    L=round(sum(x for x in ls if x is not None) / len(done), 3) if done else None,
                    n=len(done), n_total=len(qs), per_task=ok_rows)
    return results


def pareto_analysis(results):
    sys.path.insert(0, str(ROOT))
    from sa_pgfs_v1.pareto import hypervolume, non_dominated
    pts = {cid: (r['Q'], r['C'], r['L']) for cid, r in results.items()
           if r['Q'] is not None and r['n'] == r['n_total']}
    anchor = {'SINGLE__QUALITY__RETRY__FRESH': (SINGLE_ANCHOR['Q'], SINGLE_ANCHOR['C'],
                                                 SINGLE_ANCHOR['L'])}
    allpts = {**pts, **anchor}
    Cmax = max(v[1] for v in allpts.values()) * 1.0
    Lmax = max(v[2] for v in allpts.values()) * 1.0
    objs = {cid: (q, 1 - c / Cmax, 1 - l / Lmax) for cid, (q, c, l) in allpts.items()}
    ids = list(objs)
    arr = [objs[i] for i in ids]
    nd = [ids[i] for i in non_dominated(arr)] if arr else []
    hv = hypervolume(arr) if arr else None
    dom = {a: [b for b in ids if b != a and all(x >= y for x, y in zip(objs[a], objs[b]))
               and any(x > y for x, y in zip(objs[a], objs[b]))] for a in ids}
    return dict(objectives=objs, front=nd, hv=float(hv) if hv else None,
                normalization=dict(Cmax=Cmax, Lmax=Lmax,
                                   note='(Q, 1-C/Cmax, 1-L/Lmax) maximization, ref origin'),
                dominates=dom)


def run():
    partial = '--partial' in sys.argv
    tasks = json.loads((FZ / 'FROZEN200_POLICY.json').read_text())['tasks']
    results = evaluate(tasks)
    complete = {k: {kk: vv for kk, vv in v.items() if kk != 'per_task'}
                for k, v in results.items() if v['n'] == v['n_total']}
    out = dict(complete=complete, partial={k: dict(n=v['n'], n_total=v['n_total'])
                                           for k, v in results.items() if v['n'] < v['n_total']})
    if complete:
        pa = pareto_analysis(results)
        out['pareto'] = {k: v for k, v in pa.items() if k != 'dominates'}
        out['dominance_matrix'] = pa['dominates']
        # dedup check
        dd = {}
        for fam in FAMS:
            a = results.get(f'DYNAMICDAG__{fam}__NONE__FRESH', {})
            b = results.get(f'DYNAMICDAG__{fam}__LOCAL_REROUTE__FRESH', {})
            dd[fam] = (a.get('Q') == b.get('Q')) and (a.get('C') == b.get('C')) \
                and (a.get('L') == b.get('L'))
        out['clean_dedup_check'] = dd
        # anchors
        h = results.get('DYNAMICDAG__HETEROGENEOUS__NONE__FRESH', {})
        out['anchors'] = dict(
            single=SINGLE_ANCHOR,
            dyn_het_vs_legacy_static=dict(
                measured={k: h.get(k) for k in ('Q', 'C', 'L', 'n')},
                legacy=LEGACY_STATIC_ANCHOR,
                expect='Q/C should match (same models+panel+prompts); L smaller by '
                       'construction (critical path vs legacy serial sum)') if h else None)
    # cross-check vs runner's own CUBE_CLEAN.json when present
    cc = CUBE / 'CUBE_CLEAN.json'
    if cc.exists():
        theirs = json.loads(cc.read_text())['results']
        diff = {}
        for cid, mine in complete.items():
            th = theirs.get(cid)
            if th and (abs(th['Q'] - mine['Q']) > 1e-9 or abs(th['C'] - mine['C']) > 0.05
                       or abs(th['L'] - mine['L']) > 1e-3):
                diff[cid] = dict(mine={k: mine[k] for k in ('Q', 'C', 'L', 'n')}, theirs=th)
        out['cross_check_vs_CUBE_CLEAN'] = dict(n_compared=len(complete), mismatches=diff)
    (OUT / 'CUBE_CLEAN_ANALYSIS.json').write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != 'dominance_matrix'}, indent=1)[:4000])
    if not partial:
        print('\n--- per-config ---')
        for cid, r in complete.items():
            print(f"{cid:42s} Q={r['Q']} C={r['C']} L={r['L']} n={r['n']}")
        if 'pareto' in out:
            print('front:', out['pareto']['front'], 'HV=', out['pareto']['hv'])


if __name__ == '__main__':
    run()
