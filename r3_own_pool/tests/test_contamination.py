import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from router_v2.integrity import fold_cost_profiles, require_valid_quality, prompt_groups
from router_v2.run_repeat_stability import score_answer, bind_panel, aggregate, sha
from router_v2.data import verify_gate
from test_router_v2 import fixture


class ContaminationTests(unittest.TestCase):
    def test_costs_of_held_fold_cannot_change_its_decisions(self):
        from router_v2.effective_gap_tieaware import tieaware_choice
        costs=np.arange(48,dtype=float).reshape(12,4)+1
        folds=np.arange(12)%3
        before=fold_cost_profiles(costs,folds)
        costs[folds==0]=costs[folds==0,::-1]*100
        after=fold_cost_profiles(costs,folds)
        np.testing.assert_array_equal(before[folds==0],after[folds==0])
        pred=np.ones((4,4))
        np.testing.assert_array_equal(tieaware_choice(pred,before[folds==0],.01),tieaware_choice(pred,after[folds==0],.01))

    def test_failed_generation_never_valid_quality(self):
        with self.assertRaises(ValueError):
            require_valid_quality({'status':'failed','quality':{'final':0}})
        self.assertIsNone(score_answer({'dataset':'gsm8k','ground_truth':'42'},None,'failed')['quality'])

    def test_blind_panel_missing_gold_fails_instead_of_zero(self):
        with self.assertRaisesRegex(ValueError,'ground truth'):
            score_answer({'dataset':'gsm8k'},'The answer is 42.','ok')

    def test_truncated_delivered_answer_is_scored(self):
        row={'dataset':'gsm8k','ground_truth':'42'}
        result=score_answer(row,'The answer is 42.','truncated')
        self.assertEqual(result['quality'],1.)

    def test_bind_gold_without_leaking_it_into_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,_,_=fixture(Path(tmp))
            path=Path(args.cohort)/'queries.jsonl'
            rows=[json.loads(l) for l in path.read_text().split('\n')]
            for row in rows:row['ground_truth']='42'
            path.write_text('\n'.join(map(json.dumps,rows)))
            m=Path(args.cohort)/'MANIFEST.json';manifest=json.loads(m.read_text());manifest['query_sha256']=sha(path);m.write_text(json.dumps(manifest))
            panel=[{k:rows[0][k] for k in ('query_id','query','dataset','task_type')}]
            bound=bind_panel(panel,args.cohort)
            self.assertEqual(bound[0]['ground_truth'],'42')
            self.assertEqual(bound[0]['query'],panel[0]['query'])
            with self.assertRaisesRegex(ValueError,'train query'): bind_panel([rows[-1]],args.cohort)

    def test_duplicate_repeats_do_not_inflate_sample_size(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root=Path(tmp);panel=root/'PANEL.jsonl'
            panel.write_text(json.dumps(dict(query_id='q',panel_index=0,dataset='gsm8k',task_type='math',strata=[]))+'\n')
            row=dict(query_id='q',slot='large',repeat_index=0,label_protocol_version=2,
                     cohort_sha256=sha(Path(__file__).resolve().parents[1]/'data/cohort_full_v2/queries.jsonl'),
                     panel_sha256=sha(panel),scorer_sha256=sha(Path(__file__).resolve().parents[1]/'router_v2/run_repeat_stability.py'),
                     temperature=.7,top_p=1.,status='ok',quality=1.,evaluation_status='scored')
            (root/'large.jsonl').write_text((json.dumps(row)+'\n')*2)
            args=argparse.Namespace(output=str(root),panel=str(panel),temperature=.7,top_p=1.,repeats=5,stable_threshold=.8)
            with self.assertRaisesRegex(ValueError,'Duplicate repeat'):aggregate(args)
            row['status']='failed';row['quality']=0
            (root/'large.jsonl').write_text(json.dumps(row)+'\n')
            aggregate(args)
            summary=json.loads((root/'LABEL_SUMMARY.json').read_text())
            self.assertEqual(summary['n_complete'],0);self.assertEqual(summary['invalid_repeats_excluded'],1)
            self.assertTrue((root/'stable_pairs.jsonl').exists())
            self.assertEqual((root/'stable_pairs.jsonl').read_text(),'')

    def test_known_exposure_cannot_be_overridden_by_true_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,_,gate=fixture(Path(tmp));gate['role']='development'
            Path(args.gate).write_text(json.dumps(gate))
            with patch('router_v2.data.known_exposure',return_value=({'q56'},set(),[])):
                with self.assertRaisesRegex(ValueError,'prior test exposure'): verify_gate(args.gate,args.outcomes,args.cohort)

    def test_normalized_duplicates_share_group(self):
        cohort={'a':{'query':'Solve the example 123'},'b':{'query':' Solve  THE example 123 '},'c':{'query':'Completely different sentence'}}
        groups,_=prompt_groups(cohort)
        self.assertEqual(groups['a'],groups['b']);self.assertNotEqual(groups['a'],groups['c'])

if __name__=='__main__':unittest.main()
