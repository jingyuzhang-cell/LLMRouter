import copy,unittest
from .planning_wire_bounds import bounded_schema
from .goal_ir_roles import role_schema,normalize_role_ir
from .producer_plan import producer_schema,compile_producer_plan
from .test_goal_ir import ir
from .test_goal_ir_roles import grouped
from .test_producer_plan import producers
from .service_schema import full_validate
from .goal_ir import compile_goal_ir
class WireBoundsTests(unittest.TestCase):
 def test_no_mutation(self):
  s=role_schema(5);old=copy.deepcopy(s);bounded_schema(s);self.assertEqual(s,old)
 def test_three_five_goal_unchanged(self):
  for n in (3,5):
   p=grouped(ir(n));full_validate(p,bounded_schema(role_schema(5)));flat,_=normalize_role_ir(p,5);compile_goal_ir(flat)
 def test_three_five_producer_unchanged(self):
  for n in (3,5):
   p=producers(n);full_validate(p,bounded_schema(producer_schema({'extraction','reasoning','transformation','verification'},5)));compile_producer_plan(p)
 def test_long_ref_rejected_not_truncated(self):
  p=grouped(ir());p['steps'][0]['ref']='x'*49;old=copy.deepcopy(p)
  with self.assertRaises(ValueError):full_validate(p,bounded_schema(role_schema()))
  self.assertEqual(p,old)
 def test_long_symbol_rejected(self):
  p=grouped(ir());p['steps'][0]['outputs'][0]['symbol']='x'*49
  with self.assertRaises(ValueError):full_validate(p,bounded_schema(role_schema()))
 def test_long_producer_ref_rejected(self):
  p=producers();p['nodes'][1]['input_producers']['facts']=['x'*49]
  with self.assertRaises(ValueError):full_validate(p,bounded_schema(producer_schema({'extraction','reasoning','transformation','verification'},5)))
 def test_not_fixed_count(self):self.assertEqual(bounded_schema(role_schema(5))['properties']['steps']['maxItems'],5)

 def test_six_nodes_rejected(self):
  p=grouped(ir(5));p['steps'].append(p['steps'][0])
  with self.assertRaises(ValueError):full_validate(p,bounded_schema(role_schema(5)))
 def test_duplicate_short_symbol_rejected(self):
  from .goal_ir import compile_goal_ir
  from .goal_ir_roles import normalize_role_ir
  p=grouped(ir());p['steps'][1]['outputs'][0]['symbol']='table_data'
  flat,_=normalize_role_ir(p,5)
  with self.assertRaises(ValueError):compile_goal_ir(flat)
 def test_truncation_positions(self):
  import json
  text=json.dumps(grouped(ir(5)))
  for n in (1,len(text)//2,len(text)-1):
   with self.assertRaises(json.JSONDecodeError):json.loads(text[:n])
 def test_optional_generator_schema(self):
  from .generation import InitialDAGGenerator
  from types import SimpleNamespace
  from pathlib import Path
  import tempfile,json
  class Captured(Exception):pass
  with tempfile.TemporaryDirectory() as d:
   class Ex:
    bindings={'medium':'medium'};directory=Path(d);budget=SimpleNamespace(attempts=0,actual_tokens=0,charged=0,pending={})
    def begin_cell(self,*a):pass
    def call(self,k,m,p):self.payload=json.loads(p);raise Captured()
   ex=Ex()
   with self.assertRaises(Captured):InitialDAGGenerator(ex,'medium',planning_mode='goal_ir',goal_input_mode='roles',wire_protocol='bounded-planning-wire.v1').generate('generic','arithmetic',{'question':'generic','ctx_table':'1'}, {'answer':'number'})
   self.assertEqual(ex.payload['wire_protocol'],'bounded-planning-wire.v1')
   self.assertEqual(ex.payload['plan_json_schema']['properties']['steps']['items']['anyOf'][0]['properties']['ref']['maxLength'],48)
