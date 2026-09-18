"""Full 148-node snapshot preparation. Imports the frozen pilot snapshot builder unchanged;
writes runtime/offline snapshots to a separate full directory. Fail closed on any invalid node."""
import hashlib
import json
from collections import Counter
from .recovery_matrix_v2_snapshot import BASE, Sources, build_snapshot, offline_payload, digest

OUT = BASE / 'recovery_matrix_v2/full_4983983'
FROZEN_COMMIT = '49839833a30d5a0d1ae2acb5c2d93bff4f0b22ae'
FROZEN_FILES = ['recovery_matrix_v2_snapshot.py', 'recovery_matrix_v2_pilot.py',
                'recovery_matrix_v2_audit.py', 'run.py', 'tool_aware_v1.py', 'decompose_v1.py',
                'recovery_matrix_v2_spec.py', 'recovery_matrix_v2/frozen_prompts.json']

def prepare_full():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = Sources()
    pool = json.loads((BASE / 'recovery_matrix_v2_pool_final.json').read_text())
    assert len(pool) == 148, len(pool)
    assert Counter(n['label'] for n in pool) == {'evidence': 61, 'reasoning': 61, 'structural': 26}
    snaps = {n['node_id']: build_snapshot(n, sources) for n in pool}
    invalid = [dict(node_id=n['node_id'], reason=snaps[n['node_id']].get('invalid_reason'))
               for n in pool if not snaps[n['node_id']]['valid']]
    assert not invalid, invalid  # full pool is frozen; no pilot-style replacements
    (OUT / 'runtime').mkdir(exist_ok=True); (OUT / 'offline').mkdir(exist_ok=True)
    for node in pool:
        name = hashlib.sha256(node['node_id'].encode()).hexdigest() + '.json'
        (OUT / 'runtime' / name).write_text(json.dumps(snaps[node['node_id']], ensure_ascii=False, indent=2))
        (OUT / 'offline' / name).write_text(json.dumps(offline_payload(node, sources), ensure_ascii=False, indent=2))
    code_hashes = {f: hashlib.sha256((BASE / f).read_bytes()).hexdigest() for f in FROZEN_FILES}
    report = dict(frozen_commit=FROZEN_COMMIT, pilot_passed=True, full_experiment_started=True,
                  failure_pool_size=148, pool_counts=dict(Counter(n['label'] for n in pool)),
                  snapshot_invalid=invalid, replacements=[], selected_ids=[n['node_id'] for n in pool],
                  frozen_code_sha256=code_hashes,
                  pool_manifest_sha256=hashlib.sha256((BASE / 'recovery_matrix_v2_pool_final.json').read_bytes()).hexdigest())
    (OUT / 'FULL_SNAPSHOT_AUDIT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report

if __name__ == '__main__':
    print(json.dumps(prepare_full(), ensure_ascii=False, indent=2))
