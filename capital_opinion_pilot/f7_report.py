"""Post-hoc analysis for the F7 four-run experiment (zero-pay).

Reads f7min_results.json (+ responses ledger) and produces the paired comparison
with DUAL quality metrics and evidence-chain verification:

  full_set_coverage   : supported facts / 4 (RF1-RF4)
  reachable_coverage  : supported facts / reachable set (RF1,RF2 under the frozen
                        10K line-split retrieval — computed from the SAME frozen
                        packer, not from run outputs)
  evidence_chain      : a counted fact is chain-valid only if its anchor quote is
                        present in the run's evidence pack (unsupported correct
                        guesses are reported separately, never counted as recovery)

Usage: python3 f7_report.py   (prints tables; writes f7_paired_report.json)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR, norm
import evidence_packer as ep

P = PILOT_DIR
LINE_DOCS = {'t1': ['kdx_penalty_2020', 'kdx_notice_2019', 'kdx_notice_2020'],
             't2': ['kdx_inquiry_2018', 'kdx_inquiry_2019']}
ORDER = ['R1_B3p_clean', 'R2_B3p_F7', 'R3_S5Cap_F7', 'R4_S6_F7']
LABEL = {'R1_B3p_clean': "B3' clean", 'R2_B3p_F7': "B3' F7 (no recovery)",
         'R3_S5Cap_F7': 'S5+Capability F7', 'R4_S6_F7': 'S6 Joint F7'}


def build_context():
    ranked = ep.rank_chunks(ep.build_index())
    packs = ep.pack_lines(10000, LINE_DOCS, ranked=ranked)
    pack_text = packs['t1']['text'] + '\n' + packs['t2']['text']
    facts = [f for f in json.loads((P / 'kdx_st_reference_facts.json').read_text())['facts']
             if f['event_id'].startswith('kdx')]
    hay = norm(pack_text)
    reachable = [f['fact_id'] for f in facts if norm(f['anchor_quote']) in hay
                 or any(it['doc_id'] == f['doc_id'].split('_', 1)[1]
                        and it['start'] < f['char_end'] and it['end'] > f['char_start']
                        for it in packs['t1']['items'] + packs['t2']['items'])]
    return facts, pack_text, reachable


def main():
    res_path = P / 'f7min_results.json'
    if not res_path.exists():
        print('NOT READY: f7min_results.json missing (F7 not finished)')
        return
    results = json.loads(res_path.read_text())['runs']
    facts, pack_text, reachable = build_context()
    pack_hay = norm(pack_text)
    anchor_in_pack = {f['fact_id']: norm(f['anchor_quote']) in pack_hay for f in facts}

    rows = []
    for rid in ORDER:
        if rid not in results:
            rows.append({'run': rid, 'status': 'MISSING'})
            continue
        r = results[rid]
        # rebuild deliverable from persisted outputs in results (t5/t6 captured
        # during the run) — evidence chain needs the actual answer text
        covered = set(r['t1_covered'])
        chain_valid = {f for f in covered if anchor_in_pack.get(f)}
        chain_broken = sorted(covered - chain_valid)
        reach_cov = len(chain_valid & set(reachable))
        row = {'run': rid, 'label': LABEL[rid], 'policy': r['policy'],
               'complete': r['complete'], 'wall_s': r['wall_s'],
               'deadline_met': r['deadline_met'],
               'full_set_coverage': f'{len(chain_valid)}/4',
               'reachable_coverage': f'{reach_cov}/{len(reachable)}',
               'chain_broken_hits': chain_broken,
               'raw_t1_covered': sorted(covered),
               'tokens': r['tokens'], 'cash_rmb': r['cash_rmb'],
               'facts_t1': r['facts']['t1'], 'facts_t2': r['facts']['t2'],
               'recovery': r.get('decisions'), 'fault_records': r.get('fault_records')}
        rows.append(row)

    # paired contrasts
    def by(label):
        return next(r for r in rows if r.get('label') == label)

    report = {'reachable_set': reachable,
              'note': ('coverage counts only evidence-chain-valid facts; reachable set '
                       'computed from the frozen 10K line-split packer, independent of '
                       'run outputs'),
              'rows': rows, 'meter': json.loads(res_path.read_text()).get('meter')}
    try:
        r1, r2, r3, r4 = by("B3' clean"), by("B3' F7 (no recovery)"), \
            by('S5+Capability F7'), by('S6 Joint F7')
        report['contrasts'] = {
            'F7_static_quality_loss': {
                'clean_full': r1['full_set_coverage'], 'fault_full': r2['full_set_coverage'],
                'clean_reach': r1['reachable_coverage'], 'fault_reach': r2['reachable_coverage']},
            'S5Cap_recovery': {'full': r3['full_set_coverage'], 'reach': r3['reachable_coverage'],
                               'wall_s': r3['wall_s'], 'tokens': r3['tokens'], 'cash': r3['cash_rmb']},
            'S6_recovery': {'full': r4['full_set_coverage'], 'reach': r4['reachable_coverage'],
                            'wall_s': r4['wall_s'], 'tokens': r4['tokens'], 'cash': r4['cash_rmb']},
            'S6_vs_S5Cap': {
                'same_quality': r4['full_set_coverage'] == r3['full_set_coverage'],
                'S6_changed_Z_or_R': [d for d in (r4.get('recovery') or [])
                                      if d.get('policy') == 's6'][0] if r4.get('recovery') else None},
        }
    except StopIteration:
        report['contrasts'] = 'INCOMPLETE — some runs missing'
    (P / 'f7_paired_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
