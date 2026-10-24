import copy,unittest
from pathlib import Path
from .recovery_feedback_data import export_e2,validate_rows,predict_before
ROOT=Path(__file__).resolve().parents[1]
class Tests(unittest.TestCase):
 def setUp(self):self.rows=export_e2(ROOT/'recovery_mechanism_probe_v1/REAL_RUN_20261014_165304');self.features={k:self.rows[0][k] for k in ['pool','model','operation','parameters_group','task_type','cohort']}
 def test_real_rows_and_correct_latency_target(self):
  validate_rows(self.rows);self.assertEqual(len(self.rows),2);self.assertEqual(len({r['uid'] for r in self.rows}),1);self.assertTrue(all(r['quality']==1 for r in self.rows));self.assertFalse(any(r['end_to_end_label'] for r in self.rows));self.assertGreater(self.rows[0]['latency_s'],self.rows[0]['api_latency_s'][0])
 def test_one_task_not_calibrated(self):
  r=predict_before(self.rows,self.features,self.rows[0]['label_available_utc']+1);self.assertEqual(r['status'],'INSUFFICIENT_DATA');self.assertEqual(r['independent_training_tasks'],1);self.assertIsNone(r['online_choice']);self.assertIsNone(r['admitted_quality_probability']);self.assertIsNone(r['admitted_p90_seconds'])
 def test_before_feedback_no_posthoc_decision(self):
  r=predict_before(self.rows,self.features,self.rows[0]['label_available_utc']);self.assertEqual(r['independent_training_tasks'],0)
 def test_current_task_excluded(self):
  f=dict(self.features,uid=self.rows[0]['uid']);r=predict_before(self.rows,f,self.rows[0]['label_available_utc']+1);self.assertEqual(r['independent_training_tasks'],0)
 def test_no_gold_or_realized_usage_as_features(self):
  for field in ['gold','quality','output_tokens','fee_estimate']:
   with self.assertRaises(ValueError):predict_before(self.rows,dict(self.features,**{field:1}),1e20)
 def test_other_cohort_not_pooled(self):
  f=dict(self.features,cohort='capital_natural_upstream');r=predict_before(self.rows,f,1e20);self.assertEqual(r['independent_training_tasks'],0)
 def test_duplicates_and_tampered_provenance_rejected(self):
  with self.assertRaises(ValueError):validate_rows(self.rows+self.rows)
  rows=copy.deepcopy(self.rows);key=next(iter(rows[0]['source_files_sha256']));rows[0]['source_files_sha256'][key]='0'*64
  with self.assertRaises(ValueError):validate_rows(rows)
 def test_false_quality_label_kept_not_filtered(self):
  rows=copy.deepcopy(self.rows);rows[0]['quality']=0;r=predict_before(rows,self.features,1e20);self.assertEqual(r['diagnostics']['quality_frequency'],0);self.assertEqual(r['independent_training_tasks'],1)
if __name__=='__main__':unittest.main()
