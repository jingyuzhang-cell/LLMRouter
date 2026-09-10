import argparse
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from router_v2.build_clean_splits import make_cell
from router_v2.score_available import digest
from router_v2.run_repeat_stability import done_keys, generate
from router_v2.train_repeat_pair_ma import training_rows, load_repeats


class RepeatExecutionTests(unittest.TestCase):
    def test_transport_zero_is_missing_even_with_matching_cache(self):
        source=dict(query_id='q',dataset='mmlupro',ground_truth='A')
        raw=dict(status='failed',answer=None,error='HTTP 503')
        labels={('q','reasoning',digest(source),digest(raw)):('cache',{'quality':0.})}
        cell=make_cell(source,'reasoning',raw,labels)
        self.assertIsNone(cell['quality']['final'])
        self.assertEqual(cell['evaluation_status'],'infrastructure_failure_missing')

    def test_code_label_cannot_bind_to_different_response(self):
        source=dict(query_id='q',dataset='mbpp',ground_truth='[]')
        raw=dict(status='ok',answer='pass')
        labels={('q','large',digest(source),'wrong_hash'):('cache',{'quality':1.})}
        self.assertIsNone(make_cell(source,'large',raw,labels)['quality']['final'])

    def test_failed_repeat_is_resumable_but_success_is_not_rerolled(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'raw.jsonl'
            rows=[dict(query_id='a',slot='large',repeat_index=0,status='failed'),
                  dict(query_id='b',slot='large',repeat_index=0,status='ok',quality=0)]
            p.write_text('\n'.join(map(json.dumps,rows)))
            self.assertEqual(done_keys(p),{('b','large',0)})

    def test_http_transport_uses_opener_and_does_not_send_gold(self):
        raw=json.dumps({'choices':[{'message':{'content':'42'},'finish_reason':'stop'}],
                        'usage':{'prompt_tokens':2,'completion_tokens':1}}).encode()
        class Response(io.BytesIO):
            pass
        with patch('router_v2.run_repeat_stability.request.build_opener') as factory:
            factory.return_value.open.return_value=Response(raw)
            result=generate({'base_url':'https://example.invalid/v1','api_key':'dummy'},'model',
                            {'query':'Question only','ground_truth':'SECRET_GOLD','task_type':'math'},.7,1.,1)
            request=factory.return_value.open.call_args.args[0]
            self.assertNotIn('SECRET_GOLD',request.data.decode())
            self.assertEqual(result['status'],'ok')

    def test_matched_control_uses_exactly_the_stable_queries(self):
        ids=np.array(['a','b','c']);y=np.array([[0,0,1,0],[0,0,0,1],[0,0,1,1]])
        labels={'a':{'stable_label':'reasoning>large','large_quality_mean':0.,'reasoning_quality_mean':1.},
                'b':{'stable_label':'unstable_or_tie','large_quality_mean':.4,'reasoning_quality_mean':.6},
                'c':{'stable_label':'large>reasoning','large_quality_mean':1.,'reasoning_quality_mean':0.}}
        a,t,_=training_rows(ids,y,set(ids),labels,'stable_pair')
        b,u,_=training_rows(ids,y,set(ids),labels,'old_pair_stable_matched')
        np.testing.assert_array_equal(a,b);np.testing.assert_array_equal(a,[0,2])
        self.assertNotEqual(t[0].argmax(),u[0].argmax())

    def test_incomplete_repeat_labels_block_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'LABEL_SUMMARY.json'
            p.write_text(json.dumps({'panel_sha256':'p','n_complete':0,'n_incomplete':2}))
            with self.assertRaisesRegex(ValueError,'incomplete'):
                load_repeats(tmp,{'files':{'PANEL.jsonl':'p'},'n_panel':2})

if __name__=='__main__':unittest.main()
