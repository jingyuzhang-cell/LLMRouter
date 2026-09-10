import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from test_router_v2 import fixture
from router_v2.data import sha
from router_v2.diagnose_objective_signal import run


class ObjectiveSignalTests(unittest.TestCase):
    def setup_data(self, root):
        args, records, _ = fixture(root)
        cohort = Path(args.cohort)
        queries = [json.loads(line) for line in (cohort/'queries.jsonl').read_text().splitlines()]
        for row in queries:
            row['dataset'] = 'gsm8k'
        (cohort/'queries.jsonl').write_text('\n'.join(map(json.dumps, queries)))
        manifest = json.loads((cohort/'MANIFEST.json').read_text())
        manifest['query_sha256'] = sha(cohort/'queries.jsonl')
        (cohort/'MANIFEST.json').write_text(json.dumps(manifest))
        with np.load(args.embeddings) as saved:
            data = {key: saved[key] for key in saved.files}
        data['query_sha256'] = sha(cohort/'queries.jsonl')
        np.savez(args.embeddings, **data)
        for row in records:
            row['dataset'] = 'gsm8k'
            for response in row['responses']:
                response['quality'] = dict(final=int(response['quality']['final'] > .5), quality_source='auto')
        path = root/'train.jsonl'
        path.write_text('\n'.join(map(json.dumps, records[:40])))
        return argparse.Namespace(matrix=str(path), cohort=args.cohort, embeddings=args.embeddings, output=str(root/'diagnostic')), records

    def test_original_holdout_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, records = self.setup_data(Path(tmp))
            Path(args.matrix).write_text('\n'.join(map(json.dumps, records[:39] + records[56:57])))
            with self.assertRaisesRegex(ValueError, 'exactly original train'):
                run(args)
            self.assertFalse(Path(args.output).exists())

    def test_fold_predictions_do_not_use_held_fold_labels(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            args, records = self.setup_data(root)
            run(args)
            with np.load(Path(args.output)/'OOF.npz') as saved:
                mask = saved['folds'] == 0
                before = saved['predicted_quality'][mask].copy()
                ids = set(saved['ids'][mask].tolist())
            for row in records[:40]:
                if row['query_id'] in ids:
                    for response in row['responses']:
                        response['quality']['final'] = 1 - response['quality']['final']
            Path(args.matrix).write_text('\n'.join(map(json.dumps, records[:40])))
            args.output = str(root/'perturbed')
            run(args)
            with np.load(Path(args.output)/'OOF.npz') as saved:
                np.testing.assert_array_equal(before, saved['predicted_quality'][mask])


if __name__ == '__main__':
    unittest.main()
