"""Independently recompute the saved E4 metrics without fitting models."""
import json
from pathlib import Path
import numpy as np
from .data import sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'router_v2/e4_representation_20260914'


def main():
    protocol = json.loads((OUT / 'PROTOCOL.json').read_text())
    result = json.loads((OUT / 'RESULTS.json').read_text())
    for p, digest in protocol['hashes'].items():
        assert sha(p) == digest, p
    assert sha(OUT / 'PROTOCOL.json') == result['protocol_sha256']
    assert sha(OUT / 'PREDICTIONS.npz') == result['prediction_sha256']
    z = np.load(OUT / 'PREDICTIONS.npz', allow_pickle=False)
    rows = {r['query_id']: r for r in map(json.loads, (ROOT / 'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl').open())}
    ids = z['ids'].tolist()
    assert len(ids) == len(set(ids)) == 400
    v = np.array([[rows[q]['models'][s]['values'] for s in protocol['slots']] for q in ids])
    base = z['BestSingle_scores'].mean(1)
    assert np.isclose(base.mean(), result['best_single_eq'])
    unique, inv = np.unique(z['groups'], return_inverse=True)
    assert len(unique) == result['prompt_groups']
    boot = np.random.default_rng(20260914).integers(0, len(unique), (10000, len(unique)))
    counts = np.bincount(inv)
    def ci(values, level):
        total = np.bincount(inv, weights=values)
        means = total[boot].sum(1) / counts[boot].sum(1)
        return 100 * np.quantile(means, [(1 - level) / 2, 1 - (1 - level) / 2])
    for name in protocol['variants']:
        choices = z[f'{name}_choices']
        assert np.array_equal(choices, z[f'{name}_predictions'].argmax(2))
        actual = v[np.arange(400)[:, None], choices, np.arange(5)[None, :]]
        assert np.array_equal(actual, z[f'{name}_scores'])
        q = actual.mean(1)
        gain = q - base
        diff = q - z['Original_scores'].mean(1)
        m = result['methods'][name]
        assert np.isclose(q.mean(), m['eq'])
        assert np.isclose(100 * gain.mean(), m['gain_vs_best_pp'])
        assert np.isclose(100 * diff.mean(), m['gain_vs_original_pp'])
        np.testing.assert_allclose(ci(gain, .95), m['gain_vs_best_ci95_pp'], atol=1e-8)
        np.testing.assert_allclose(ci(diff, .95), m['gain_vs_original_ci95_pp'], atol=1e-8)
        np.testing.assert_allclose(ci(diff, .9875), m['gain_vs_original_ci9875_pp'], atol=1e-8)
        for f in np.unique(z['folds']):
            assert np.isclose(q[z['folds'] == f].mean(), m['by_fold_eq'][str(f)])
        full = v.mean(2)[np.arange(400), z[f'{name}_full_choices']]
        assert np.isclose(full.mean(), m['full_repeat_oof_eq'])
        delta = actual - z['Original_scores']
        switch = choices != z['Original_choices']
        assert int(switch.sum()) == m['switches_vs_original']['rotations']
        assert int((delta > 0).sum()) == m['switches_vs_original']['helped']
        assert int((delta < 0).sum()) == m['switches_vs_original']['harmed']
    embeddings = np.load(OUT / 'EMBEDDINGS.npz', allow_pickle=False)
    assert embeddings['ids'].tolist() == ids
    for name in ['Content', 'Stem', 'Options']:
        assert embeddings[name].shape == (400, 3584)
        assert np.isfinite(embeddings[name]).all()
        assert np.allclose(np.linalg.norm(embeddings[name], axis=1), 1, atol=.005)
    em = json.loads((OUT / 'EMBEDDING_MANIFEST.json').read_text())
    assert sha(OUT / 'EMBEDDINGS.npz') == em['sha256'] and em['truncated'] == 0
    for chunk, digest in em['chunks'].items():
        assert sha(OUT / 'chunks' / chunk) == digest
    record = dict(passed=True, validator_sha256=sha(Path(__file__)),
                  input_hashes=True, embedding_norms_and_hashes=True, selection_argmax=True,
                  observed_scores_recomputed=True, switch_counts=True, means=True,
                  paired_intervals=True, fold_metrics=True, full_repeat_metrics=True,
                  permutation_count=len(result['shuffle']['null_gain_pp']))
    assert record['permutation_count'] == 39
    (OUT / 'INDEPENDENT_VALIDATION.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
