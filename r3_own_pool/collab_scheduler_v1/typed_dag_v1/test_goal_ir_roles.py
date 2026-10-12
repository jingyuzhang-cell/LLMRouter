import copy,json,unittest
from pathlib import Path
from .goal_ir_roles import role_schema,normalize_role_ir
from .goal_ir import compile_goal_ir,ROLES
from .service_schema import full_validate
from .semantic_validation import SemanticErrors
from .test_goal_ir import ir,build
from .test_semantic_ids import LoopTests as Fixture,CTX
from .generation import InitialDAGGenerator

def grouped(p):
 p=copy.deepcopy(p)
 for s in p['steps']:
  groups={}
  for x in s['inputs']:groups.setdefault(ROLES[x['type']],[]).append(x)
  s['inputs']=groups
 return p
class RoleTests(unittest.TestCase):
 def test_variable_topology_forward_roots(self):
  for size in (3,5):
   p=grouped(ir(size));p['steps'].reverse();q,e=normalize_role_ir(p);g,_=build(q)
   self.assertEqual(len(g.nodes),size);self.assertEqual(e['invented_edges'],0)
 def test_missing_role_rejected(self):
  for role in ('facts','expression'):
   p=grouped(ir());del p['steps'][-1]['inputs'][role]
   with self.assertRaises(SemanticErrors):normalize_role_ir(p)
 def test_empty_role_rejected(self):
  p=grouped(ir());p['steps'][-1]['inputs']['facts']=[]
  with self.assertRaises(SemanticErrors):normalize_role_ir(p)
 def test_wrong_type_rejected(self):
  p=grouped(ir());p['steps'][-1]['inputs']['facts'][0]['type']='expression'
  with self.assertRaises(SemanticErrors):normalize_role_ir(p)
 def test_unknown_producer_not_inferred(self):
  p=grouped(ir());p['steps'][1]['inputs']['facts'][0]['symbol']='unknown';q,_=normalize_role_ir(p)
  with self.assertRaises(SemanticErrors):compile_goal_ir(q)
 def test_historical_failures_no_invented_links(self):
  root=Path(__file__).parent/'http_schema_diagnostic_v1'
  for run in ('run02','run03','run04'):
   original=json.loads((root/run/'execution/B/RAW_CANDIDATE.txt').read_text());before=copy.deepcopy(original)
   with self.assertRaises(SemanticErrors):normalize_role_ir(grouped(original))
   self.assertEqual(original,before)
 def test_old_ir_still_valid(self):full_validate(ir(5),__import__(__package__+'.goal_ir',fromlist=['goal_ir_schema']).goal_ir_schema())
class RoleLoopTests(Fixture):
 def dispatch_roles(self,m,p):
  payload=json.loads(p) if p.startswith('{') else None
  if payload and payload.get('operation') in ('plan_goal_ir','repair_goal_ir'):
   self.assertEqual(payload['plan_json_schema'],role_schema(payload['public_task']['limits']['max_nodes']));return json.dumps(next(self.candidates))
  return self.dispatch(m,p)
 def test_three_five_original_metered_execution(self):
  for size in (3,5):
   self.candidates=iter([grouped(ir(size))]);ex=self.executor(self.dispatch_roles)
   a,b=InitialDAGGenerator(ex,'medium',planning_mode='goal_ir',goal_input_mode='roles',strict_planning_schema=True).generate_and_execute('role-stub-'+str(size),'financial_arithmetic',CTX,{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes})
   self.assertEqual(a.status,'GENERATED');self.assertEqual(b['status'],'COMPLETE');self.assertEqual(b['final_outputs']['answer'],2 if size==3 else 5)
   self.assertEqual(a.graph.provenance['goal_ir_compilation']['role_adapter']['invented_edges'],0);self.assertEqual(ex.budget.attempts,4 if size==3 else 6)
for name in dir(Fixture):
 if name.startswith('test_') and name not in RoleLoopTests.__dict__:setattr(RoleLoopTests,name,None)
del Fixture
