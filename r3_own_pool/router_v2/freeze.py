"""Copy fully scored, audited outcomes without regenerating splits or utilities."""
import argparse
import json
from pathlib import Path
import shutil
from .data import load_cohort, load_outcomes, matrix, verify_gate, sha


def freeze(cohort_dir, outcomes, gate_path, output):
    cohort, split=load_cohort(cohort_dir)
    gate=verify_gate(gate_path,outcomes,cohort_dir)
    rows=load_outcomes(outcomes,cohort)
    for partition in ('train','validation','test'):
        matrix(rows,split[partition])  # domain/coverage only, no summary of test performance
    dest=Path(output)
    dest.mkdir(parents=True,exist_ok=False)
    for source,name in [(outcomes,'outcomes.jsonl'),(gate_path,'GATE.json'),
                        (Path(cohort_dir)/'split.json','split.json')]:
        shutil.copyfile(source,dest/name)
    files={name:sha(dest/name) for name in ('outcomes.jsonl','GATE.json','split.json')}
    (dest/'MANIFEST.json').write_text(json.dumps(dict(files=files,
        query_sha256=sha(Path(cohort_dir)/'queries.jsonl'),
        counts={k:len(v) for k,v in split.items()},gate_role=gate.get('role','development'),
        note='Original split preserved; no difficulty features or per-query outcome normalization generated.'),indent=2))
    return dest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('cohort','outcomes','gate','output'):
        ap.add_argument('--'+name,required=True)
    a=ap.parse_args()
    print(freeze(a.cohort,a.outcomes,a.gate,a.output))

if __name__=='__main__':main()
