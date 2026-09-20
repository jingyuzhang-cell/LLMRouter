"""Controlled fault propagation analysis (offline). Per fault type: baseline wrong rate,
recovery rate per arm (paired bootstrap over tasks), successor correction rate, token and
latency deltas, plus the C0 control sanity check (arms must be equal without faults)."""
import json
import random
from collections import defaultdict

from .recovery_matrix_v2_devset import BASE
from .controlled_fault_propagation import OUT, SEED

B = 5000

def run():
    raw = json.loads((OUT / 'RAW_RESULTS.json').read_text())
    rows = raw['results']
    # derive baseline-wrong: success==0, or success==1 via fallback correction
    for r in rows:
        r['baseline_wrong'] = (r['success'] == 0) or (r['recovered_or_corrected'] == 1)
    by = defaultdict(dict)
    for r in rows: by[(r['uid'], r['fault'])][r['arm']] = r
    pairs = [(v['static'], v['dynamic']) for v in by.values() if 'static' in v and 'dynamic' in v]
    rng = random.Random(SEED)
    def paired_boot(stat_fn, universe):
        out = []
        for _ in range(B):
            sample = stat_fn(*[universe[rng.randrange(len(universe))] for _ in universe])
            out.append(stat_fn(*sample) if False else sample)
        return out
    # per-fault stats
    rep = dict(seed=SEED, n_pairs=len(pairs), per_fault={}, control_check={}, overall={})
    for ft in ['C0', 'T1', 'T2', 'T3']:
        sub = [(s, d) for (s, d) in pairs if s['fault'] == ft]
        if not sub: continue
        n = len(sub)
        def rates(pairs_):
            bs = sum(s['baseline_wrong'] for s, d in pairs_)
            rs = sum(d['success'] and s['baseline_wrong'] for s, d in pairs_)
            rd = sum(d['success'] and s['baseline_wrong'] for s, d in pairs_)
            r_static = (sum(d['success'] for s, d in pairs_ if s['baseline_wrong'])) / max(1, bs)
            r_dyn = r_static  # placeholder replaced below
            return bs, rs, rd
        base_wrong = sum(1 for s, d in sub if s['baseline_wrong'])
        rec_s = sum(1 for s, d in sub if s['baseline_wrong'] and d['success'])
        rec_d = sum(1 for s, d in sub if d['baseline_wrong'] and d['success'])
        help_ = sum(1 for s, d in sub if s['success'] == 0 and d['success'] == 1)
        harm = sum(1 for s, d in sub if s['success'] == 1 and d['success'] == 0)
        dc = sum(d['used'] - s['used'] for s, d in sub) / n
        dl = sum(d['lat'] - s['lat'] for s, d in sub) / n
        # bootstrap CI for recovery-rate difference on baseline-wrong instances
        idx = [i for i, (s, d) in enumerate(sub) if s['baseline_wrong']]
        diffs = []
        for _ in range(B if idx else 1):
            sample = [sub[rng.randrange(len(sub))] for _ in idx] if idx else []
            if not sample: continue
            rs = sum(d['success'] for s, d in sample if s['baseline_wrong']) / max(1, sum(1 for s, d in sample if s['baseline_wrong']))
            rd = sum(d['success'] for s, d in sample if d['baseline_wrong']) / max(1, sum(1 for s, d in sample if d['baseline_wrong']))
            diffs.append(rd - rs)
        diffs.sort()
        ci = [round(diffs[int(0.025 * len(diffs))], 4), round(diffs[int(0.975 * len(diffs)) - 1], 4)] if diffs else None
        rep['per_fault'][ft] = dict(
            n=n, baseline_wrong=base_wrong,
            static_recovered=rec_s, static_recovery_rate=round(rec_s / max(1, base_wrong), 4),
            dynamic_recovered=rec_d, dynamic_recovery_rate=round(rec_d / max(1, base_wrong), 4),
            recovery_diff_ci=(ci if base_wrong else None),
            help=help_, harm=harm,
            delta_C_mean=round(dc, 1), delta_L_mean=round(dl, 3),
            static_tokens=round(sum(s['used'] for s, d in sub) / n, 1),
            dynamic_tokens=round(sum(d['used'] for d, s in zip([d for s, d in sub], [s for s, d in sub])) / n, 1))
    # control sanity
    c0 = [(s, d) for (s, d) in pairs if s['fault'] == 'C0']
    rep['control_check'] = dict(n=len(c0),
        arms_equal=sum(1 for s, d in c0 if s['success'] == d['success']),
        static_tokens=round(sum(s['used'] for s, d in c0) / max(1, len(c0)), 1))
    # overall (faulted contexts only)
    faulted = [(s, d) for (s, d) in pairs if s['fault'] != 'C0']
    rep['overall'] = dict(
        n=len(faulted),
        static_recovery=round(sum(1 for s, d in faulted if s['baseline_wrong'] and d['success']) / max(1, sum(1 for s, d in faulted if s['baseline_wrong'])), 4),
        dynamic_recovery=round(sum(1 for s, d in faulted if d['baseline_wrong'] and d['success']) / max(1, sum(1 for s, d in faulted if d['baseline_wrong'])), 4),
        help=sum(1 for s, d in faulted if s['success'] == 0 and d['success'] == 1),
        harm=sum(1 for s, d in faulted if s['success'] == 1 and d['success'] == 0),
        mean_dC=round(sum(d['used'] - s['used'] for s, d in faulted) / len(faulted), 1),
        mean_dL=round(sum(d['lat'] - s['lat'] for s, d in faulted) / len(faulted), 3))
    (OUT / 'CFP_ANALYSIS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
