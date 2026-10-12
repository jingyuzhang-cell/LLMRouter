import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from .semantic_validation import inspect_semantic_plan,validate_semantic_plan,SemanticErrors,compare_errors,error_signature
from .semantic_ids import assemble_semantic
from .test_semantic_ids import plan,CTX,LoopTests as Fixtures
from .generation import InitialDAGGenerator

class ValidationTests(unittest.TestCase):
 def errors(self,p):return inspect_semantic_plan(p)
 def test_duplicate_ref(self):
  p=plan();p['nodes'][1]['ref']='raw';self.assertIn('AMBIGUOUS_SEMANTIC_REFERENCE',[e['error_code'] for e in self.errors(p)])
 def test_dangling_dependency_and_final(self):
  p=plan();p['nodes'][1]['dependencies']=['missing'];p['final_outputs'][0]['node_ref']='lost'
  e=self.errors(p);self.assertEqual({x['missing_dependency'] for x in e if x['error_code'] in ('DEPENDENCY_REFERENCE','FINAL_OUTPUT_REFERENCE')},{'missing','lost'})
 def test_self_loop_path(self):
  p=plan();p['nodes'][0]['dependencies']=['raw'];self.assertIn(['raw','raw'],[e['cycle_path'] for e in self.errors(p)])
 def test_two_node_cycle(self):
  p=plan();p['nodes'][0]['dependencies']=['math'];self.assertIn(['math','raw','math'],[e['cycle_path'] for e in self.errors(p)])
 def test_three_node_cycle(self):
  p=plan();p['nodes'][0]['dependencies']=['compute'];p['nodes'][2]['dependencies']=['math']
  self.assertIn(['compute','math','raw','compute'],[e['cycle_path'] for e in self.errors(p)])
 def test_duplicate_dependency(self):
  p=plan();p['nodes'][1]['dependencies']=['raw','raw'];self.assertTrue(any(e['error_code']=='DEPENDENCY_FORMAT' for e in self.errors(p)))
 def test_required_producer_missing(self):
  p=plan();p['nodes'][2]['dependencies']=['math'];e=next(e for e in self.errors(p) if e['error_code']=='CONTRACT_UNBINDABLE')
  self.assertIn('facts',e['missing_dependency']['calculate.v1']['missing_or_ambiguous_producers'])
 def test_forward_reference_reordered(self):
  p=plan(5);p['nodes'].reverse();self.assertEqual(self.errors(p),[])
 def test_multiple_roots(self):self.assertEqual(self.errors(plan(5)),[])
 def test_same_name_different_refs(self):
  p=plan(5)
  for n in p['nodes']:n['name']='shared display name'
  self.assertEqual(self.errors(p),[])
 def test_legal_three_and_five(self):
  for size in (3,5):self.assertTrue(validate_semantic_plan(plan(size))['valid'])
 def test_preassembly_interception(self):
  p=plan();p['nodes'][0]['dependencies']=['raw']
  with patch('collab_scheduler_v1.typed_dag_v1.semantic_ids.assemble') as assembly:
   with self.assertRaises(SemanticErrors):assemble_semantic(p,'u',CTX,{'answer':'number'})
   assembly.assert_not_called()
 def test_repeated_error_ignores_format_and_labels(self):
  p=plan();p['nodes'][0]['dependencies']=['compute'];q=json.loads(json.dumps(p,indent=4));q['nodes'].reverse()
  for n in q['nodes']:n['name']='cosmetic change'
  self.assertTrue(compare_errors(self.errors(p),self.errors(q))['no_progress'])
 def test_new_error_not_success(self):
  p=plan();p['nodes'][1]['dependencies']=['absent'];q=plan();q['nodes'][0]['dependencies']=['raw'];comparison=compare_errors(self.errors(p),self.errors(q))
  self.assertFalse(comparison['no_progress']);self.assertTrue(comparison['introduced_errors']);self.assertTrue(self.errors(q))
 def test_feedback_fields(self):
  p=plan();p['nodes'][0]['dependencies']=['math']
  with self.assertRaises(SemanticErrors) as exc:validate_semantic_plan(p)
  self.assertTrue({'error_code','node_ref','related_refs','cycle_path','missing_dependency','expected_constraint','actual_value','errors','error_signature'}<=set(exc.exception.feedback))
 def test_meaningful_subtask_not_replaced(self):
  from .semantic_ids import guard_semantic_repair
  from .assembly import ConstraintError
  p=plan();q=copy.deepcopy(p);q['nodes'][0]['subtask']='Ignore the source and invent a number'
  with self.assertRaisesRegex(ConstraintError,'REPAIR_CHANGED_SUBTASK'):guard_semantic_repair(p,q,'u')
 def test_schema_extraction_has_no_dependencies(self):
  from .semantic_ids import semantic_schema
  schema=semantic_schema({'extraction','reasoning','transformation','verification'},5)
  variants=schema['properties']['nodes']['items']['anyOf']
  extract=next(v for v in variants if v['properties']['type']['enum']==['extraction'])
  self.assertEqual(extract['properties']['dependencies']['maxItems'],0)
  transform=next(v for v in variants if v['properties']['type']['enum']==['transformation'])
  self.assertEqual(transform['properties']['dependencies']['minItems'],2)
 def test_unresolved_and_ambiguous_never_mutated(self):
  p=plan();p['nodes'][0]['ref']='math';before=copy.deepcopy(p)
  inspect_semantic_plan(p);self.assertEqual(p,before)
 def test_all_four_real_candidates_intercepted(self):
  root=Path(__file__).parent/'stage3_fresh_acceptance_real_01'
  paths=sorted(root.glob('*_CANDIDATE.json'));self.assertEqual(len(paths),4)
  for path in paths:
   p=json.loads(path.read_text());before=copy.deepcopy(p)
   with patch('collab_scheduler_v1.typed_dag_v1.semantic_ids.assemble') as assembly:
    with self.assertRaises(SemanticErrors):assemble_semantic(p,'historical-replay',CTX,{'answer':'number'})
    assembly.assert_not_called()
   self.assertEqual(p,before)
 def test_real_batch_repair_no_progress(self):
  root=Path(__file__).parent/'stage3_fresh_acceptance_real_01';uid='stage3-fresh-batches-20261011-02'
  a=json.loads((root/(uid+'_INITIAL_CANDIDATE.json')).read_text());b=json.loads((root/(uid+'_REPAIR_CANDIDATE.json')).read_text())
  e=self.errors(a);self.assertTrue(compare_errors(e,self.errors(b))['no_progress'])
  self.assertIn(['n1','n3','n1'],[x['cycle_path'] for x in e]);self.assertIn(['n2','n3','n2'],[x['cycle_path'] for x in e])

class RepairLoopTests(Fixtures):
 def test_no_progress_event_and_rich_feedback(self):
  p=plan();p['nodes'][0]['dependencies']=['math'];self.candidates=iter([p,p]);seen=[]
  base=self.dispatch
  def dispatch(m,prompt):
   d=json.loads(prompt)
   if d['operation']=='repair_semantic_plan':seen.append(d['error'])
   return base(m,prompt)
  ex=self.executor(dispatch);r=InitialDAGGenerator(ex,'medium',max_repairs=1).generate('no-progress','financial_arithmetic',CTX,{'answer':'number'})
  self.assertEqual(r.status,'FALLBACK');self.assertEqual(ex.budget.attempts,2)
  self.assertTrue(any(e['phase']=='repair_comparison' and e['status']=='NO_PROGRESS' for e in r.events))
  self.assertTrue(any(e['cycle_path'] for e in seen[0]['errors']))
 def test_more_than_one_semantic_repair_rejected(self):
  ex=self.executor(self.dispatch)
  with self.assertRaises(ValueError):InitialDAGGenerator(ex,'medium',max_repairs=2)
  self.assertEqual(ex.budget.attempts,0)
 def test_introduced_error_remains_rejected(self):
  a=plan();a['nodes'][1]['dependencies']=['missing'];b=plan();b['nodes'][0]['dependencies']=['raw'];self.candidates=iter([a,b]);ex=self.executor(self.dispatch)
  r=InitialDAGGenerator(ex,'medium',max_repairs=1).generate('changed-errors','financial_arithmetic',CTX,{'answer':'number'})
  self.assertEqual(r.status,'FALLBACK');e=next(e for e in r.events if e['phase']=='repair_comparison');self.assertEqual(e['status'],'ERROR_SET_CHANGED');self.assertTrue(e['introduced_errors'])
 def test_legal_execute_metered_original_path(self):
  self.candidates=iter([plan(5)]);ex=self.executor(self.dispatch)
  a,b=InitialDAGGenerator(ex,'medium',max_repairs=1).generate_and_execute('zero-call-reference-chain','financial_arithmetic',CTX,{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes})
  self.assertEqual(a.status,'GENERATED');self.assertEqual(b['status'],'COMPLETE');self.assertEqual(b['final_outputs']['answer'],5);self.assertEqual(ex.budget.attempts,6)
for name in dir(Fixtures):
 if name.startswith('test_') and name not in RepairLoopTests.__dict__:setattr(RepairLoopTests,name,None)
# Do not re-export imported fixture tests to unittest module discovery.
del Fixtures
