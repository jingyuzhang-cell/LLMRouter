"""Read-only readiness report. Never manufacture positive provenance attestations."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from .data import load_cohort, sha


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    cohort,split=load_cohort(root/'data/cohort_full_v2')
    raw=subprocess.run([sys.executable,str(root/'collection_status.py')],check=True,capture_output=True,text=True)
    coverage=json.loads(raw.stdout)
    ready=coverage['four_slot_queries_recorded']==len(cohort)
    report=dict(cohort_queries=len(cohort),split_counts={k:len(v) for k,v in split.items()},
        split_sha256=sha(root/'data/cohort_full_v2/split.json'),raw=coverage,
        gates=dict(raw_matrix_complete=ready,cohort_hash_and_split=True,
                   scoring_complete='not_certified',cost_provenance_verified='not_certified',
                   code_sandbox_verified='not_certified',holdout_uncontaminated='not_certified'),
        training_ready=False,
        next_step='Complete raw collection and independently audit scoring, cost basis, sandbox and holdout history; fit requires a hash-bound gate document.',
        note='No outcome-quality metrics inspected; stale lane status can disagree with live processes.')
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
