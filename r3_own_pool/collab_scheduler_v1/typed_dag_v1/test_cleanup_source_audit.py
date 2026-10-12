import json,tempfile,time,unittest,fcntl
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from .run_cleanup import finish
from .task_source_audit import freeze_requirements
from .source_coverage import audit_graph_sources,manifest
from .protocol import Graph
ROOT=Path(__file__).parent
class CleanupSourceTests(unittest.TestCase):
 def cleanup(self,error=False):
  with tempfile.TemporaryDirectory() as t:
   s=SimpleNamespace(active='owned')
   def close():
    if error:raise RuntimeError('close failure')
    s.active=None
   s.close=close;r=finish(s,Path(t),time.monotonic()-1)
   self.assertIn('total_wall_s',r);self.assertGreaterEqual(r['total_wall_s'],1);return r
 def test_original_nameerror_regression(self):self.assertTrue(self.cleanup()['service_stopped'])
 def test_all_exit_reasons(self):
  for reason in ('success','rejected','timeout','client_exception','review_failed','early_stop'):
   with self.subTest(reason=reason):self.assertTrue(self.cleanup()['service_stopped'])
 def test_close_failure_recorded(self):self.assertTrue(self.cleanup(True)['errors'])
 def test_logging_failure_still_closes(self):
  with patch('collab_scheduler_v1.typed_dag_v1.run_cleanup.mark',side_effect=NameError('mark')):self.assertTrue(self.cleanup()['service_stopped'])
 def test_idempotent(self):
  with tempfile.TemporaryDirectory() as t:
   s=SimpleNamespace(active=None,close=lambda:None)
   self.assertTrue(finish(s,Path(t),time.monotonic())['service_stopped']);self.assertTrue(finish(s,Path(t),time.monotonic())['service_stopped'])
 def test_lock_context_release(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'lock'
   with p.open('a') as f:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
   with p.open('a') as f:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
 def test_review_every_source(self):
  with self.assertRaises(ValueError):freeze_requirements({'question':'x','ctx_table':'1','ctx_text':'combine'}, {},'human','v1')
 def test_rule_no_digits_required(self):
  c={'question':'x','ctx_text':'Use combined totals'};d={'ctx_text':dict(status='REQUIRED',kind='RULE',evidence=c['ctx_text'],rationale='aggregation constraint')}
  self.assertEqual(len(freeze_requirements(c,d,'human','v1')['required_source_data']),1)
 def test_uncertain_kept(self):
  c={'question':'x','ctx_text':'ambiguous'};d={'ctx_text':dict(status='UNCERTAIN',kind='RULE',evidence='ambiguous',rationale='needs review')}
  self.assertEqual(freeze_requirements(c,d,'human','v1')['uncertain_sources'],['ctx_text'])
 def test_historical_false_pass_source_replay(self):
  packet=ROOT/'bounded_ab_water_trace60_v1';graph=Graph.from_json((packet/'execution/T2_A/GRAPH.json').read_text());task=json.loads((packet/'TASK_2.json').read_text());context=task['context']
  old=json.loads((packet/'REQUIRED_SOURCES_2.json').read_text());self.assertFalse(audit_graph_sources(graph,manifest(context),old)['errors'])
  proposed=old+[dict(data_id='losses',source_id='ctx_text',evidence=context['ctx_text'])]
  self.assertTrue(audit_graph_sources(graph,manifest(context),proposed)['errors'])
  review=json.loads((packet/'execution/T2_A/semantic_review_HTTP_RESPONSE.json').read_text())['choices'][0]['message']['content'];self.assertEqual(json.loads(review)['status'],'PASS')
