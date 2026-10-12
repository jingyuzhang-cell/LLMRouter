import tempfile,unittest
from pathlib import Path
from .fresh_acceptance import ScopedBudget,CAPS
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun
class BudgetTests(unittest.TestCase):
 def make(self):
  d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);return ScopedBudget(Path(d.name))
 def test_generation_cannot_borrow_execution(self):
  b=self.make();b.select('a','generation');b.next_reservation=6000;b.reserve('one');b.next_reservation=1
  with self.assertRaises(StopRun):b.reserve('two')
  b.select('a','execution');b.next_reservation=6000;b.reserve('exec');self.assertEqual(b.charged,12000)
 def test_unknown_usage_retains_phase_reserve(self):
  b=self.make();b.select('a','generation');b.next_reservation=100;b.reserve('one')
  with self.assertRaises(StopRun):b.settle(1,{'usage':{},'status':'delivered'})
  self.assertEqual(b.charged,100);self.assertEqual(b.buckets[('a','generation')],100)
 def test_usage_refund_both_global_and_phase(self):
  b=self.make();b.select('a','execution');b.next_reservation=100;i=b.reserve('one');b.settle(i,dict(status='delivered',usage=dict(prompt_tokens=20,completion_tokens=10,total_tokens=30)))
  self.assertEqual(b.charged,30);self.assertEqual(b.buckets[('a','execution')],30)
 def test_task_and_global_request_caps(self):
  b=self.make();b.select('a','generation');b.next_reservation=1
  for _ in range(12):b.reserve('one')
  with self.assertRaises(StopRun):b.reserve('thirteen')
  b.select('b','generation')
  for _ in range(12):b.reserve('two')
  self.assertEqual(b.attempts,24)
  b.select('c','generation')
  with self.assertRaises(StopRun):b.reserve('global-excess')
