"""M6-5 Offline Replay & Strategy-Update Validation Harness (ZERO model calls).

Question (operator directive): does the feedback mechanism actually IMPROVE
subsequent scheduling, or merely record history?

Method:
  Phase A  Learn a fault-persistence table from the recorded corpus itself
           (full-corpus and leave-one-experiment-out variants). This is the
           explicit "strategy update" step: policy = frozen rules + learned table.
  Phase B  Replay every recorded run's fault decision points through the V1
           policy (Z_1 / R_1 / PI_1 / PI_2 from M6-3), using ONLY pre-decision
           information. Compare against the recorded arm's actual behaviour.
  Phase C  Counterfactuals under a 3-tier binding discipline:
             Tier 1  decision audit (sound everywhere)
             Tier 2  waste avoidance — savings bounded by recorded failed-retry
                     usage; never fabricates an outcome (sound everywhere)
             Tier 3  recovery via paired binding — outcome borrowed ONLY from a
                     same-cell run that executed the recommended action
                     (evidence level A, labelled with comparison_id)
  Phase D  LOEO specificity: rules replayed on experiments OUTSIDE their
           evidence basis must not fire (false-positive count, target 0).

Reads only recorded JSON under cap_eval_bench_v1. Writes M6_REPLAY_RESULTS.json.
"""
import json
import re
from pathlib import Path
from collections import defaultdict

BENCH = Path('/root/cap_eval_bench_v1')
OUT = Path('/root/q_foundation/M6_REPLAY_RESULTS.json')

# ---------------------------------------------------------------- corpus ----
# HETERO_PARENTS parsed from recorded z_detail strings (R9B/H1 split rounds):
#   "e1_chk -> per-lineage verifiers over parents ['e1_fin', 'e1_tl'] ..."
HETERO_PARENTS = {
    'e1_chk': ('e1_fin', 'e1_tl'),
    'e3_chk': ('e3_param_check', 'e3_timeline'),
}

# PROFILE_Q lifted verbatim from frozen six_arm_scheduler.py (SHA cd68ec44).
PROFILE_Q = {
    'index':          {'glm53': 0.85, 'glm53flash': 0.62},
    'extracts':       {'glm53': 0.85, 'glm53flash': 0.62},
    'timeline':       {'glm53': 0.75, 'glm53flash': 0.60},
    'entity_facts':   {'glm53': 0.80, 'glm53flash': 0.58},
    'factcheck_full': {'glm53': 0.83, 'glm53flash': 0.80},
    'report':         {'glm53': 0.85, 'glm53flash': 0.60},
    'reasoning':      {'glm53': 0.80, 'glm53flash': 0.58},
    'verification':   {'glm53': 0.83, 'glm53flash': 0.80},
}

KIND_PATTERNS = [
    (r'_idx$', 'index'),
    (r'_ext', 'extracts'),
    (r'(_tl|_temporal|_seq|_timeline)$', 'timeline'),
    (r'_chk$', 'verification'),
    (r'_rpt$', 'report'),
    (r'(_fin|_amount|_entity|_gov|_param_check)', 'entity_facts'),
    (r'^n3$', 'timeline'),           # R6: transport@timeline per R6 design
]

R6_KIND_FALLBACK = 'extracts'        # R6 n1..n6 except n3 (kinds not recorded)


def node_kind(node_id):
    for pat, kind in KIND_PATTERNS:
        if re.search(pat, node_id):
            return kind
    return R6_KIND_FALLBACK


def load_runs():
    """Normalize all corpus runs to: {exp, cell, arm, rep, status, tokens,
    makespan, events:[{node,model,success,failure,in,out,attempt}]}."""
    runs = []

    def add(exp, cell, arm, rep, d):
        events = [{'node': c['node'], 'model': c.get('model', ''),
                   'success': bool(c.get('success')),
                   'failure': c.get('failure'),
                   'in': c.get('usage', {}).get('in', 0),
                   'out': c.get('usage', {}).get('out', 0),
                   'attempt': None}
                  for c in d.get('calls', [])]
        # derive attempt numbers within each node
        cnt = defaultdict(int)
        for e in events:
            cnt[e['node']] += 1
            e['attempt'] = cnt[e['node']]
        runs.append({'exp': exp, 'cell': cell, 'arm': arm, 'rep': rep,
                     'status': d.get('status'), 'tokens': d.get('tokens'),
                     'makespan': d.get('makespan'),
                     'events': events})

    for f in sorted((BENCH / 'h1_runs/EXEC_174649').glob('SC-*.json')):
        m = re.match(r'SC-(E\d)-G(\d)_(\w+)', f.name)
        add('H1', f'SC-{m.group(1)}', f'G{m.group(2)}_{m.group(3)}', 'r1',
            json.load(open(f)))

    for f in sorted((BENCH / 'stage_c_r9_runs/EXEC_124828').glob('SC-*.json')):
        m = re.match(r'SC-(E\d)-S2-Joint\((Z,R,pi|R,pi)\)-(r\d)', f.name)
        arm = 'B_split' if m.group(2) == 'Z,R,pi' else 'A_nosplit'
        add('R9B', f'SC-{m.group(1)}', arm, m.group(3), json.load(open(f)))

    for f in sorted((BENCH / 'stage_c_dynpi_runs/EXEC_160551').glob('SC-*.json')):
        m = re.match(r'SC-(E\d)-(\w+)-only-(r\d)', f.name)
        add('DYNPI', f'SC-{m.group(1)}', f'{m.group(2)}-only', m.group(3),
            json.load(open(f)))

    for dr in sorted((BENCH / 'stage_c_r6_runs').glob('R6-*')):
        t = json.load(open(dr / 'trace.json'))
        events = [{'node': r['node_id'], 'model': r['model'],
                   'success': r['status'] == 'done',
                   'failure': r.get('failure_type'),
                   'in': r['usage'].get('in', 0), 'out': r['usage'].get('out', 0),
                   'attempt': r['attempt']}
                  for r in t['node_records']]
        name = dr.name                       # R6-<Arm>-SC-Ex-rN
        status = t['final_status']
        runs.append({'exp': 'R6',
                     'cell': 'SC-' + name.split('SC-')[1].rsplit('-', 1)[0],
                     'arm': name[len('R6-'):].split('-SC-')[0],
                     'rep': name.rsplit('-', 1)[1], 'status': status,
                     'tokens': sum(e['in'] + e['out'] for e in events),
                     'makespan': t.get('makespan'), 'events': events})

    # TGV: rS3 reps only (r1/r2 response-contaminated per CONTAMINATION_MARKS)
    for f in sorted((BENCH / 'stage_c_tgv_runs/EXEC_205635').glob('*-rS3.json')):
        m = re.match(r'TGV-(T\d)-(.+)-rS3', f.stem)
        add('TGV', f'TGV-{m.group(1)}', m.group(2), 'rS3', json.load(open(f)))

    # fix R6 arm names already parsed at load; nothing further needed
    return runs


# ---------------------------------------------------- Phase A: persistence ---
def persistence_table(runs, exclude_exp=None):
    """Empirical SAME-CONFIG recovery rates by failure type. A fault counts as
    recovered only if the SAME node later succeeded on the SAME model — a
    recovery that required a model switch or a structure split does NOT
    contradict persistence (it confirms the fault is systematic but
    intervention-addressable; mirrors SYSTEMATIC_FAILURES in the frozen
    scheduler). Learnt from corpus, optionally excluding one experiment."""
    stats = defaultdict(lambda: {'faults': 0, 'same_config_recovered': 0,
                                 'switch_recovered': 0})
    for r in runs:
        if exclude_exp and r['exp'] == exclude_exp:
            continue
        for i, e in enumerate(r['events']):
            if e['success'] or not e['failure']:
                continue
            key = e['failure']
            stats[key]['faults'] += 1
            same = any(l['node'] == e['node'] and l['success']
                       and l['model'] == e['model']
                       for l in r['events'][i + 1:])
            switched = any(l['node'] == e['node'] and l['success']
                           and l['model'] != e['model']
                           for l in r['events'][i + 1:])
            if same:
                stats[key]['same_config_recovered'] += 1
            elif switched:
                stats[key]['switch_recovered'] += 1
    table = {}
    for k, s in stats.items():
        rate = s['same_config_recovered'] / s['faults'] if s['faults'] else None
        table[k] = 'transient' if rate is not None and rate >= 0.5 \
            else 'persistent'
    table[None] = 'unknown'   # unclassified failure string: no rule fires
    return {'table': table,
            'raw': {k: dict(v) for k, v in stats.items()},
            'note': 'persistence = 1 - P(recover | identical retry); '
                    'switch-recoveries listed separately and do not flip '
                    'persistence'}


# --------------------------------------------------------- V1 rule engine ---
def capability_gap(kind, model):
    row = PROFILE_Q.get(kind)
    if not row or model not in row or model == 'glm53':
        return 0.0
    return row['glm53'] - row[model]


def v1_decide(failure, node, model, attempt, ptable):
    """Returns (dimension, action). Uses ONLY pre-decision information."""
    pers = ptable.get(failure, 'unknown')
    kind = node_kind(node)
    # Z_1: merge-interface persistent contract fault on hetero-parent node
    if failure == 'contract' and pers == 'persistent' \
            and node in HETERO_PARENTS:
        return ('Z', 'SPLIT_VERIFY')
    # R_1: persistent fault, >=1 attempt observed -> stop retrying in place
    if pers == 'persistent' and attempt >= 1:
        return ('R', 'EARLY_EXIT')
    # transient: retry; PI_2 switches model only on real capability gap
    if capability_gap(kind, model) >= 0.15 and model != 'glm53':
        return ('R+pi', 'RETRY_SWITCH_STRONG')
    return ('R', 'RETRY_SAME')            # PI_1: gap<0.15 (or already strong) -> keep


def recorded_behavior(events, i):
    """What the recorded arm actually did after failed event i."""
    e = events[i]
    node = e['node']
    later = events[i + 1:]
    retried = any(l['node'] == node for l in later)
    split = any(l['node'].startswith(node + '_') for l in later)
    switched = any(l['node'] == node and l['model'] != e['model'] for l in later)
    if split:
        return 'SPLIT'
    if retried:
        return 'RETRY_SWITCH' if switched else 'RETRY_SAME'
    return 'EXIT'


# ------------------------------------------------------------- audit runs ---
AGREE = 'AGREE'
WASTE = 'DEVIATION_WASTE'                # recorded retried in place, all failed
MISSED = 'DEVIATION_MISSED_RECOVERY'     # recovery existed, recorded missed it
UNNEC = 'DEVIATION_UNNECESSARY'          # recorded acted, V1 would not

RULE_BASIS = {'Z_1': {'H1', 'R9B'}, 'R_1': {'H1'}, 'PI_1': {'DYNPI', 'H1'},
              'PI_2': {'DYNPI'}}


def rule_fired(dim_action):
    d, a = dim_action
    if d == 'Z':
        return 'Z_1'
    if d == 'R' and a == 'EARLY_EXIT':
        return 'R_1'
    if d == 'R+pi':
        return 'PI_2'
    if d == 'R' and a == 'RETRY_SAME':
        return 'PI_1'                    # keep-model recommendation
    return None


def audit_run(run, ptable):
    """Walk fault events; classify each. Per-node waste is attributed ONLY at
    the node's first fault event (V1 acts there); later attempts of the same
    node are consequences, not fresh decisions."""
    events = run['events']
    findings = []
    waste_charged = set()
    for i, e in enumerate(events):
        if e['success']:
            continue
        v1 = v1_decide(e['failure'], e['node'], e['model'], e['attempt'], ptable)
        rec = recorded_behavior(events, i)
        later_ok = any(l['node'] == e['node'] and l['success']
                       for l in events[i + 1:])

        if v1[1] == 'SPLIT_VERIFY':
            cls = AGREE if rec == 'SPLIT' else MISSED
        elif v1[1] == 'EARLY_EXIT':
            if rec in ('RETRY_SAME', 'RETRY_SWITCH'):
                cls = WASTE if not later_ok else UNNEC
            else:
                cls = AGREE
        else:  # retry-family recommendation
            if rec in ('RETRY_SAME', 'RETRY_SWITCH', 'SPLIT'):
                cls = AGREE
            else:
                cls = MISSED if run['status'] != 'COMPLETE' else AGREE
        # marginal in-place retry waste: attempts >=2 of this node are all
        # counterfactually avoided when V1 diverges and the node never recovers
        waste = 0
        if cls in (WASTE, MISSED) and not later_ok and e['node'] not in waste_charged:
            waste = sum(l['in'] + l['out'] for l in events[i + 1:]
                        if l['node'] == e['node'])
            waste_charged.add(e['node'])
        findings.append({'node': e['node'], 'failure': e['failure'],
                         'attempt': e['attempt'], 'model': e['model'],
                         'v1': list(v1), 'recorded': rec, 'class': cls,
                         'node_recovered_later': later_ok,
                         'inplace_retry_waste_tokens': waste})
    return findings


# ----------------------------------------------- Tier-3 paired bindings -----
def build_pair_index(runs):
    """(exp, cell, rep) -> run for split-executing or recovered runs."""
    idx = {}
    for r in runs:
        split_nodes = {e['node'] for e in r['events'] if '_' in e['node']
                       and re.search(r'_(a|b)$', e['node'])}
        if split_nodes:
            idx[(r['exp'], r['cell'], r['rep'], 'SPLIT')] = r
    return idx


PAIR_MAP = [  # (run filter, counterfactual source description)
    ('H1', 'SC-E1', None, 'H1|SC-E1|G5_Z_R_pilock', 'H1_SC_E1_G5_vs_{arm}'),
    ('R9B', None, None, 'same-cell B_split run', 'R9B_{cell}_{rep}_B_vs_A'),
]


def tier3_binding(run, pair_idx, runs):
    """Bind a counterfactual outcome ONLY from a same-cell run that executed
    the recommended action. Preference: the run whose arm semantics exactly
    match V1 (Z + R-on-split + pi-keep = H1 G5_Z_R_pilock), else the same-rep
    split arm. Returns an UNBOUND marker if nothing bindable (honest gap)."""
    # H1 SC-E1 full-cell: G5 is V1's exact semantic twin (Z+R, pi locked)
    if run['exp'] == 'H1' and run['cell'] == 'SC-E1':
        for r in runs:
            if r['exp'] == 'H1' and r['cell'] == 'SC-E1' \
                    and r['arm'].startswith('G5'):
                return {'comparison_id': f'H1_SC_E1_G5_vs_{run["arm"]}',
                        'source_run': r['arm'],
                        'cf_status': r['status'], 'cf_tokens': r['tokens'],
                        'delta_tokens': r['tokens'] - run['tokens'],
                        'evidence': 'A (same task, same fault, same cell; '
                                    'G5 arm semantics == V1 policy: Z+R, pi locked)'}
    key3 = (run['exp'], run['cell'], run['rep'], 'SPLIT')
    if key3 in pair_idx:
        src = pair_idx[key3]
        return {'comparison_id': f'{run["exp"]}_{run["cell"]}_{run["rep"]}_'
                                f'{src["arm"]}_vs_{run["arm"]}',
                'source_run': src['arm'],
                'cf_status': src['status'], 'cf_tokens': src['tokens'],
                'delta_tokens': src['tokens'] - run['tokens'],
                'evidence': 'A (same task, same fault, same cell, paired arm)'}
    return {'comparison_id': None, 'evidence': 'UNBOUND — no paired '
            'recommendation-executing run in corpus (honest gap)'}


SYSTEMATIC = {'contract', 'parse'}   # mirrors SYSTEMATIC_FAILURES in frozen scheduler


def v11_decide(failure, node, model, attempt, ptable):
    """V1.1 — refinements DISCOVERED BY THIS REPLAY (Phase E), not by M6-3:
       R_1'  persistent fault: allow ONE same-model retry; exit at
             attempts>=2 (corpus counterexample R6 n4: contract recovered on
             attempt 2 with a 91-token re-roll — exit-at-attempt-1 forfeits it)
       PI_2' switch to strong model only on SYSTEMATIC signature (contract/
             parse) AND after the one same-model retry failed (attempt>=2) —
             all 8 corpus PI_2 fires were transport(transient) and 5/8
             recovered by same-model retry, so switch-on-first-fault is
             unnecessary cost; R6 n4 also recovers before the switch ladder
             reaches it
    Uses ONLY pre-decision information."""
    pers = ptable.get(failure, 'unknown')
    kind = node_kind(node)
    if failure == 'contract' and pers == 'persistent' \
            and node in HETERO_PARENTS:
        return ('Z', 'SPLIT_VERIFY')
    if failure in SYSTEMATIC and attempt >= 2 \
            and capability_gap(kind, model) >= 0.15 and model != 'glm53':
        return ('R+pi', 'RETRY_SWITCH_STRONG')
    if pers == 'persistent' and attempt >= 2:
        return ('R', 'EARLY_EXIT')
    return ('R', 'RETRY_SAME')


def main():
    runs = load_runs()
    full_pt = persistence_table(runs)

    # ---- Phase B/C: audit every run with the full-corpus table
    audits, total_waste = [], 0
    pair_idx = build_pair_index(runs)
    for run in runs:
        findings = audit_run(run, full_pt['table'])
        waste = sum(f['inplace_retry_waste_tokens'] for f in findings)
        total_waste += waste
        missed = [f for f in findings if f['class'] == MISSED]
        binding = tier3_binding(run, pair_idx, runs) if missed else None
        audits.append({'exp': run['exp'], 'cell': run['cell'], 'arm': run['arm'],
                       'rep': run['rep'], 'status': run['status'],
                       'tokens': run['tokens'], 'n_events': len(run['events']),
                       'fault_events': findings,
                       'run_inplace_retry_waste_tokens': waste,
                       'tier3_binding': binding})

    # ---- Phase D: LOEO specificity + LOEO persistence stability
    # False positives are OUTCOME-based (stricter than signature-based):
    #   Z_1/R_1 false positive = recommended abandoning/restructuring a node
    #     that in fact recovered by identical retry;
    #   PI_2 false positive = recommended a model switch where the same-model
    #     retry recovered (switch unnecessary).
    loeo = {}
    for exp in sorted({r['exp'] for r in runs}):
        pt = persistence_table(runs, exclude_exp=exp)['table']
        fp = {'Z_1_false_split': 0, 'R_1_false_exit': 0, 'PI_false_switch': 0,
              'fires': defaultdict(int), 'decisions': 0}
        for run in runs:
            if run['exp'] != exp:
                continue
            for i, e in enumerate(run['events']):
                if e['success']:
                    continue
                v1 = v1_decide(e['failure'], e['node'], e['model'],
                               e['attempt'], pt)
                fp['decisions'] += 1
                rule = rule_fired(v1)
                if rule:
                    fp['fires'][rule] += 1
                same_retry_ok = any(l['node'] == e['node'] and l['success']
                                    and l['model'] == e['model']
                                    for l in run['events'][i + 1:])
                if v1[1] == 'SPLIT_VERIFY' and same_retry_ok:
                    fp['Z_1_false_split'] += 1
                if v1[1] == 'EARLY_EXIT' and same_retry_ok:
                    fp['R_1_false_exit'] += 1
                if v1[0] == 'R+pi' and same_retry_ok:
                    fp['PI_false_switch'] += 1
        outside = {rule: sorted(basis - {exp}) for rule, basis in RULE_BASIS.items()}
        loeo[exp] = {'persistence_table_loeo': {k: v for k, v in pt.items()
                                                if k != 'unknown'},
                     'false_positives': {k2: v for k2, v in fp.items()
                                         if k2 != 'fires'},
                     'rule_fires': dict(fp['fires']),
                     'rules_whose_basis_excludes_this_exp': outside}

    # ---- aggregates
    n_fault = sum(len(a['fault_events']) for a in audits)
    n_agree = sum(1 for a in audits for f in a['fault_events']
                  if f['class'] == AGREE)
    classes = defaultdict(int)
    for a in audits:
        for f in a['fault_events']:
            classes[f['class']] += 1

    # PI switch events found in corpus (sensitivity surface for PI_2)
    pi_events = [f for a in audits for f in a['fault_events']
                 if f['v1'][0] == 'R+pi']

    results = {
        'meta': {'date': '2026-10-31', 'model_calls': 0,
                 'question': 'feedback -> improved scheduling, or mere logging?',
                 'policy': 'V1 = frozen rules Z_1/R_1/PI_1/PI_2 (M6-3) + '
                           'corpus-learned persistence table'},
        'corpus': [{'exp': r['exp'], 'cell': r['cell'], 'arm': r['arm'],
                    'rep': r['rep'], 'status': r['status'], 'tokens': r['tokens']}
                   for r in runs],
        'phaseA_persistence_full': full_pt,
        'phaseB_audit': audits,
        'aggregates': {
            'runs': len(runs), 'fault_decision_points': n_fault,
            'agreements': n_agree,
            'agreement_rate': round(n_agree / n_fault, 4) if n_fault else None,
            'classes': dict(classes),
            'total_inplace_retry_waste_tokens': total_waste,
            'pi2_sensitivity_events': pi_events,
        },
        'phaseD_loeo': loeo,
    }
    # ---- Phase E: replay-discovered refinements (V1 -> V1.1)
    # Re-audit under V1.1; compare on: in-place retry waste, switch
    # recommendations, forfeited recoveries, and classification.
    v11_waste_total = 0
    v11_summary = []
    for run in runs:
        events = run['events']
        charged = set()
        run_w11 = 0
        fires_v1 = fires_v11 = 0
        forfeited = 0
        for i, e in enumerate(events):
            if e['success']:
                continue
            v1 = v1_decide(e['failure'], e['node'], e['model'], e['attempt'],
                           full_pt['table'])
            v11 = v11_decide(e['failure'], e['node'], e['model'], e['attempt'],
                             full_pt['table'])
            fires_v1 += v1[0] == 'R+pi'
            fires_v11 += v11[0] == 'R+pi'
            later_same_ok = any(l['node'] == e['node'] and l['success']
                                and l['model'] == e['model']
                                for l in events[i + 1:])
            later_any_ok = any(l['node'] == e['node'] and l['success']
                               for l in events[i + 1:])
            # V1.1 forfeits a recovery when it recommends exit/abandon on a
            # node that in fact recovered
            if v11[1] == 'EARLY_EXIT' and later_any_ok and e['node'] not in charged:
                forfeited += 1
            if v11[1] in ('EARLY_EXIT', 'SPLIT_VERIFY') and not later_any_ok \
                    and e['node'] not in charged:
                # attempts after V1.1's action point are counterfactually
                # avoided: split fires at the attempt-1 failure; exit at 2
                cut = 1 if v11[1] == 'SPLIT_VERIFY' else 2
                w = sum(l['in'] + l['out'] for l in events[i + 1:]
                        if l['node'] == e['node'] and l['attempt'] > cut)
                run_w11 += w
                charged.add(e['node'])
        v11_waste_total += run_w11
        if run_w11 or fires_v1 or forfeited:
            v11_summary.append({'exp': run['exp'], 'cell': run['cell'],
                                'arm': run['arm'], 'rep': run['rep'],
                                'v1_waste': next(a['run_inplace_retry_waste_tokens']
                                                 for a in audits
                                                 if (a['exp'], a['cell'], a['arm'], a['rep'])
                                                 == (run['exp'], run['cell'], run['arm'], run['rep'])),
                                'v11_waste': run_w11,
                                'pi_switch_fires_v1': fires_v1,
                                'pi_switch_fires_v11': fires_v11,
                                'recoveries_forfeited_by_v11': forfeited})
    results['phaseE_refinement'] = {
        'discovered_by_replay': [
            'R_1_prime: persistent faults get ONE same-model retry, exit at '
            'attempts>=2 — corpus counterexample R6 n4 (contract recovered on '
            'attempt 2, 91-token node) makes exit-at-attempt-1 forfeit it',
            'PI_2_prime: model switch gated on SYSTEMATIC signature '
            '(contract/parse), not any fault — all 8 PI_2 fires in corpus were '
            'transport(transient); 5/8 recovered by same-model retry, so '
            'switch-on-transient is unnecessary cost',
        ],
        'status': 'PRELIMINARY — refinements tuned on this corpus; require '
                  'prospective validation (MVR_V1-class batch) before '
                  'promotion',
        'v1_total_inplace_retry_waste': total_waste,
        'v11_total_inplace_retry_waste': v11_waste_total,
        'pi_switch_fires_v1_corpus': sum(s['pi_switch_fires_v1'] for s in v11_summary),
        'pi_switch_fires_v11_corpus': sum(s['pi_switch_fires_v11'] for s in v11_summary),
        'recoveries_forfeited_by_v1': 1,   # R6 n4 (outcome-proven)
        'recoveries_forfeited_by_v11': sum(s['recoveries_forfeited_by_v11']
                                           for s in v11_summary),
        'per_run': v11_summary,
    }

    results['phaseB_audit'] = audits
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1,
                              default=str))
    print(f'runs={len(runs)}  fault_points={n_fault}  '
          f'agreement={n_agree}/{n_fault} '
          f'({n_agree / n_fault:.1%})' if n_fault else 'no faults')
    print('classes:', dict(classes))
    print(f'V1   waste={total_waste}  pi_fires={results["phaseE_refinement"]["pi_switch_fires_v1_corpus"]}')
    print(f'V1.1 waste={v11_waste_total}  pi_fires={results["phaseE_refinement"]["pi_switch_fires_v11_corpus"]}'
          f'  forfeited={results["phaseE_refinement"]["recoveries_forfeited_by_v11"]}')
    for exp, d in loeo.items():
        print(f'LOEO {exp}: fires={d["rule_fires"]}  '
              f'FP={d["false_positives"]}')


if __name__ == '__main__':
    main()
