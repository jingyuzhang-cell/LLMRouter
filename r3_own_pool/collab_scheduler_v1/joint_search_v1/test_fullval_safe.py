import tempfile
import unittest
from pathlib import Path
from .fullval_runner import run
from collab_scheduler_v1.fault30_cache_accounting_tests import make_task

class Backend:
    OUT=None
    def __init__(self,missing=False):self.starts=0;self.stops=0;self.calls=0;self.missing=missing
    def start_model(self,m):self.starts+=1;return object(),object(),0
    def stop_model(self,p,l):self.stops+=1
    def call_model(self,m,p):
        self.calls+=1
        return dict(status='delivered',answer='{"value":4.0}',usage=None if self.missing else dict(prompt_tokens=60,completion_tokens=40,total_tokens=100))

class ValidationTests(unittest.TestCase):
    def trial(self,missing=False,cap=30):
        with tempfile.TemporaryDirectory() as tmp:
            b=Backend(missing)
            m=dict(tasks=[make_task()],models=dict(medium='m',large='l',coder='c'),caps=dict(new_request_attempts=cap,new_total_tokens=30000,wall_seconds=3600,request_token_reservation=8192,max_output_tokens=512,logical_calls_per_task_config_state=12))
            r=run(m,Path(tmp)/'run',b)
            self.assertEqual(b.starts,b.stops)
            self.assertEqual(r['requests'],b.calls)
            self.assertIsNone(b.OUT)
            return r
    def test_full_four_nodes_and_cache_and_actual_ledger(self):
        r=self.trial();self.assertEqual(r['status'],'COMPLETE');self.assertTrue(r['full_completed']);self.assertFalse(r['pending'])
    def test_failure_retains_reservation_stops_once(self):
        r=self.trial(missing=True);self.assertEqual(r['requests'],1);self.assertEqual(r['tokens_charged_with_pending'],8192);self.assertEqual(r['full_status'],'FULL_UNVERIFIED')
    def test_global_cap_before_dispatch(self):
        r=self.trial(cap=4);self.assertEqual(r['requests'],4);self.assertEqual(r['status'],'VALIDATION_INCOMPLETE');self.assertEqual(r['full_status'],'FULL_UNVERIFIED')

if __name__=='__main__':unittest.main()
