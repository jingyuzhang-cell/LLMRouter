import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import warnings
from unittest.mock import patch
from sklearn.exceptions import ConvergenceWarning
from test_router_v2 import fixture
from router_v2.multiseed import fit_batch, evaluate_batch, aggregate, numeric_summary


class MultiSeedTests(unittest.TestCase):
    def test_duplicate_seeds_rejected_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'distinct'):
            fit_batch(argparse.Namespace(seeds=[42, 42]))

    def test_summary_does_not_select_best_seed_or_average_intervals(self):
        summary = numeric_summary([.1, .3])
        self.assertAlmostEqual(summary['mean'], .2)
        self.assertEqual(summary['per_seed'], [.1, .3])
        self.assertNotIn('ci95', summary)
        self.assertIsNone(numeric_summary([None, .3])['mean'])
        with self.assertRaisesRegex(ValueError, 'Every declared'):
            aggregate([], [42, 43])

    def test_all_seeds_sealed_before_evaluation_and_no_reopen(self):
        with tempfile.TemporaryDirectory() as tmp, warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter('ignore', ConvergenceWarning)
            args, _, _ = fixture(Path(tmp))
            args.seeds = [42, 43]
            args.quality_delta = .01
            fit_batch(args)
            root = Path(args.output)
            for seed in args.seeds:
                self.assertTrue((root/f'seed_{seed}'/'FROZEN.json').exists())
                self.assertFalse((root/f'seed_{seed}'/'TEST_OPENED.json').exists())
            evaluate_batch(argparse.Namespace(output=args.output))
            summary = json.loads((root/'SUMMARY.json').read_text())
            self.assertEqual(summary['seeds'], [42, 43])
            self.assertEqual(summary['n_test'], 16)
            self.assertEqual(summary['role'], 'synthetic_smoke')
            self.assertEqual(len(summary['result_sha256']), 2)
            for row in summary['sweep']:
                self.assertEqual(len(row['metrics']['quality']['per_seed']), 2)
            with self.assertRaisesRegex(ValueError, 'already attempted'):
                evaluate_batch(argparse.Namespace(output=args.output))

    def test_later_seed_corruption_blocks_first_seed(self):
        with tempfile.TemporaryDirectory() as tmp, warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter('ignore', ConvergenceWarning)
            args, _, _ = fixture(Path(tmp))
            args.seeds = [42, 43]
            args.quality_delta = 0.
            fit_batch(args)
            root = Path(args.output)
            (root/'seed_43'/'SELECTION.json').write_text('{}')
            with patch('router_v2.multiseed.experiment.evaluate') as evaluate:
                with self.assertRaisesRegex(ValueError, 'Seed artifact changed'):
                    evaluate_batch(argparse.Namespace(output=args.output))
                evaluate.assert_not_called()
            self.assertFalse((root/'BATCH_TEST_OPENED.json').exists())
            self.assertFalse((root/'seed_42'/'TEST_OPENED.json').exists())

    def test_interrupted_evaluation_keeps_batch_marker(self):
        with tempfile.TemporaryDirectory() as tmp, warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter('ignore', ConvergenceWarning)
            args, _, _ = fixture(Path(tmp))
            args.seeds = [42, 43]
            args.quality_delta = 0.
            fit_batch(args)
            root = Path(args.output)
            with patch('router_v2.multiseed.experiment.evaluate', side_effect=RuntimeError('interrupted')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    evaluate_batch(argparse.Namespace(output=args.output))
            self.assertTrue((root/'BATCH_TEST_OPENED.json').exists())
            self.assertFalse((root/'SUMMARY.json').exists())


if __name__ == '__main__':
    unittest.main()
