"""E9 extension: label audit on the independent 100-query confirmation panel.

The confirmation set was collected selectively: reasoning has 5 repeats on all
100 queries, medium/large only on the 10 queries the router switched to. So a
full Bayesian audit is impossible at zero cost; instead this reports (1) the
R1 label distribution fresh-100 vs development-400 and (2) the Bayesian
support P(theta_m > theta_R1) of the router's 10 actual switches, compared
with the development panel's switch labels. Same Jeffreys machinery as E9.
"""
import importlib.metadata
import json
from pathlib import Path
import numpy as np

from .data import sha, load_cohort
from .rescore_glm_pilot import extract_option
from .run_e9_routing_label_audit import p_greater, write

ROOT = Path(__file__).resolve().parents[1]
E9 = ROOT / 'router_v2/e9_routing_label_audit'
E6 = ROOT / 'router_v2/e6_representation_objective_2x2'
CONF = ROOT / 'router_v2/ridge_confirmation_100'
EXP = ROOT / 'router_v2/experiment_ridge_confirmation_100'
RAW_R1 = ROOT / 'data/ridge_confirmation_100_reasoning/reasoning.jsonl'
REF = 3


def load_repeats(path, slots):
    rows = {}
    for line in path.open():
        r = json.loads(line)
        rows.setdefault(r['query_id'], {}).setdefault(r['slot'], []).append(r)
    return rows


def rescored_quality(row, cohort):
    """Same scoring as the frozen confirmation analyzer: extract_option vs ground truth."""
    option = extract_option(row.get('answer') or '') if row.get('status') != 'failed' else None
    gt = str(cohort[row['query_id']]['ground_truth']).strip().upper()[-1]
    return float(option == gt) if option else 0.0


def k_of(block, slot, cohort):
    return int(sum(rescored_quality(r, cohort) for r in block[slot]))


def run():
    out = E9 / 'confirmation_100'
    if out.exists():
        raise FileExistsError('Confirmation audit already exists')
    e9_protocol = json.loads((E9 / 'PROTOCOL.json').read_text())
    if sha(E9 / 'RESULTS.json') != e9_protocol['hashes'][str(E9 / 'RESULTS.json')]:
        raise ValueError('E9 audit changed')
    z = np.load(E6 / 'INPUTS.npz', allow_pickle=False)
    dev_ids = set(z['ids'].tolist())
    per_query = {r['query_id']: r for r in map(json.loads, (E9 / 'PER_QUERY.jsonl').open())}
    blocks = load_repeats(RAW_R1, ['reasoning'])
    cohort, _ = load_cohort(ROOT / 'data/cohort_full_v2')
    panel_ids = [r['query_id'] for r in map(json.loads, (CONF / 'PANEL.jsonl').open())]
    if len(panel_ids) != 100 or len(blocks) != 100:
        raise ValueError('Confirmation panel mismatch')
    overlap = sorted(set(panel_ids) & dev_ids)
    if overlap:
        raise ValueError(f'Confirmation/dev overlap: {overlap[:5]}')
    for q in panel_ids:
        if len(blocks[q]['reasoning']) != 5:
            raise ValueError(f'Incomplete R1 repeats: {q}')
    fresh_k = np.array([k_of(blocks[q], 'reasoning', cohort) for q in panel_ids])
    dev_k = z['repeats'][:, REF, :].sum(1).astype(int)
    experiment = json.loads((EXP / 'RESULTS.json').read_text())
    if abs(fresh_k.mean() / 5 - experiment['r1_expected_quality']) > 1e-9:
        raise ValueError('Rescored R1 mean does not reproduce the frozen confirmation analyzer')
    decisions = {r['query_id']: r for r in map(json.loads, (CONF / 'FROZEN_DECISIONS.jsonl').open())}
    switched = [q for q, r in decisions.items() if r['choice_slot'] != 'reasoning']
    raw_probe = {}
    for slot in ['medium', 'large']:
        for line in (ROOT / f'data/ridge_confirmation_100_selected/{slot}.jsonl').open():
            r = json.loads(line)
            raw_probe.setdefault(r['query_id'], {}).setdefault(slot, []).append(r)
    switch_rows = []
    for q in switched:
        slots_here = [s for s in ['medium', 'large'] if s in raw_probe.get(q, {})]
        if len(slots_here) != 1 or len(raw_probe[q][slots_here[0]]) != 5:
            raise ValueError(f'Switched query without complete probe repeats: {q}')
        slot = slots_here[0]
        k_m = int(sum(rescored_quality(r, cohort) for r in raw_probe[q][slot]))
        k_ref = int(fresh_k[panel_ids.index(q)])
        p_win = p_greater(k_m + 0.5, 5 - k_m + 0.5, k_ref + 0.5, 5 - k_ref + 0.5)
        switch_rows.append(dict(query_id=q, alt=slot, k_alt=k_m, k_r1=k_ref,
                                delta_mean5=(k_m - k_ref) / 5,
                                p_alt_greater_r1=round(p_win, 4)))
    dev_switch_pwin = [max(r['p_win']) for r in per_query.values() if r['label'] == 'switch']
    result = dict(
        experiment='E9 extension: confirmation-100 label audit', n=100,
        disjoint_from_dev=bool(not overlap),
        r1_labels=dict(
            dev400=dict(mean=float(dev_k.mean() / 5), k_distribution={str(k): int(c) for k, c in zip(*np.unique(dev_k, return_counts=True))}),
            fresh100=dict(mean=float(fresh_k.mean() / 5), k_distribution={str(k): int(c) for k, c in zip(*np.unique(fresh_k, return_counts=True))})),
        router_switches=dict(
            count=len(switch_rows), experiment_report=experiment['switch_n'],
            rows=switch_rows,
            bayesian_support=dict(switches_with_p_win_gt_09=int(sum(r['p_alt_greater_r1'] > .9 for r in switch_rows)),
                                  switches_with_p_win_gt_05=int(sum(r['p_alt_greater_r1'] > .5 for r in switch_rows)),
                                  median_p_win=float(np.median([r['p_alt_greater_r1'] for r in switch_rows]))),
            dev400_switch_reference=dict(n=len(dev_switch_pwin),
                                         median_max_p_win=float(np.median(dev_switch_pwin)),
                                         frac_gt_09_by_definition=1.0)),
        limitations=['Medium/large were collected only on switched queries; a full fresh-panel audit needs ~950 more generations.',
                     'Labels re-derived with the frozen confirmation analyzer scoring (extract_option vs ground truth); R1 mean reproduces 0.692 exactly.',
                     'n=10 switches; descriptive, not a significance test.'],
        hashes=dict(reasoning=sha(RAW_R1), panel=sha(CONF / 'PANEL.jsonl'), decisions=sha(CONF / 'FROZEN_DECISIONS.jsonl'),
                    experiment=sha(EXP / 'RESULTS.json'), e9_results=sha(E9 / 'RESULTS.json')),
        packages={p: importlib.metadata.version(p) for p in ['numpy', 'scipy']})
    out.mkdir()
    write(out / 'RESULTS.json', result)
    write(out / 'PROTOCOL.json', dict(experiment='E9 confirmation-100 label audit extension',
                                      method='same Jeffreys posterior and p_greater as E9; zero generation',
                                      hashes={str(Path(__file__)): sha(Path(__file__))}))
    print(json.dumps(dict(dev_r1_mean=result['r1_labels']['dev400']['mean'],
                          fresh_r1_mean=result['r1_labels']['fresh100']['mean'],
                          switch_support=result['router_switches']['bayesian_support']), indent=1))


def main():
    run()


if __name__ == '__main__':
    main()
