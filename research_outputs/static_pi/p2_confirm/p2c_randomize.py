#!/usr/bin/env python3
"""P2-C randomization table (preregistered algorithm; frozen before the seed is computed).

Unit of inference stays the task (26); the table only fixes execution order.
  blocks   = 26 tasks x 2 replicates = 52 (task, rep) blocks; task list = manifest order sorted by task code
  seed     = int(first 8 hex digits of sha256(manifest file bytes), 16) -- fixed by already-frozen content
  order    = random.Random(seed).shuffle(blocks)
  per block (same RNG stream, in block order): shared upstream first (structural prerequisite of G2-G6);
             G2 first among multi-agent arms (checkpoint); G3-G6 in a random permutation after G2;
             G1 inserted at a uniformly random position among the 6 arm slots (independent of the checkpoint)
No re-draw: the script refuses to write if an output already exists.
Usage: p2c_randomize.py MANIFEST OUT
"""
import hashlib, json, random, sys
from pathlib import Path


def build(manifest_path):
    raw = Path(manifest_path).read_bytes()
    man_sha = hashlib.sha256(raw).hexdigest()
    seed = int(man_sha[:8], 16)
    tasks = sorted(r['task'] for r in json.loads(raw)['contracts'])
    assert len(tasks) == 26 and len(set(tasks)) == 26
    blocks = [(t, rep) for t in tasks for rep in (1, 2)]
    rng = random.Random(seed)
    rng.shuffle(blocks)
    table = []
    for i, (t, rep) in enumerate(blocks, 1):
        rest = ['G3', 'G4', 'G5', 'G6']
        rng.shuffle(rest)
        seq = ['G2'] + rest
        seq.insert(rng.randrange(len(seq) + 1), 'G1')
        table.append(dict(block=i, task=t, rep=rep, arm_order=seq))
    return dict(manifest_sha256=man_sha, seed=seed, seed_rule='int(sha256(manifest)[:8], 16)',
                algorithm_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                n_blocks=len(table), table=table)


if __name__ == '__main__':
    out = Path(sys.argv[2])
    if out.exists():
        sys.exit(f'REFUSE: {out} exists (no re-draw)')
    res = build(sys.argv[1])
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', 'utf-8')
    out.chmod(0o444)
    print('seed', res['seed'], 'table sha256', hashlib.sha256(out.read_bytes()).hexdigest())
