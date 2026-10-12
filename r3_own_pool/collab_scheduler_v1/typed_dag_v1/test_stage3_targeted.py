import json,tempfile,unittest
from pathlib import Path
from .coverage_review import parse_review,review_schema,ReviewError
from .adapters import fixed_financial_graph
from .producer_plan import compile_producer_plan
from .semantic_validation import validate_semantic_plan
from .fresh_acceptance import ScopedBudget
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun

class TargetedTests(unittest.TestCase):
 def test_saved_candidates_exact_refs(self):
  p=Path(__file__).parent/'stage3_producer_fresh_real_01/HTTP_OUTPUTS.jsonl'
  rows=[json.loads(l) for l in p.read_text().splitlines()]
  for r in rows[:2]:
   plan=json.loads(r['data']['choices'][0]['message']['content']);compiled,_=compile_producer_plan(plan)
   with self.assertRaises(ValueError):validate_semantic_plan(compiled)
   self.assertIn('n1_facts_0',compiled['nodes'][1]['dependencies'])
  compiled,_=compile_producer_plan(json.loads(rows[2]['data']['choices'][0]['message']['content']))
  validate_semantic_plan(compiled)
 def test_saved_review_truncation(self):
  rows=[json.loads(l) for l in (Path(__file__).parent/'stage3_producer_fresh_real_01/HTTP_OUTPUTS.jsonl').read_text().splitlines()]
  c=rows[3]['data']['choices'][0]
  with self.assertRaises(ReviewError) as e:parse_review(c['message']['content'],fixed_financial_graph('t'),{'answer':'answer'},c['finish_reason'])
  self.assertEqual(e.exception.feedback['error_code'],'SEMANTIC_REVIEW_TRUNCATED')
 def test_review_format(self):
  with self.assertRaises(ReviewError) as e:parse_review('{',fixed_financial_graph('t'),{'answer':'answer'})
  self.assertEqual(e.exception.feedback['error_code'],'SEMANTIC_REVIEW_FORMAT')
 def test_review_schema(self):
  with self.assertRaises(ReviewError) as e:parse_review('{}',fixed_financial_graph('t'),{'answer':'answer'})
  self.assertEqual(e.exception.feedback['error_code'],'SEMANTIC_REVIEW_SCHEMA')
 def test_review_pass(self):
  r=dict(status='PASS',error_code='NONE',node_refs=[],evidence='All operands supplied.',replan=False)
  self.assertEqual(parse_review(json.dumps(r),fixed_financial_graph('t'),{'answer':'answer'}),r)
 def test_review_fail(self):
  r=dict(status='FAIL',error_code='SOURCE_MISSING',node_refs=['e1'],evidence='Required source absent.',replan=True)
  with self.assertRaises(ReviewError) as e:parse_review(json.dumps(r),fixed_financial_graph('t'),{'answer':'answer'})
  self.assertEqual(e.exception.feedback['error_code'],'SEMANTIC_REVIEW_REJECTED')
 def test_review_false_pass(self):
  with self.assertRaises(ReviewError):parse_review(json.dumps(dict(status='PASS',error_code='NONE',node_refs=[],evidence='',replan=True)),fixed_financial_graph('t'),{'answer':'answer'})
 def test_preflight_historical_block_without_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   b=ScopedBudget(Path(d));b.select('t','generation');b.buckets[('t','generation')]=3913;b.charged=b.actual_tokens=3913
   with self.assertRaises(StopRun):b.preflight(2481,future_requests=5)
   self.assertEqual(b.attempts,0)
 def test_unknown_usage_and_execution_protection(self):
  with tempfile.TemporaryDirectory() as d:
   b=ScopedBudget(Path(d));b.select('t','generation');b.next_reservation=100;b.reserve('x');b.caps['new_total_tokens']=6100
   with self.assertRaises(StopRun):b.preflight(1)
   self.assertEqual(b.charged,100)
 def test_future_tokens(self):
  with tempfile.TemporaryDirectory() as d:
   b=ScopedBudget(Path(d));b.select('t','generation')
   with self.assertRaises(StopRun):b.preflight(4000,future_tokens=2001)
 def test_future_requests(self):
  with tempfile.TemporaryDirectory() as d:
   b=ScopedBudget(Path(d));b.select('t','generation');b.task_attempts['t']=8
   with self.assertRaises(StopRun):b.preflight(100,future_requests=5)
 def test_wall(self):
  with tempfile.TemporaryDirectory() as d:
   b=ScopedBudget(Path(d));b.select('t','generation');b.clock=lambda:b.start+1190
   with self.assertRaises(StopRun):b.preflight(100,min_wall_s=30)
