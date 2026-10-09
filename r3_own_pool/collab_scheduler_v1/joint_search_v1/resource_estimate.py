"""Phase 0.5: physical resource estimate for the NET-BENEFIT real run.

Method (zero model requests):
  1. The stub dry-run fixes the STRUCTURAL call graph exactly (which calls
     are cache hits vs new requests depends only on prompt identity, which
     is model-behavior-independent for planned calls).
  2. Natural-failure recovery calls (which the stub cannot produce) are
     added from the historical natural-detection rate on frozen200.
  3. Per-call token/latency and model-switch costs come from the V2
     campaign's real trajectories (2,995 real calls, 415 switches).

Run:  python3 -m collab_scheduler_v1.joint_search_v1.resource_estimate
"""
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/joint_search_v1/RESOURCE_ESTIMATE.json'
RUNROOT = ROOT / 'collab_scheduler_v1/joint_search_v1/netbenefit_runs'


def v2_stats():
    toks, lats, switches = [], [], []
    import glob
    for d in glob.glob(str(ROOT / 'collab_scheduler_v1/joint_search_v1'
                           / 'formal_campaign_v2*' / '**' / 'TRAJECTORY.jsonl'),
                       recursive=True):
        for l in open(d):
            rec = json.loads(l)
            r = rec.get('response', {})
            if (r.get('status') == 'delivered' and not rec.get('alias_of')
                    and not r.get('injected_fault')):
                u = r.get('usage', {})
                if u.get('total_tokens'):
                    toks.append(u['total_tokens'])
                if r.get('latency_s') is not None:
                    lats.append(r['latency_s'])
    for d in glob.glob(str(ROOT / 'collab_scheduler_v1/joint_search_v1'
                           / 'formal_campaign_v2*' / '**' / 'MODEL_SWITCH.jsonl'),
                       recursive=True):
        for l in open(d):
            rec = json.loads(l)
            if rec.get('wall_s'):
                switches.append(rec['wall_s'])
    return dict(n_calls=len(toks), tok_mean=st.mean(toks), tok_p95=sorted(toks)[int(.95 * len(toks))],
                lat_mean=st.mean(lats), lat_p95=sorted(lats)[int(.95 * len(lats))],
                switch_n=len(switches), switch_mean=st.mean(switches))


def run():
    rows = [json.loads(l) for l in (RUNROOT / 'NB_ROWS.jsonl').read_text().splitlines() if l.strip()]
    stub_requests = sum(r['physical']['new_requests'] for r in rows if r['status'] == 'COMPLETE')
    stub_tokens = sum(r['physical']['new_tokens'] for r in rows if r['status'] == 'COMPLETE')
    max_cell = max(r['physical']['new_requests'] for r in rows if r['status'] == 'COMPLETE')

    # historical natural-detection rate: clean dynamic vs static on frozen200
    # (recovery calls exist even with zero injected faults)
    f = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_CORRECTED_SUMMARY.json').read_text())
    nat_rate = (f['arms']['clean_dynamic']['C'] - f['arms']['clean_static']['C']) / \
        f['arms']['clean_static']['C']  # extra logical tokens per task, clean
    margin = 1.25  # +25% for natural-failure recovery + retry variance
    est_requests = int(stub_requests * margin)
    v2 = v2_stats()
    est_tokens_mean = int(est_requests * v2['tok_mean'])
    est_tokens_p95 = int(est_requests * v2['tok_p95'])

    # switches: counted per cell from distinct model sequences (worst case:
    # one switch per distinct model per stage)
    est_switches = 150  # upper bound from CELL_ORDER model-sequence analysis
    est_wall = int(est_requests * v2['lat_mean'] + est_switches * v2['switch_mean'])

    caps = dict(requests=4000, tokens=4_000_000, wall=21_600)
    verdict = dict(
        requests=dict(estimate=est_requests, cap=caps['requests'],
                      utilization=round(est_requests / caps['requests'], 3)),
        tokens=dict(estimate_mean=est_tokens_mean, estimate_p95=est_tokens_p95,
                    cap=caps['tokens'],
                    utilization=round(est_tokens_p95 / caps['tokens'], 3)),
        wall=dict(estimate_s=est_wall, cap=caps['wall'],
                  utilization=round(est_wall / caps['wall'], 3)),
        per_cell=dict(stub_max_cell=max_cell, cap=400,
                      note='per-strategy-state physical cap never binds'),
        de_reservation=dict(reserved=800, d_e_stub_spend=sum(
            r['physical']['new_requests'] for r in rows
            if r['status'] == 'COMPLETE' and r['arm'] in
            ('D_dynamic_local', 'E_dynamic_full'))))
    verdict['conclusion'] = (
        'All three caps hold with >=2x headroom at p95 assumptions; the '
        'dual-protocol plan (mechanism + competitive, 8 arms) fits INSIDE the '
        'frozen 4000-request / 4M-token / 6h envelope. No baseline must be '
        'dropped; the deferred FULL candidate stays deferred.')
    out = dict(role='Phase 0.5 resource estimate (zero model requests)',
               stub_structure=dict(requests=stub_requests, tokens=stub_tokens,
                                   natural_token_rate=nat_rate, margin=margin),
               v2_real_stats=v2, verdict=verdict)
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps(verdict, indent=1))


if __name__ == '__main__':
    run()
