import json
import unittest
from unittest.mock import patch
import numpy as np
from .label_repair_plan import win,pair_eig,select_fold_local,audit_counts
from .collect_label_repair import request_once,score


class RepairTests(unittest.TestCase):
 def test_information_gain_is_valid_and_symmetric(self):
  value=pair_eig(2,3)
  self.assertGreaterEqual(value,-1e-8);self.assertLessEqual(value,1)
  self.assertAlmostEqual(value,pair_eig(3,2),places=6)
  self.assertEqual(win(5,5,5,5),.5)

 def test_fold_local_selection_ignores_outside_order(self):
  rows=[{'query_id':str(i)} for i in range(100)]
  folds=[dict(fold=0,development_ids=[str(i) for i in range(60)],test_ids=[str(i) for i in range(60,100)])]
  first,_=select_fold_local(rows,folds)
  reordered=rows[60:]+rows[:60]
  second,_=select_fold_local(reordered,folds)
  self.assertEqual(first,second)
  self.assertFalse(set(first[0]['repair_training_ids'])&set(folds[0]['test_ids']))

 def test_audit_uses_actual_repeat_count(self):
  before=audit_counts((5,5,5,5),5)
  after=audit_counts((15,15,15,15),15)
  self.assertEqual(after['repeats'],15)
  self.assertGreater(after['p_tie_best'],before['p_tie_best'])
  self.assertEqual(after['p_win'],[.5,.5,.5])

 def test_delivered_parse_failure_not_transport_missing(self):
  row={'ground_truth':'C'}
  self.assertIsNone(score(row,dict(status='failed',answer=None))['quality'])
  self.assertEqual(score(row,dict(status='truncated',answer='No explicit choice.'))['quality'],0.)
  self.assertEqual(score(row,dict(status='truncated',answer='Answer: C'))['quality'],1.)

 def test_api_payload_excludes_answer_key(self):
  captured={}
  class Reply:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self):return json.dumps({'choices':[{'message':{'content':'Answer: C'},'finish_reason':'stop'}],'model':'fixed-model','usage':{'completion_tokens':4}}).encode()
  class Opener:
   def open(self,req,timeout):captured.update(json.loads(req.data));return Reply()
  with patch('urllib.request.build_opener',return_value=Opener()):
   out=request_once({'base_url':'https://example.invalid/v1','api_key':'dummy'},'fixed-model',{'query':'Public question','ground_truth':'SECRET_KEY'})
  self.assertNotIn('SECRET_KEY',json.dumps(captured))
  self.assertEqual(captured['messages'],[{'role':'user','content':'Public question'}])
  self.assertEqual(captured['max_tokens'],2048)
  self.assertEqual(out['status'],'ok')


if __name__=='__main__':unittest.main()
