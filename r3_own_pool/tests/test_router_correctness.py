import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

spec = importlib.util.spec_from_file_location('router', Path(__file__).resolve().parents[1] / 'train_router.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class RouterCorrectness(unittest.TestCase):
    def test_deterministic_inference_and_training_restored(self):
        model = r.HybridUtilityRouter(q_dim=8)
        x = np.random.default_rng(1).normal(size=(12, 8)).astype('float32')
        np.testing.assert_array_equal(model.predict_all(x), model.predict_all(x))
        self.assertTrue(model.training)
        self.assertTrue(((model.predict_all(x) >= 0) & (model.predict_all(x) <= 1)).all())

    def test_full_entrypoint_rejects_obsolete_protocol(self):
        with patch('sys.argv', ['router', '--frozen', 'full_v1']):
            with self.assertRaisesRegex(ValueError, '3500/750/750'):
                r.main()

    def test_end_to_end_synthetic_pilot(self):
        rng = np.random.default_rng(7)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fr = root / 'data/frozen'
            fr.mkdir(parents=True)
            rows = []
            for i in range(80):
                rows.append(dict(query_id=str(i), query=f'query {i}', dataset='synthetic', task_type='math',
                    responses=[dict(slot=s, quality={'final':float(rng.integers(0,2))},
                        cost={'usd':0.0}, latency={'total_ms':float(j+1)}) for j,s in enumerate(r.SLOTS)]))
            (fr/'pilot_v1.jsonl').write_text('\n'.join(map(json.dumps, rows)))
            (fr/'split.json').write_text(json.dumps({'train':list(map(str,range(64))), 'test':list(map(str,range(64,80)))}))
            np.save(fr/'pilot_v1_emb.npy', rng.normal(size=(80,8)).astype('float32'))
            original = r.HybridUtilityRouter
            original_fit = original.fit
            def factory(**kw):
                return original(q_dim=8, **kw)
            def short_fit(self, X, M, Y, **kw):
                return original_fit(self, X, M, Y, epochs=1)
            with patch.object(r, 'R', root), patch.object(r, 'HybridUtilityRouter', factory), patch.object(original, 'fit', short_fit), patch('sys.argv',['router']):
                r.main()
            result = json.loads((root/'ROUTER_RESULT_pilot_v1.json').read_text())
            self.assertEqual(len(result['sweep']),24)
            self.assertTrue(np.isfinite([p['profile_utility'] for p in result['sweep']]).all())
            self.assertIn('Hybrid(lam=0)',result['methods'])
            self.assertTrue((root/'ROUTER_PREDICTIONS_pilot_v1.npz').exists())

if __name__ == '__main__':
    unittest.main()
