import contextlib
import io
from pathlib import Path
import tempfile
import unittest
import numpy as np
import torch
from test_objective_signal import ObjectiveSignalTests
from router_v2.diagnose_objective_signal import run as objective_run
from router_v2.diagnose_rank_signal import load_inputs, train_pair


class RankSignalTests(unittest.TestCase):
    def test_same_seed_training_is_reproducible(self):
        torch.set_num_threads(1)
        rng = np.random.default_rng(7)
        x = rng.normal(size=(12, 8)).astype('float32')
        y = rng.integers(0, 2, size=(12, 4)).astype('float32')
        first = train_pair(x[:8], y[:8], x[8:], 42, 2)
        second = train_pair(x[:8], y[:8], x[8:], 42, 2)
        self.assertEqual(set(first), {'0.0', '0.5'})
        for key in first:
            np.testing.assert_array_equal(first[key], second[key])
            self.assertEqual(first[key].shape, (4, 4))
            self.assertTrue(np.isfinite(first[key]).all())

    def test_reuses_original_folds_and_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            args, _ = ObjectiveSignalTests().setup_data(Path(tmp))
            objective_run(args)
            frozen, x, datasets = load_inputs(args.output)
            self.assertEqual(len(x), 40)
            self.assertEqual(set(frozen['folds']), {0, 1, 2})
            self.assertEqual(set(datasets), {'gsm8k'})
            with (Path(args.output)/'OOF.npz').open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'Source artifact changed'):
                load_inputs(args.output)


if __name__ == '__main__':
    unittest.main()
