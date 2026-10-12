import copy,json,unittest
from .goal_chain_audit import audit_goal_chain
from .test_goal_ir import ir,datum,step
from .test_goal_ir_roles import grouped
from .test_producer_plan import producers
from .test_semantic_ids import CTX
class GoalChainAuditTests(unittest.TestCase):
 def audit(self,p,mode='goal_ir',required=None):return audit_goal_chain(p,mode,CTX,required)
 def codes(self,r):return {e['error_code'] for e in r['errors']}
 def test_legal_three_and_five(self):
  for n in (3,5):
   for p,mode in [(ir(n),'goal_ir'),(grouped(ir(n)),'goal_ir_roles'),(producers(n),'semantic')]:
    r=self.audit(p,mode);self.assertEqual(r['static_status'],'DECLARATIONS_CONSISTENT');self.assertEqual(len(r['reverse_chain']['answer']),n)
    self.assertEqual(r['admission_status'],'REQUIRES_SEMANTIC_REVIEW')
 def test_final_producer_missing(self):
  p=ir();p['final_goal']['outputs'][0]['symbol']='undeclared';r=self.audit(p)
  self.assertIn('IR_GOAL_UNCOVERED',self.codes(r));self.assertEqual(r['final_producers'][0]['status'],'MISSING')
 def test_required_node_not_contributing(self):
  p=producers(5);p['final_outputs']=[dict(name='answer',node_ref='math')];r=self.audit(p,'semantic')
  self.assertIn('FINAL_OUTPUT_CONNECTIVITY',self.codes(r))
 def test_multiple_roots_merge(self):
  r=self.audit(ir(5));self.assertIn('read_text',r['reverse_chain']['answer']);self.assertIn('read',r['reverse_chain']['answer'])
 def test_duplicate_expression_and_missing_goal_both_visible(self):
  p=ir();extra=copy.deepcopy(p['steps'][1]);extra['ref']='other';p['steps'].append(extra);p['final_goal']['outputs'][0]['symbol']='absent'
  r=self.audit(p);self.assertIn('IR_AMBIGUOUS_PRODUCER',self.codes(r));self.assertIn('IR_GOAL_UNCOVERED',self.codes(r))
 def test_expression_producer_missing(self):
  p=ir();p['steps'][-1]['inputs'][-1]['symbol']='absent';r=self.audit(p)
  self.assertIn('IR_MISSING_PRODUCER',self.codes(r))
 def test_operation_output_conflict(self):
  p=ir();p['steps'][1]['operation']='calculate';r=self.audit(p)
  self.assertIn('IR_OPERATION_OUTPUT_TYPE',self.codes(r))
 def test_name_is_not_operation_proof(self):
  p=ir();p['steps'][1]['description']='Calculate a result';r=self.audit(p)
  self.assertEqual(r['static_status'],'DECLARATIONS_CONSISTENT');self.assertEqual(r['operation_intent'],'REQUIRES_SEMANTIC_REVIEW')
 def test_source_missing_and_unknown_distinguished(self):
  p=ir();unknown=self.audit(p);self.assertEqual(unknown['source_coverage']['source_complete'],'PENDING_SEMANTIC_REVIEW')
  required=[dict(data_id='text',source_id='ctx_text',evidence=CTX['ctx_text'])]
  self.assertIn('REQUIRED_SOURCE_MISSING',self.codes(self.audit(p,required=required)))
 def test_cycle_witness(self):
  a=datum('a','verified_value');b=datum('b','verified_value');p=dict(final_goal=dict(description='check',outputs=[dict(name='answer',**a)]),steps=[step('A','verify_value',[b],a),step('B','verify_value',[a],b)])
  r=self.audit(p);self.assertIn('CYCLE',self.codes(r));self.assertTrue(r['cycle_paths'])
 def test_does_not_change_candidate(self):
  p=grouped(ir(5));before=copy.deepcopy(p);r=self.audit(p,'goal_ir_roles');self.assertEqual(p,before);self.assertEqual(r['invented_edges'],0)
