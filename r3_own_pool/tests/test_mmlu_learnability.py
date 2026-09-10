import json,tempfile,unittest
from pathlib import Path
import numpy as np
from router_v2.mmlu_learnability import subject_from_query,subject_mean,validate_pairs,metrics

class LearnabilityTests(unittest.TestCase):
 def test_incomplete_panel_blocks_baseline_fitting(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'MANIFEST.json').write_text(json.dumps({'n_panel':400}))
   (p/'DISTRIBUTION_STATUS.json').write_text(json.dumps({'complete':False,'n_complete':27}))
   with self.assertRaisesRegex(ValueError,'P0 incomplete'):validate_pairs(p,p)
 def test_subject_is_extracted_from_query_only(self):
  self.assertEqual(subject_from_query('Answer the following math question. Some text'),'math')
  self.assertEqual(subject_from_query('No category header'),'unknown')
 def test_unseen_subject_uses_only_training_mean(self):
  tr=np.array(['a','a']);y=np.array([.2,.4]);va=np.array(['b','a'])
  np.testing.assert_allclose(subject_mean(tr,y,va),[.3,.3])
 def test_auc_ignores_ties_and_uses_continuous_score(self):
  r=metrics(np.array([-.1,99.,.1]),np.array([-.2,0.,.2]))
  self.assertEqual(r['auc_on_nonzero_empirical_delta'],1.)
  self.assertEqual(r['auc_n'],2)
 def test_auc_single_direction_is_undefined(self):
  self.assertIsNone(metrics(np.array([.1,.2]),np.array([0.,.2]))['auc_on_nonzero_empirical_delta'])
 def test_negative_r2_is_preserved(self):
  r=metrics(np.array([1.,-1.]),np.array([-.2,.2]))
  self.assertLess(r['r2'],0)

if __name__=='__main__':unittest.main()
