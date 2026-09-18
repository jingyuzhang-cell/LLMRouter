"""Recoverable vs unrecoverable cause analysis over the 116 criterion-pure true failures
(original final answer verifiably wrong). Descriptive only: no classifier is trained on 8
positive samples. Reads frozen audit outputs; zero model calls."""
import json
from collections import Counter, defaultdict
from .recovery_matrix_v2_full_prep import OUT

RECOVERY = ['retry_same', 'switch_model', 'evidence_retrieval', 'local_decompose']
LABELS = ['evidence', 'reasoning', 'structural']

def run():
    full = json.loads((OUT / 'FULL_RESULTS.json').read_text())['results']
    orig = {r['nid']: r for r in json.loads((OUT / 'ORIG_CORRECTNESS.json').read_text())}
    clean = [r for r in full if not orig[r['node_id']]['orig_correct']]
    rows = []
    for r in clean:
        nid = r['node_id']; o = orig[nid]
        er = r['actions']['evidence_retrieval']; dc = r['actions']['local_decompose']
        rt = r['actions']['retry_same']
        succ = {a: r['actions'][a]['success'] for a in RECOVERY}
        recoverable = any(succ.values())
        rows.append(dict(
            nid=nid, label=r['label'], domain=r['domain'], task_uid=r['task_uid'],
            recoverable=recoverable, n_recovering_actions=sum(succ.values()),
            ER_before=er['ER_before'], ER_after=er['ER_after'], delta_ER=er['delta_ER'],
            n_facts_before=len(er['facts_before']['facts']),
            n_facts_after=len(er['facts_after']['facts']),
            facts_changed_by_retrieval=er['facts_after'] != er['facts_before'],
            decompose_executed=dc.get('decompose_executed'), D_before=dc['D_before'], D_after=dc['D_after'],
            orig_exec_err=o['orig_exec_err'], orig_value=o['orig_value'],
            retry_exec_err=rt.get('executor_error'), retry_expression=rt.get('expression'),
            gold=json.loads((OUT / 'offline' / (__import__('hashlib').sha256(nid.encode()).hexdigest() + '.json')).read_text())['gold_answer']))
    # error magnitude of the original answer
    for x in rows:
        try:
            x['orig_rel_err'] = abs(x['orig_value'] - x['gold']) / abs(x['gold']) if x['orig_value'] is not None else None
        except Exception:
            x['orig_rel_err'] = None
    rec = [x for x in rows if x['recoverable']]
    unrec = [x for x in rows if not x['recoverable']]

    def feat(fn, agg):
        return (agg([fn(x) for x in rec if fn(x) is not None]) if rec else None,
                agg([fn(x) for x in unrec if fn(x) is not None]) if unrec else None)

    # Unrecoverable reason categories (primary, mutually exclusive priority order).
    # orig_value is None <=> the original reasoning answer failed decode/execution;
    # orig_value not None <=> original expression executed but produced a wrong value.
    cats = defaultdict(list)
    for x in unrec:
        if x['orig_value'] is None:
            cats['original_unexecutable'].append(x)
        elif x['ER_before'] < 1:
            cats['executed_wrong_value_with_evidence_gap'].append(x)
        else:
            cats['executed_wrong_value_full_evidence'].append(x)
    # cross-cutting: did retrieval add evidence and still fail; did decompose execute and fail
    cross = dict(
        retrieval_added_evidence_still_failed=sum(1 for x in unrec if x['delta_ER'] > 0),
        retrieval_added_nothing=sum(1 for x in unrec if x['delta_ER'] == 0),
        facts_unchanged_by_retrieval=sum(1 for x in unrec if not x['facts_changed_by_retrieval']),
        decompose_executed_still_failed=sum(1 for x in unrec if x['decompose_executed']),
        decompose_never_executed=sum(1 for x in unrec if not x['decompose_executed']),
        retry_expression_executable=sum(1 for x in unrec if x['retry_exec_err'] is None),
    )
    rep = dict(
        n=len(rows), n_recoverable=len(rec), n_unrecoverable=len(unrec),
        by_label={l: dict(recoverable=sum(x['recoverable'] for x in rows if x['label'] == l),
                          total=sum(x['label'] == l for x in rows)) for l in LABELS},
        features=dict(
            ER_before_mean=feat(lambda x: x['ER_before'], lambda v: round(sum(v) / len(v), 3)),
            delta_ER_gt0_rate=(sum(x['delta_ER'] > 0 for x in rec) / len(rec),
                               sum(x['delta_ER'] > 0 for x in unrec) / len(unrec)),
            facts_changed_rate=(sum(x['facts_changed_by_retrieval'] for x in rec) / len(rec),
                                sum(x['facts_changed_by_retrieval'] for x in unrec) / len(unrec)),
            decompose_executed_rate=(sum(bool(x['decompose_executed']) for x in rec) / len(rec),
                                     sum(bool(x['decompose_executed']) for x in unrec) / len(unrec)),
            orig_executed_rate=(sum(x['orig_value'] is not None for x in rec) / len(rec),
                                sum(x['orig_value'] is not None for x in unrec) / len(unrec)),
            n_facts_before_mean=feat(lambda x: x['n_facts_before'], lambda v: round(sum(v) / len(v), 2)),
            orig_rel_err_median=feat(lambda x: x['orig_rel_err'], lambda v: round(sorted(v)[len(v) // 2], 3)),
        ),
        unrecoverable_primary_causes={k: len(v) for k, v in sorted(cats.items(), key=lambda kv: -len(kv[1]))},
        unrecoverable_cross={k: v for k, v in cross.items()},
        recoverable_detail=[dict(nid=x['nid'], label=x['label'], domain=x['domain'],
                                 recovering=[a for a in RECOVERY if None], ER_before=x['ER_before'], delta_ER=x['delta_ER'],
                                 decompose_executed=x['decompose_executed'], orig_exec_err=x['orig_exec_err'])
                            for x in rec],
        per_node=rows)
    # fill which actions recovered
    succ_map = {r['node_id']: {a: r['actions'][a]['success'] for a in RECOVERY} for r in clean}
    for d in rep['recoverable_detail']:
        d['recovering'] = [a for a in RECOVERY if succ_map[d['nid']][a]]
    (OUT / 'RECOVERY_CAUSES.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return rep

if __name__ == '__main__':
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != 'per_node'}, ensure_ascii=False, indent=2))
