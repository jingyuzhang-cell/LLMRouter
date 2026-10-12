import copy,json,unittest
from pathlib import Path
from .producer_plan import compile_producer_plan,producer_schema,verify_producer_bindings,guard_raw_repair
from .semantic_ids import assemble_semantic
from .semantic_validation import SemanticErrors
from .assembly import ConstraintError
from .protocol import Limits
from .test_semantic_ids import plan,CTX,LoopTests as Fixture
from .generation import InitialDAGGenerator

def producers(size=3):
 p=plan(size)
 for n in p['nodes']:
  deps=n.pop('dependencies')
  if n['type']=='extraction':inputs={}
  elif n['type']=='reasoning':inputs={'facts':deps}
  elif n['type']=='transformation':inputs={'facts':[d for d in deps if d!='math'],'expression':['math']}
  else:inputs={'value':deps}
  n['input_producers']=inputs
 return p

class ProducerTests(unittest.TestCase):
 def graph(self,p):
  q,e=compile_producer_plan(p);g=assemble_semantic(q,'u',CTX,{'answer':'number'});verify_producer_bindings(g,e);return g,e
 def test_variable_three_five(self):
  for size in (3,5):g,e=self.graph(producers(size));self.assertEqual(len(g.nodes),size);self.assertEqual(e['invented_edges'],0)
 def test_forward_and_multiroot(self):
  p=producers(5);p['nodes'].reverse();g,_=self.graph(p);self.assertEqual(sum(not n.dependencies for n in g.nodes),2)
 def test_same_names(self):
  p=producers(5)
  for n in p['nodes']:n['name']='same'
  self.assertEqual(len(self.graph(p)[0].nodes),5)
 def test_missing_role_not_filled(self):
  p=producers();del p['nodes'][2]['input_producers']['expression']
  with self.assertRaises(SemanticErrors):compile_producer_plan(p)
 def test_wrong_producer_not_substituted(self):
  p=producers();p['nodes'][2]['input_producers']['expression']=['raw']
  with self.assertRaisesRegex(SemanticErrors,'PRODUCER_TYPE_MISMATCH'):compile_producer_plan(p)
 def test_two_expression_producers_ambiguous(self):
  p=producers();p['nodes'][2]['input_producers']['expression']=['math','raw']
  with self.assertRaises(SemanticErrors):compile_producer_plan(p)
 def test_duplicate_field_rejected(self):
  p=producers();p['nodes'][1]['dependencies']=['raw']
  with self.assertRaisesRegex(SemanticErrors,'DUPLICATE_DEPENDENCY_REPRESENTATION'):compile_producer_plan(p)
 def test_cycle_still_rejected(self):
  p=producers(5);p['nodes'][-1]['input_producers']={'value':['audit']}
  with self.assertRaisesRegex(ConstraintError,'CYCLE'):self.graph(p)
 def test_missing_ref_still_rejected(self):
  p=producers();p['nodes'][1]['input_producers']['facts']=['absent']
  with self.assertRaisesRegex(ConstraintError,'DEPENDENCY_REFERENCE'):self.graph(p)
 def test_history_not_upgraded(self):
  root=Path(__file__).parent/'stage3_fresh_acceptance_real_01'
  for path in root.glob('*_CANDIDATE.json'):
   p=json.loads(path.read_text());q,e=compile_producer_plan(p);self.assertEqual(p,q);self.assertEqual(e['protocol'],'legacy_dependencies_diagnostic')
   with self.assertRaises(ConstraintError):assemble_semantic(q,'replay',CTX,{'answer':'number'})
 def test_schema_only_one_dependency_source(self):
  for v in producer_schema({'extraction','reasoning','transformation','verification'},5)['properties']['nodes']['items']['anyOf']:
   self.assertIn('input_producers',v['required']);self.assertNotIn('dependencies',v['properties'])
 def test_compile_failure_cannot_drop_nodes_in_repair(self):
  a=producers(5);b=producers();del a['nodes'][3]['input_producers']['expression']
  with self.assertRaisesRegex(ConstraintError,'REPAIR_REMOVED_NODE'):guard_raw_repair(a,b,'u',Limits())

class ProducerLoopTests(Fixture):
 def test_actual_new_schema_mock_loop(self):
  original=self.dispatch
  def call(m,p):
   try:d=json.loads(p)
   except ValueError:return original(m,p)
   if d.get('operation')=='plan_typed_dag':
    self.assertNotIn('dependencies',json.dumps(d['plan_json_schema']));return json.dumps(producers(5))
   return original(m,p)
  ex=self.executor(call);a,b=InitialDAGGenerator(ex,'medium',max_repairs=1).generate_and_execute('producer-mock','financial_arithmetic',CTX,{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes})
  self.assertEqual(a.status,'GENERATED');self.assertEqual(a.graph.provenance['producer_plan']['protocol'],'explicit_input_producers.v1');self.assertEqual(b['status'],'COMPLETE');self.assertEqual(b['final_outputs']['answer'],5);self.assertEqual(ex.budget.attempts,6)
for name in dir(Fixture):
 if name.startswith('test_') and name not in ProducerLoopTests.__dict__:setattr(ProducerLoopTests,name,None)
del Fixture
