import argparse
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import warnings
from unittest.mock import patch
import numpy as np
import torch
from sklearn.exceptions import ConvergenceWarning
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from router_v2.core import rank_loss, route, scales_from_train, evaluate_policy, select_operating_point, zero_mixture
from router_v2.data import sha, load_cohort, load_outcomes, matrix, verify_gate, read_rows
from router_v2.experiment import fit, evaluate
from router_v2.freeze import freeze as freeze_v2


def fixture(root):
    cohort = root/'cohort'
    cohort.mkdir()
    rows = [dict(query_id=f'q{i}', query=f'synthetic task number {i} feature {i%7}',dataset='synthetic',task_type='math') for i in range(72)]
    split = dict(train=[r['query_id'] for r in rows[:40]], validation=[r['query_id'] for r in rows[40:56]], test=[r['query_id'] for r in rows[56:]])
    (cohort/'queries.jsonl').write_text('\n'.join(map(json.dumps,rows)))
    (cohort/'split.json').write_text(json.dumps(split))
    (cohort/'MANIFEST.json').write_text(json.dumps(dict(query_sha256=sha(cohort/'queries.jsonl'),split_counts={k:len(v) for k,v in split.items()})))
    rng = np.random.default_rng(42)
    x = rng.normal(size=(72,8)).astype('float32')
    np.savez(root/'embedding.npz',ids=np.array([r['query_id'] for r in rows]),vectors=x,query_sha256=sha(cohort/'queries.jsonl'))
    records = []
    for i,row in enumerate(rows):
        responses=[]
        for j,slot in enumerate(('small','medium','large','reasoning')):
            responses.append(dict(slot=slot,status='ok',quality={'final':float((x[i,j]>0)*.8+.1)},
                cost={'usd':float((j+1)*.001)},latency={'total_ms':float((j+1)*10)}))
        records.append(dict(**row,responses=responses))
    outcomes = root/'outcomes.jsonl'
    outcomes.write_text('\n'.join(map(json.dumps,records)))
    gate = dict(role='synthetic_smoke',outcomes_sha256=sha(outcomes),queries_sha256=sha(cohort/'queries.jsonl'),
        split_sha256=sha(cohort/'split.json'),scoring_complete=True,failures_accounted=True,
        cost_provenance_verified=True,code_sandbox_verified=True,holdout_uncontaminated=True,
        currency='USD',cost_basis='synthetic units, not measured dollars')
    (root/'gate.json').write_text(json.dumps(gate))
    return argparse.Namespace(cohort=str(cohort),outcomes=str(outcomes),gate=str(root/'gate.json'),
         embeddings=str(root/'embedding.npz'),output=str(root/'run'),seed=42,epochs=1),records,gate


class V2Tests(unittest.TestCase):
    def test_jsonl_unicode_line_separator_is_not_record_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.jsonl'
            row={'query': 'first'+chr(0x2028)+'second'}
            path.write_text(json.dumps(row,ensure_ascii=False)+'\n')
            self.assertEqual(read_rows(path),[row])

    def test_freeze_preserves_split_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,records,gate=fixture(Path(tmp))
            dest=freeze_v2(args.cohort,args.outcomes,args.gate,Path(tmp)/'frozen')
            self.assertEqual(sha(dest/'split.json'),sha(Path(args.cohort)/'split.json'))
            self.assertEqual(sha(dest/'outcomes.jsonl'),sha(args.outcomes))
            with self.assertRaises(FileExistsError):
                freeze_v2(args.cohort,args.outcomes,args.gate,dest)

    def test_legacy_full_freeze_rejected_before_read(self):
        path=Path(__file__).resolve().parents[1]/'collect/freeze.py'
        spec=importlib.util.spec_from_file_location('legacy_freeze_for_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with self.assertRaisesRegex(ValueError,'pilot-only'):
            module.freeze('full_v1')

    def test_opportunity_analysis_filters_before_outcome_access(self):
        path=Path(__file__).resolve().parents[1]/'analyze_full.py'
        spec=importlib.util.spec_from_file_location('development_analysis_for_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            args,records,gate=fixture(Path(tmp))
            # Invalid test response container must never be inspected by train analysis.
            for rec in records[40:]:
                rec['responses']=None
            Path(args.outcomes).write_text('\n'.join(map(json.dumps,records)))
            frame=module.load(Path(args.outcomes),{r['query_id'] for r in records[:40]})
            self.assertEqual(len(frame),40)

    def test_ties_and_no_pair_backward(self):
        pred=torch.zeros((2,4),requires_grad=True)
        loss=rank_loss(pred,torch.ones((2,4)))
        loss.backward()
        self.assertEqual(float(loss.detach()),0)
        np.testing.assert_array_equal(pred.grad.numpy(),np.zeros((2,4)))

    def test_pair_count_normalization(self):
        pred=torch.zeros((2,4),requires_grad=True)
        target=torch.tensor([[1.,0.,0.,0.],[3.,2.,1.,0.]])
        self.assertAlmostEqual(float(rank_loss(pred,target).detach()),.05,places=6)

    def test_zero_gap_and_zero_resource_scales(self):
        y=np.zeros((10,4,3));y[:,:,0]=1
        scales=scales_from_train(y)
        self.assertTrue(np.isfinite(scales).all())
        self.assertIsNone(evaluate_policy(y,np.zeros(10,dtype=int),y,(0,0),scales)['gap_recovery'])

    def test_validation_fallback_and_fixed_mixture(self):
        y=np.ones((12,4,3));y[:,0,0]=1;y[:,1:,0]=0
        pred=y.copy();pred[:,:,0]=pred[:,:,0][:,::-1]
        point=select_operating_point(pred,y,y,np.ones(3))
        self.assertEqual(point['kind'],'best_single')
        p=zero_mixture(y,0,np.ones(3))
        self.assertAlmostEqual(p[0],1)

    def test_input_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, records, gate=fixture(Path(tmp))
            cohort,split=load_cohort(args.cohort)
            by=load_outcomes(args.outcomes,cohort)
            by['q0']['responses'][0]['quality']['final']=None
            with self.assertRaisesRegex(ValueError,'Missing/invalid'):
                matrix(by,split['train'])
            gate['cost_provenance_verified']=False
            Path(args.gate).write_text(json.dumps(gate))
            with self.assertRaisesRegex(ValueError,'cost_provenance'):
                verify_gate(args.gate,args.outcomes,args.cohort)
            split['test'][0]=split['train'][0]
            (Path(args.cohort)/'split.json').write_text(json.dumps(split))
            with self.assertRaisesRegex(ValueError,'overlap'):
                load_cohort(args.cohort)

    def test_end_to_end_and_holdout_invariance(self):
        with tempfile.TemporaryDirectory() as tmp, warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter('ignore',ConvergenceWarning)
            args,records,gate=fixture(Path(tmp))
            fit(args)
            first=Path(args.output)
            self.assertFalse((first/'TEST_OPENED.json').exists())
            predictions=np.load(first/'PREDICTIONS.npz')
            selection=json.loads((first/'SELECTION.json').read_text())
            evaluate(args)
            result=json.loads((first/'RESULTS.json').read_text())
            self.assertEqual(result['n_test'],16)
            self.assertEqual(sum(r['method']=='Hybrid' for r in result['sweep']),24)
            self.assertEqual(result['role'],'synthetic_smoke')
            with self.assertRaises(FileExistsError):
                evaluate(args)
            # Changing only held-out labels/resources must not change fit or validation selection.
            for rec in records[56:]:
                for response in rec['responses']:
                    response['quality']['final']=1-response['quality']['final']
                    response['cost']['usd']*=1000
                    response['latency']['total_ms']*=1000
            Path(args.outcomes).write_text('\n'.join(map(json.dumps,records)))
            gate['outcomes_sha256']=sha(args.outcomes)
            Path(args.gate).write_text(json.dumps(gate))
            args.output=str(Path(tmp)/'second')
            fit(args)
            other=np.load(Path(args.output)/'PREDICTIONS.npz')
            for k in predictions.files:
                np.testing.assert_array_equal(predictions[k],other[k],err_msg=k)
            next_selection=json.loads((Path(args.output)/'SELECTION.json').read_text())
            selection.pop('timing');next_selection.pop('timing')
            self.assertEqual(selection,next_selection)
            # Sealed policy mutation is rejected before test is opened.
            (Path(args.output)/'SELECTION.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'artifact changed'):
                evaluate(args)
            self.assertFalse((Path(args.output)/'TEST_OPENED.json').exists())

if __name__=='__main__':
    unittest.main()
