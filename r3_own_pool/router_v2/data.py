"""Explicit manifests and split-aware matrix extraction for v2."""
import hashlib
import json
from pathlib import Path
import numpy as np
from .core import SLOTS


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().split("\n") if line.strip()]


def load_cohort(directory):
    directory = Path(directory)
    rows = read_rows(directory/'queries.jsonl')
    manifest = json.loads((directory/'MANIFEST.json').read_text())
    split = json.loads((directory/'split.json').read_text())
    if sha(directory/'queries.jsonl') != manifest['query_sha256']:
        raise ValueError('Cohort hash mismatch')
    ids = [r['query_id'] for r in rows]
    if len(set(ids)) != len(ids) or len({r['query'] for r in rows}) != len(rows):
        raise ValueError('Duplicate query id or prompt')
    flat = [q for name in ('train', 'validation', 'test') for q in split[name]]
    if len(flat) != len(set(flat)) or set(flat) != set(ids):
        raise ValueError('Split overlap or incomplete coverage')
    for name in ('train', 'validation', 'test'):
        if not split[name] or len(split[name]) != manifest['split_counts'][name]:
            raise ValueError('Split count mismatch')
    return {r['query_id']: r for r in rows}, split


def load_outcomes(path, cohort):
    rows = read_rows(path)
    by = {r['query_id']: r for r in rows}
    if len(by) != len(rows) or set(by) != set(cohort):
        raise ValueError('Outcome matrix must cover exact cohort, without duplicate ids')
    for qid, row in by.items():
        if row['query'] != cohort[qid]['query']:
            raise ValueError('Outcome prompt mismatch')
        slots = [s['slot'] for s in row['responses']]
        if sorted(slots) != sorted(SLOTS):
            raise ValueError('Incomplete or duplicate response slots')
    return by


def matrix(by, ids):
    values = []
    for qid in ids:
        by_slot = {s['slot']: s for s in by[qid]['responses']}
        values.append([[by_slot[s]['quality']['final'], by_slot[s]['cost']['usd'],
                        by_slot[s]['latency']['total_ms']] for s in SLOTS])
    y = np.asarray(values, dtype=float)
    if not np.isfinite(y).all() or (y < 0).any() or (y[:, :, 0] > 1).any():
        raise ValueError('Missing/invalid Q,C,L: no dropped queries or implicit zero imputation')
    return y


def verify_gate(gate_path, outcome_path, cohort_dir):
    gate = json.loads(Path(gate_path).read_text())
    expected = {'outcomes_sha256': sha(outcome_path),
                'queries_sha256': sha(Path(cohort_dir)/'queries.jsonl'),
                'split_sha256': sha(Path(cohort_dir)/'split.json')}
    if any(gate.get(k) != v for k, v in expected.items()):
        raise ValueError('Gate hashes do not match inputs')
    for key in ('scoring_complete', 'failures_accounted', 'cost_provenance_verified',
                'code_sandbox_verified', 'holdout_uncontaminated'):
        if gate.get(key) is not True:
            raise ValueError('Data gate not satisfied: ' + key)
    if gate.get('currency') != 'USD' or not gate.get('cost_basis'):
        raise ValueError('Current schema requires documented common USD cost basis')
    return gate
