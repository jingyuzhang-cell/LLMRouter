import sys
from pathlib import Path
import tempfile
import json
import unittest
from unittest.mock import patch, MagicMock
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2.diagnose_earlystop import select_epoch, fit_nested
from router_v2 import verify_development_closure as closure
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'collect'))


class ClosureTests(unittest.TestCase):
    def test_epoch_selection_uses_mse_with_earlier_tie_break(self):
        history=[dict(epoch=1,held_mse=.3),dict(epoch=5,held_mse=.2),dict(epoch=10,held_mse=.2)]
        self.assertEqual(select_epoch(history),5)
        with self.assertRaises(ValueError):select_epoch([dict(epoch=1,held_mse=float('nan'))])

    def test_inner_selection_refits_all_training_rows(self):
        x=np.arange(160,dtype='float32').reshape(20,8);y=np.zeros((20,4));xv=np.ones((3,8))
        mock=MagicMock();mock.predict_all.return_value=np.zeros((3,4))
        history=[dict(epoch=1,held_mse=.1),dict(epoch=5,held_mse=.2)]
        with patch('router_v2.diagnose_earlystop.diagnostic_fit',return_value=(None,history,{})) as fit, patch('router_v2.diagnose_earlystop.Router',return_value=mock):
            _,details=fit_nested(x,y,np.array(['a']*10+['b']*10),xv,42)
            self.assertEqual(len(fit.call_args.args[1]),16)
            self.assertEqual(len(fit.call_args.args[3]),4)
            self.assertEqual(details['selected_epochs'],1)
            np.testing.assert_array_equal(mock.fit.call_args.args[0],x)
            self.assertEqual(mock.fit.call_args.kwargs['epochs'],1)
            np.testing.assert_array_equal(mock.predict_all.call_args.args[0],xv)

    def test_validation_cache_response_hash_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data/raw').mkdir(parents=True)
            for name in ('scored_validation_v2','scored_code_validation_v2'):
                (root/'data'/name).mkdir()
            cohort={'v1':dict(query_id='v1',query='synthetic')}
            labels=[]
            for slot in closure.SLOTS:
                raw=dict(query_id='v1',status='ok',answer='synthetic')
                (root/'data/raw'/f'{slot}.jsonl').write_text(json.dumps(raw)+'\n')
                labels.append(dict(query_id='v1',slot=slot,source_sha256=closure.digest(cohort['v1']),response_sha256=closure.digest(raw),quality=1.))
            cache=root/'data/scored_validation_v2/SCORES.jsonl'
            cache.write_text('\n'.join(map(json.dumps,labels))+'\n')
            (root/'data/scored_code_validation_v2/SCORES.jsonl').write_text('')
            out=root/'out';out.mkdir()
            with patch.object(closure,'ROOT',root):
                np.testing.assert_array_equal(closure.validation_quality(['v1'],cohort,out),np.ones((1,4)))
                labels[0]['response_sha256']='invalid'
                cache.write_text('\n'.join(map(json.dumps,labels))+'\n')
                with self.assertRaisesRegex(ValueError,'Missing bound'):
                    closure.validation_quality(['v1'],cohort,out)

if __name__=='__main__':unittest.main()
