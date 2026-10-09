"""Offline error audit of the fixed-DAG incremental cost predictor (DIAGNOSTIC).

Reads ONLY frozen copies under copy_inputs/ (no active files, no GPU, no
production-code changes). Imports the production predictor read-only:

    CacheIdentityPredictor (review/track_b.py)
      identity: e=(node,model); r=(m_e1,m_e2,m_r); v=+Z-context in fault30
      est_new_tokens = NODE_EST_TOKENS x model-multiplier for 'new' nodes
                       + RECOVERY_COST x RECOVERY_FIRE_E[state][Z]

Per cell (chronological), replays the predictor exactly as the searcher would
have used it (predict -> register under its clean/fault30 scope semantics) and
compares against ledger actuals from the copy:

  per-node hit/new  vs TRAJECTORY alias_of ground truth
                     (overall + 'model changed vs all earlier executions of the
                      same (scope,uid,node)' sub-bucket)
  cell new tokens   vs EVALUATIONS/SCENARIOS search_spend.new_tokens (ledger)
  cell new requests vs search_spend.new_requests (node-derived prediction)
  deployment C      vs evaluator objectives C — reported SEPARATELY, never
                     merged with search physical spend

Buckets: cold(S1) / cache-reuse(S4) / LOCAL(S2) / FULL(S3) / campaign-mixed.
An oracle-scope variant (same identity rules, ONE shared scope per run — the
fullval runs actually share one underlying cache scope) is replayed alongside
to attribute error between identity rules and scope-split conservatism.

Coverage = per cell, whether predicted est >= actual (upper) / <= actual
(lower). Errors are signed (prediction - actual).
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
JS = ROOT / 'collab_scheduler_v1/joint_search_v1'
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from collab_scheduler_v1.joint_search_v1.review.track_b import (  # noqa
    CacheIdentityPredictor, NODE_EST_TOKENS, MODEL_MULTIPLIER,
    RECOVERY_COST, RECOVERY_FIRE_E)
from collab_scheduler_v1.joint_search_v1.evaluator import NODES  # noqa

SOURCES = {
    'fullval_runs_fullval_authorized_1h_01': dict(
        kind='fullval', manifest='FULLVAL_AUTHORIZED_1H.json',
        version='authorized_fullval_1h_v1 (old eval-derivation gold; '
                'cost audit unaffected by gold version)'),
    'fullval_runs_fullval_cont1_01': dict(
        kind='fullval', manifest='FULLVAL_CONTINUATION_1.json',
        version='fullval_continuation_1_v1'),
    'formal_campaign_proposed_state_incremental_20261009': dict(
        kind='campaign', manifest='FORMAL_LAUNCH_V1.json',
        version='formal_launch_v1 (old gold; DIAGNOSTIC; killed mid 9th cell; '
                'the 8 completed cells are used; the interrupted cell has no '
                'evaluation record and is excluded — its spend lives in the '
                'campaign journal, not in these copies)'),
    'formal_campaign_v2_scalarized_bo_20261009': dict(
        kind='campaign', manifest='FORMAL_LAUNCH_V2.json',
        version='formal_launch_v2 (GOLD_CONTRACT_V1)'),
}
X_FULLVAL = ('large', 'large', 'medium', 'coder')
SCENE_Z = {'S1': 'NONE', 'S4': 'NONE', 'S2': 'LOCAL', 'S3': 'FULL'}
SCENE_STATE = {'S1': 'clean', 'S4': 'clean', 'S2': 'fault30', 'S3': 'fault30'}
BUCKET_OF = {'S1': 'cold_S1', 'S4': 'cache_reuse_S4', 'S2': 'LOCAL_S2',
             'S3': 'FULL_S3', 'campaign-mixed': 'campaign_mixed'}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def parse_traj(d):
    """planned[(scope,cid_full,uid,node)] = hit/new + executed model;
    recovery list for non-base calls (chronological).

    event_id = scope:cid:key where key = f30:topo:fam:node:uid (5 fields) and
    cid may itself contain colons in the fullval lineage ('S1:<config>'). Parse
    positionally from the tail; cid_full joins everything between scope and key."""
    planned, recovery = {}, []
    for line in (d / 'TRAJECTORY.jsonl').read_text().splitlines():
        rec = json.loads(line)
        f = rec['event_id'].split(':')
        # planned key: f30:topo:fam:node:uid  (tail-5 == 'f30')
        # recovery key: f30:topo:fam:node:kind:uid (tail-6 == 'f30')
        if len(f) >= 6 and f[-5] == 'f30':
            scope, cid_full = f[0], ':'.join(f[1:-5])
            fam, node, uid = f[-3], f[-2], f[-1]
            if fam == 'base':
                k = (scope, cid_full, uid, node)
                if k not in planned:
                    planned[k] = dict(hit='alias_of' in rec, model=rec.get('model'))
                continue
            recovery.append(dict(scope=scope, cid=cid_full))
        elif len(f) >= 7 and f[-6] == 'f30':
            recovery.append(dict(scope=f[0], cid=':'.join(f[1:-6])))
    return planned, recovery


def cells_of(meta, d, name):
    """Cells carry the TRAJECTORY key mapping: fullval executors override the
    scope ('fullval_shared_underlying' / 'fullval_cont1') and prefix cid with
    the scenario; campaign cells use scope=state, cid=config id."""
    out = []
    if meta['kind'] == 'fullval':
        traj_scope = 'fullval_shared_underlying' if 'authorized_1h' in name else 'fullval_cont1'
        for line in (d / 'SCENARIOS.jsonl').read_text().splitlines():
            s = json.loads(line)
            scene = s['scenario']
            cid = '__'.join((*X_FULLVAL, SCENE_Z[scene]))
            out.append(dict(cid=cid, state=SCENE_STATE[scene],
                            bucket=BUCKET_OF[scene],
                            traj_scope=traj_scope, traj_cid=f'{scene}:{cid}',
                            uids=[s['uid']], spend=s['result']['search_spend'],
                            depC=s['result']['objectives']['C']))
    else:
        for line in (d / 'EVALUATIONS.jsonl').read_text().splitlines():
            e = json.loads(line)
            out.append(dict(cid=e['config_id'], state=e['state'],
                            bucket='campaign_mixed',
                            traj_scope=e['state'], traj_cid=e['config_id'],
                            uids=[t['uid'] for t in e['tasks']],
                            spend=e['search_spend'],
                            depC=e['objectives']['C']))
    return out


def cfg_of(cid):
    return dict(id=cid, X=dict(zip(NODES, cid.split('__')[:4])),
                Z=cid.rsplit('__', 1)[1])


class OracleScopePredictor:
    """Same identity rules, ONE shared scope per run (the fullval runs share a
    single underlying cache scope across S1..S3). Audit-local only."""

    def __init__(self, uids):
        self.sigs = {u: dict(e=set(), r=set(), v=set()) for u in uids}

    @staticmethod
    def _vsig(cfg, state):
        x = cfg['X']
        sig = (x['e1'], x['e2'], x['r'], x['v'])
        return sig + (('z', cfg['Z']),) if state == 'fault30' else sig

    def predict(self, cfg, state):
        x = cfg['X']
        per, est = {}, 0.0
        for u, s in self.sigs.items():
            nodes = {}
            for nd in ('e1', 'e2'):
                nodes[nd] = 'hit' if (nd, x[nd]) in s['e'] else 'new'
            nodes['r'] = 'hit' if (x['e1'], x['e2'], x['r']) in s['r'] else 'new'
            nodes['v'] = 'hit' if self._vsig(cfg, state) in s['v'] else 'new'
            per[u] = nodes
            est += sum(NODE_EST_TOKENS[nd] * MODEL_MULTIPLIER[x[nd]]
                       for nd in NODES if nodes[nd] == 'new')
        est /= max(1, len(self.sigs))
        est += RECOVERY_COST.get(cfg['Z'], 0) * RECOVERY_FIRE_E[state][cfg['Z']]
        return dict(per_task=per, est_new_tokens=float(max(est, 100.0)))

    def register(self, cfg, state):
        x = cfg['X']
        for u, s in self.sigs.items():
            s['e'].add(('e1', x['e1']))
            s['e'].add(('e2', x['e2']))
            s['r'].add((x['e1'], x['e2'], x['r']))
            s['v'].add(self._vsig(cfg, state))


def stats(errs, actuals=None):
    if not errs:
        return dict(n=0)
    out = dict(n=len(errs),
               signed_mean=round(sum(errs) / len(errs), 1),
               mae=round(sum(abs(e) for e in errs) / len(errs), 1),
               upper_cover=round(sum(1 for e in errs if e >= 0) / len(errs), 3),
               lower_cover=round(sum(1 for e in errs if e <= 0) / len(errs), 3))
    if actuals:
        scale = sum(actuals) / len(actuals)
        out['relative_mae'] = round(out['mae'] / scale, 3) if scale else None
        out['actual_mean'] = round(scale, 1)
    return out


def main():
    audit = dict(
        role='offline incremental-cost predictor error audit',
        status='DIAGNOSTIC EVIDENCE — not performance comparison',
        gpu_calls=0, inputs={},
        conventions=dict(
            error_sign='unified: error = prediction - actual (negative = underestimate)',
            coverage_upper='fraction of cells with actual <= prediction '
                           '(prediction treated as candidate upper bound)',
            coverage_lower='fraction of cells with actual >= prediction',
            token_scale='the predictor outputs a PER-TASK MEAN; ledger new_tokens '
                        'is the CELL TOTAL over n tasks. Both scales are reported: '
                        'per_task (pred vs actual/n) and cell_total (pred*n vs '
                        'actual). v1 of this audit compared per-task prediction '
                        'against cell-total actual — an 8x scale artifact that '
                        'masqueraded as systematic underestimation; corrected here.',
            separation='deployment C and search physical spend NEVER merged',
            oracle='same identity rules, single shared scope per run — isolates '
                   'scope-split conservatism from identity-rule error'),
        sources_note='frozen copies only; random cell (no terminal record) and '
                     'all running sessions excluded')
    all_node_rows = []
    for name, meta in SOURCES.items():
        d = HERE / 'copy_inputs' / name
        uids = sorted({json.loads(l)['key'].split(':')[-1]
                       for l in (d / 'WORKFLOW.jsonl').read_text().splitlines()})
        pred = CacheIdentityPredictor(uids)
        oracle = OracleScopePredictor(uids)
        planned, recovery = parse_traj(d)
        cells = cells_of(meta, d, name)
        seen_models = {}   # (scope,uid,node) -> set(models executed before)
        per_cell, node_rows, mismatches = [], [], []
        def cell_est(flags_by_uid, cfg, state):
            est = sum(sum(NODE_EST_TOKENS[nd] * MODEL_MULTIPLIER[cfg['X'][nd]]
                          for nd in NODES if flags[nd] == 'new')
                      for flags in flags_by_uid.values()) / max(1, len(flags_by_uid))
            return est + RECOVERY_COST.get(cfg['Z'], 0) * RECOVERY_FIRE_E[state][cfg['Z']]

        def register_uids(sigs, cfg, state, uids):
            x = cfg['X']
            for u in uids:
                sg = sigs[state][u] if 'clean' in sigs else sigs[u]  # predictor is [state][uid]; oracle is [uid]
                sg['e'].add(('e1', x['e1']))
                sg['e'].add(('e2', x['e2']))
                sg['r'].add((x['e1'], x['e2'], x['r']))
                sg['v'].add((x['e1'], x['e2'], x['r'], x['v'],
                             (('z', cfg['Z']),) if state == 'fault30' else ()))

        for c in cells:
            cfg = cfg_of(c['cid'])
            p = pred.predict(cfg, c['state'])
            o = oracle.predict(cfg, c['state'])
            # fullval cells are SINGLE-TASK: the production predictor's
            # panel-wide register/average does not apply; use the cell's own
            # uids for both the estimate and the registration (searcher cells
            # cover the whole panel and are unaffected by this adaptation).
            if meta['kind'] == 'fullval':
                p_est = max(100.0, cell_est({u: p['per_task'][u] for u in c['uids']},
                                            cfg, c['state']))
                o_est = max(100.0, cell_est({u: o['per_task'][u] for u in c['uids']},
                                            cfg, c['state']))
            else:
                p_est, o_est = p['est_new_tokens'], o['est_new_tokens']
            for uid in c['uids']:
                for nd in NODES:
                    rec = planned.get((c['traj_scope'], c['traj_cid'], uid, nd))
                    if rec is None:
                        continue
                    act = 'hit' if rec['hit'] else 'new'
                    key = (c['traj_scope'], uid, nd)
                    model_changed = rec['model'] not in seen_models.get(key, set())
                    for tag, pv in (('predictor', p['per_task'][uid][nd]),
                                    ('oracle', o['per_task'][uid][nd])):
                        row = dict(
                            variant=tag, node=nd, bucket=c['bucket'],
                            cell=f'{c["traj_cid"]}@{c["traj_scope"]}',
                            uid=uid, model=rec['model'],
                            model_changed_vs_prior=model_changed,
                            pred=pv, act=act, ok=(pv == act))
                        node_rows.append(row)
                        if tag == 'predictor' and not row['ok']:
                            mismatches.append(row)
                    seen_models.setdefault(key, set()).add(rec['model'])
            act_tok = c['spend']['new_tokens']
            act_req = c['spend']['new_requests']
            n_tasks = max(1, len(c['uids']))
            pred_nodes = sum(1 for uid in c['uids'] for nd in NODES
                             if p['per_task'][uid][nd] == 'new')
            oracle_nodes = sum(1 for uid in c['uids'] for nd in NODES
                               if o['per_task'][uid][nd] == 'new')
            n_rec = sum(1 for r in recovery
                        if r['scope'] == c['state'] and r['cid'] == c['cid'])
            per_cell.append(dict(
                bucket=c['bucket'], cid=c['cid'], state=c['state'], n_tasks=n_tasks,
                pred_new_tokens_per_task=round(p_est, 1),
                oracle_new_tokens_per_task=round(o_est, 1),
                actual_new_tokens_per_task=round(act_tok / n_tasks, 1),
                actual_new_tokens_cell_total=act_tok,
                # scale-matched errors: per-task basis AND cell-total basis
                token_err_per_task=round(p_est - act_tok / n_tasks, 1),
                oracle_token_err_per_task=round(o_est - act_tok / n_tasks, 1),
                token_err_cell_total=round(p_est * n_tasks - act_tok, 1),
                pred_new_nodes=pred_nodes, oracle_new_nodes=oracle_nodes,
                actual_new_requests=act_req,
                request_err=pred_nodes - act_req,
                recovery_calls_actual=n_rec,
                deployment_C_actual=round(c['depC'], 1),
                deployment_C_static_est=round(
                    sum(NODE_EST_TOKENS[nd] * MODEL_MULTIPLIER[cfg['X'][nd]]
                        for nd in NODES) + RECOVERY_COST.get(cfg['Z'], 0), 1)))
            register_uids(pred.sigs, cfg, c['state'], c['uids'])
            register_uids(oracle.sigs, cfg, c['state'], c['uids'])
            if meta['kind'] != 'fullval':  # panel-wide semantics preserved
                pass
        buckets = {}
        for b in sorted({c['bucket'] for c in per_cell}):
            rows = [c for c in per_cell if c['bucket'] == b]
            buckets[b] = dict(
                cells=len(rows),
                token_err_per_task=stats([c['token_err_per_task'] for c in rows],
                    [c['actual_new_tokens_per_task'] for c in rows]),
                oracle_token_err_per_task=stats(
                    [c['oracle_token_err_per_task'] for c in rows]),
                token_err_cell_total=stats([c['token_err_cell_total'] for c in rows]),
                request_err=stats([float(c['request_err']) for c in rows],
                    [float(c['actual_new_requests']) for c in rows]))
        nacc = {}
        for variant in ('predictor', 'oracle'):
            vr = [r for r in node_rows if r['variant'] == variant]
            for scope_tag, sel in (('all', vr),
                                   ('model_changed', [r for r in vr if r['model_changed_vs_prior']]),
                                   ('model_same', [r for r in vr if not r['model_changed_vs_prior']])):
                nacc[f'{variant}.{scope_tag}'] = dict(
                    n=len(sel), accuracy=round(
                        sum(1 for r in sel if r['ok']) / len(sel), 3) if sel else None,
                    false_hit_rate=round(
                        sum(1 for r in sel if r['pred'] == 'hit' and r['act'] == 'new')
                        / len(sel), 3) if sel else None)
        audit['inputs'][name] = dict(
            version=meta['version'], kind=meta['kind'],
            manifest_sha256=sha(JS / meta['manifest']),
            n_cells=len(per_cell),
            predictor_mismatches=mismatches,
            cell_totals=dict(
                actual_new_tokens=sum(c['actual_new_tokens_cell_total'] for c in per_cell),
                actual_new_requests=sum(c['actual_new_requests'] for c in per_cell),
                deployment_C_sum=round(sum(c['deployment_C_actual'] for c in per_cell), 1)),
            buckets=buckets, node_accuracy=nacc,
            cells=per_cell)
        all_node_rows.extend(r for r in node_rows if r['variant'] == 'predictor')
    # cross-source node accuracy
    audit['node_level_predictor'] = dict(
        n=len(all_node_rows),
        accuracy=round(sum(1 for r in all_node_rows if r['ok']) / len(all_node_rows), 3),
        false_hit_rate=round(
            sum(1 for r in all_node_rows if r['pred'] == 'hit' and r['act'] == 'new')
            / len(all_node_rows), 3),
        note='false_hit = predicted cache hit but ledger shows a new request — '
             'the unsafe direction for budget; must be 0 for precision-1.0 claim')
    (HERE / 'PREDICTOR_ERROR_AUDIT.json').write_text(json.dumps(audit, indent=1))
    # console digest
    for name, s in audit['inputs'].items():
        print(f"== {name} ({s['n_cells']} cells) ==")
        for b, bs in s['buckets'].items():
            print(f"  {b:16} tok_err{bs["token_err_per_task"]} req_err{bs["request_err"]}")
        print('  node acc:', {k: v for k, v in s['node_accuracy'].items()
                               if k.startswith('predictor')})
    print('cross-source predictor node accuracy:', audit['node_level_predictor'])
    print('audit written:', HERE / 'PREDICTOR_ERROR_AUDIT.json')


if __name__ == '__main__':
    main()
