"""joint6_t2_replay — Tier-2: real-log calibration + replay of EVSI
information purchase. Zero API calls. Retrospective on H1V7/H1V8
(dev data): calibration/validation, NOT independent evidence.

Replay semantics (honest):
- Decision points: the 12 faulted scenario-repeats (detection=True) of
  H1V7/H1V8 where BOTH arms (accept, closure-repair) were really
  executed with real terminal eU. The 3 no-fault points are trivial
  (all rules accept; zero regret) and excluded from scoring.
- Pre-decision observables: cov (computed on the already-paid shared
  sink), detection, fault id. NO terminal labels.
- Verify action = sink-only re-execution: REAL price from frozen
  ledgers (H1V7 0.0349 eU / H1V8 0.0408 eU; ¥0 cash, 25-31s wall).
  Its observation = a fresh cov sample of the same condition.
- Real fresh samples exist ONLY for paired conditions (6 conditions,
  9 usable faulted points where the partner repeat provides a real y).
  For unpaired points the verify observation is modeled from the
  calibrated channel and reported separately (Tier B); UNKNOWN
  accounting in Tier C.
- Calibration is leave-one-out: every decision point is scored with
  channel/posterior parameters fitted on the other points only.
"""
from __future__ import annotations

import json
import random
import statistics as st

DEC = json.load(open('/root/r3_own_pool/deadline_reward_v1/'
                     'JOINT6_T2_DECISIONS.json'))
THETA = 0.318
VERIFY = {'H1V7': 0.0349, 'H1V8': 0.0408}
PARTNER = {  # real fresh-cov sample availability (paired repeats)
    ('H1V7', 'S1_r1'): 'S1_r2', ('H1V7', 'S1_r2'): 'S1_r1',
    ('H1V7', 'S2_r1'): 'S2_r2', ('H1V7', 'S2_r2'): 'S2_r1',
    ('H1V8', 'Z-b0_r1'): 'Z-b0_r2', ('H1V8', 'Z-b0_r2'): 'Z-b0_r1',
    ('H1V8', 'Z-x0_r1'): 'Z-x0_r2', ('H1V8', 'Z-x0_r2'): 'Z-x0_r1',
    ('H1V8', 'Z-b1_r1'): 'Z-b1_r2', ('H1V8', 'Z-b1_r2'): 'Z-b1_r1',
}
BY_SR = {d['sr']: d for d in DEC}


def fit_channel(train):
    """cov class-conditional Gaussians: REPAIR (delta>0) vs ACCEPT."""
    import math
    rs = [d['cov'] for d in train if d['delta'] > 1e-9]
    as_ = [d['cov'] for d in train if d['delta'] <= 1e-9]
    if len(rs) < 2 or len(as_) < 2:
        return None
    def ms(v):
        m = st.mean(v)
        s = st.stdev(v) if len(v) > 1 else 0.15
        return m, max(s, 0.05)
    mr, sr_ = ms(rs)
    ma, sa = ms(as_)
    pr = len(rs) / len(train)
    def p_rep(covs):
        # log-posterior with n samples
        lr = math.log(pr / (1 - pr))
        for c in covs:
            lr += (-0.5 * ((c - mr) / sr_) ** 2 - math.log(sr_)) \
                  - (-0.5 * ((c - ma) / sa) ** 2 - math.log(sa))
        return 1 / (1 + math.exp(-lr))
    return dict(p_rep=p_rep, mr=mr, sr=sr_, ma=ma, sa=sa,
                within_sd=0.15)


def evsi_verify(chan, cov, c_v, e_delta):
    """Myopic EVSI in eU units: expected reduction of decision regret
    from one fresh cov sample. Decision regret when wrong ~= E|delta|
    (calibrated on train); fresh sample sharpens the posterior via the
    channel (within-condition sd). Compare directly to verify price."""
    import random as _r
    rng = _r.Random(1234)
    tot = 0.0
    B = 200
    for _ in range(B):
        y = min(1.0, max(0.0, cov + rng.gauss(0, chan['within_sd'])))
        p1 = chan['p_rep']([cov])
        p2 = chan['p_rep']([cov, y])
        r_before = min(p1, 1 - p1) * e_delta
        r_after = min(p2, 1 - p2) * e_delta
        tot += r_before - r_after
    return tot / B


def run(method):
    out_rows = []
    for d in DEC:
        if not d['det']:
            continue
        train = [x for x in DEC if x is not d and x['det']]
        chan = fit_channel(train)
        if chan is None:
            out_rows.append(dict(sr=d['sr'], method=method,
                                 note='CAL_FAIL', tier='C'))
            continue
        tier = 'A' if (d['exp'], d['sr']) in PARTNER else 'B'
        c_v = VERIFY[d['exp']]
        p1 = chan['p_rep']([d['cov']])
        act = 'REPAIR' if p1 > 0.5 else 'ACCEPT'
        n_ver = 0
        if method == 'PJ':
            pass
        elif method == 'THRESH':
            act = 'REPAIR' if d['cov'] < THETA else 'ACCEPT'
        elif method == 'PRIOR':
            act = 'REPAIR' if st.mean(
                [1 if x['delta'] > 0 else 0 for x in train]) > 0.5 \
                else 'ACCEPT'
        elif method == 'PJ_MS':
            votes = []
            for b in range(200):
                rng = random.Random(b)
                boot = [rng.choice(train) for _ in range(len(train))]
                cb = fit_channel(boot)
                if cb:
                    votes.append('REPAIR'
                                 if cb['p_rep']([d['cov']]) > 0.5
                                 else 'ACCEPT')
            act = (max(set(votes), key=votes.count) if votes else act)
        elif method in ('LA1', 'ALL', 'COSTH'):
            do_v = False
            if method == 'ALL':
                do_v = True
            elif method == 'COSTH':
                do_v = 0.30 < p1 < 0.70
            else:
                e_delta = st.mean(
                    [abs(x['delta']) for x in train])
                evsi = evsi_verify(chan, d['cov'], c_v, e_delta)
                do_v = evsi > c_v
            if do_v:
                n_ver = 1
                if tier == 'A':
                    y = BY_SR[PARTNER[(d['exp'], d['sr'])]]['cov']  # REAL sample
                else:
                    # modeled fresh sample (Tier B)
                    rng = random.Random(hash(d['sr']) % 2**31)
                    y = min(1.0, max(0.0,
                             d['cov'] + rng.gauss(0, chan['within_sd'])))
                p2 = chan['p_rep']([d['cov'], y])
                act2 = 'REPAIR' if p2 > 0.5 else 'ACCEPT'
                changed = act2 != act
                act = act2
            else:
                changed = False
        obt = (d['eU_repair'] if act == 'REPAIR' else d['eU_accept']) \
            - n_ver * c_v
        best = max(d['eU_repair'], d['eU_accept'])
        out_rows.append(dict(sr=d['sr'], method=method, tier=tier,
                             act=act, cov=d['cov'], p_rep=round(p1, 3),
                             n_verify=n_ver,
                             regret=round(best - obt, 4),
                             decision_err=round(best - (
                                 d['eU_repair'] if act == 'REPAIR'
                                 else d['eU_accept']), 4),
                             note=''))
    return out_rows


def main():
    methods = ('PRIOR', 'THRESH', 'PJ', 'PJ_MS', 'COSTH', 'ALL', 'LA1')
    all_rows = []
    summary = []
    for m in methods:
        rows = run(m)
        all_rows += rows
        fa = [r for r in rows if r.get('tier') in ('A', 'B')
              and 'regret' in r]
        ra = [r['regret'] for r in fa if r['tier'] == 'A']
        rb = [r['regret'] for r in fa if r['tier'] == 'B']
        nv = sum(r.get('n_verify', 0) for r in fa)
        summary.append(dict(
            method=m, n=len(fa),
            mean_regret=round(st.mean([r['regret'] for r in fa]), 4),
            regret_tierA=round(st.mean(ra), 4) if ra else None,
            regret_tierB=round(st.mean(rb), 4) if rb else None,
            n_verify=nv,
            wrong=sum(1 for r in fa if r.get('decision_err', 0) > 1e-9),
            mean_decision_err=round(st.mean(
                [r.get('decision_err', 0) for r in fa]), 4),
            mean_verify_cost=round(st.mean(
                [r.get('regret', 0) - r.get('decision_err', 0)
                 for r in fa]), 4)))
        print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
    json.dump(dict(summary=summary, rows=all_rows,
                   calibration=dict(
                       verify_price_eU=VERIFY,
                       verify_form='sink-only re-execution, ¥0 cash, '
                                   '25-31s wall (real ledger means)',
                       within_cond_cov_sd={k: round(abs(
                           BY_SR[a]['cov'] - BY_SR[b]['cov']) / 2**0.5, 3)
                           for k, (a, b) in
                           [('S1', ('S1_r1', 'S1_r2')),
                            ('S2', ('S2_r1', 'S2_r2')),
                            ('Z-b0', ('Z-b0_r1', 'Z-b0_r2')),
                            ('Z-x0', ('Z-x0_r1', 'Z-x0_r2')),
                            ('Z-b1', ('Z-b1_r1', 'Z-b1_r2'))]},
                       note='retrospective on dev data (H1V7/H1V8); '
                            'LOO channel; tier A = real verify '
                            'observation, tier B = modeled')),
              open('/root/r3_own_pool/deadline_reward_v1/'
                   'JOINT6_T2_REPLAY.json', 'w'),
              ensure_ascii=False, indent=1)
    print('done')


if __name__ == '__main__':
    main()
