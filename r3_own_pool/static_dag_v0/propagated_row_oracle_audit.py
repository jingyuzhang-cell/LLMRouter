"""Zero-call audit of propagated per-model Q, row oracle and headroom.

Every number is recomputed from frozen RESPONSES.jsonl via the frozen loaders
(capability_analysis.load_corpus / preference_router_eval.load_confirmation /
conf500_eval.load_conf500) and the frozen scorer
exec_calc(decode(RSN).expression, parse_facts(EXT).facts) with close tolerance
max(1e-4, 1e-4*|gold|). No model calls. Supersedes any orally quoted value
(e.g. "4.1pp") : cite this file's numbers or nothing.
"""
import hashlib
import json
import subprocess

import numpy as np

from . import core
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .capability_analysis import load_corpus
from .preference_router_eval import load_confirmation
from .conf500_eval import load_conf500
from .confirmation_200 import OUT as CONF1
from .confirmation_500 import OUT as CONF5

OUT = BASE / 'propagated_row_oracle_audit'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def commit():
    return subprocess.run(['git', '-C', str(core.ROOT), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True).stdout.strip()


def summarize(name, rows):
    assert rows, 'empty corpus: ' + name
    q = {m: np.array([r['per_model'][m]['task_q'] for r in rows], dtype=float) for m in POOL}
    M = np.stack([q[m] for m in POOL])
    row_oracle = M.max(axis=0)
    best = max(POOL, key=lambda m: q[m].mean())
    all_correct = int((M.min(axis=0) == 1).sum())
    all_wrong = int((M.max(axis=0) == 0).sum())
    return dict(
        corpus=name, n_tasks=int(M.shape[1]),
        Q_medium=round(float(q['medium'].mean()), 6),
        Q_large=round(float(q['large'].mean()), 6),
        Q_coder=round(float(q['coder'].mean()), 6),
        best_single_model=best,
        Q_best_single=round(float(q[best].mean()), 6),
        Q_row_oracle=round(float(row_oracle.mean()), 6),
        headroom_pp=round(100.0 * (float(row_oracle.mean()) - float(q[best].mean())), 4),
        headroom_vs_large_pp=round(100.0 * (float(row_oracle.mean()) - float(q['large'].mean())), 4),
        all_correct=all_correct, all_wrong=all_wrong,
        disagreement=int(M.shape[1] - all_correct - all_wrong),
        uids=sorted(r['uid'] for r in rows))


def run():
    corpora = [
        ('dev900_propagated', load_corpus(), CPROF, 900),
        ('confirmation200_propagated', load_confirmation(), CONF1, 200),
        ('confirmation500_propagated', load_conf500(), CONF5, 500),
    ]
    parts, uid_seen = [], set()
    for name, rows, folder, policy_n in corpora:
        s = summarize(name, rows)
        s['policy_n'] = policy_n
        s['valid_tasks'] = s['n_tasks']
        s['infrastructure_dropped'] = policy_n - s['n_tasks']
        dup = uid_seen.intersection(s['uids'])
        assert not dup, 'corpora not disjoint: ' + str(len(dup))
        uid_seen.update(s['uids'])
        s['source_files'] = {str(p.relative_to(core.ROOT)): sha(p)
                             for p in [folder / 'RESPONSES.jsonl', folder / ('PROFILE_POLICY.json' if name.startswith('dev900') else ('CONF_POLICY.json' if '200' in name else 'CONF500_POLICY.json'))]}
        s.pop('uids')
        parts.append(s)
    # pooled 1600
    pooled = []
    for name, rows, _, _ in corpora:
        pooled += rows
    total = summarize('pooled1600_propagated', pooled)
    total.pop('uids')
    report = dict(
        generated_unix=__import__('time').time(),
        commit_hash=commit(),
        evidence_tier='audit of frozen outputs; zero model calls; replay-level',
        scoring='exec_calc(v.decode(RSN answer)["expression"], v.parse_facts(EXT answer)); success iff close(val, gold) with tol max(1e-4, 1e-4*|gold|); Q=0 on any parse/exec error',
        protocol='propagated same-model chain EXT(m)->RSN(m); row oracle = per-task max over the 3 diagonal chains; headroom = row oracle - best single model',
        corpora=parts,
        pooled1600=total,
        note='This file is the only citable source for propagated headroom. Any previously quoted oral number (e.g. "4.1pp") is void unless it equals headroom_pp here.')
    OUT.mkdir(exist_ok=True)
    (OUT / 'REASONER_ROW_ORACLE_AUDIT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for s in parts + [total]:
        print(s['corpus'], 'n=%d' % s['n_tasks'],
              'Q_m=%.3f Q_l=%.3f Q_c=%.3f' % (s['Q_medium'], s['Q_large'], s['Q_coder']),
              'row_oracle=%.4f best=%s(%.3f)' % (s['Q_row_oracle'], s['best_single_model'], s['Q_best_single']),
              'headroom=%.2fpp all_wrong=%d' % (s['headroom_pp'], s['all_wrong']))


if __name__ == '__main__':
    run()
