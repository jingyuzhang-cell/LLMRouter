import copy,unittest
import semantic_plan as SP,assemble_dag as AD
from merge_contract_v2 import merge,execute
DOCS=['kdx_inquiry_2018','kdx_notice_2019']
def plan():
 rows=[('i','index',[]),('a','extracts_f',['i']),('b','extracts_f',['i']),('m','facts_merge_v2',['a','b']),('tl','timeline',['m']),('ef','entity_facts',['m']),('ck','factcheck_full',['m','tl','ef']),('r','report',['ck'])]
 return {'plan':[{'id':u,'kind':k,'goal':'独立合成机制样例','doc_ids':DOCS if k=='extracts_f' else [],'depends':deps} for u,k,deps in rows]}
class Tests(unittest.TestCase):
 def test_semantic_and_typed_multi_input(self):
  p=plan();self.assertEqual(SP.validate_plan(p,DOCS),[]);gv,iss=AD.assemble(p);self.assertIsNotNone(gv);self.assertEqual(iss,[]);node=next(n for n in gv[0].nodes if n.node_id=='m');self.assertEqual([b.node_id for b in node.inputs if b.port=='facts'],['a','b'])
 def test_forward_order(self):
  p=plan();p['plan'].reverse();self.assertEqual(SP.validate_plan(p,DOCS),[]);self.assertIsNotNone(AD.assemble(p)[0])
 def test_wrong_type(self):
  p=plan();p['plan'][1]['kind']='extracts';self.assertTrue(SP.validate_plan(p,DOCS));self.assertIsNone(AD.assemble(p)[0])
 def test_no_dead_branch(self):
  p=plan();p['plan'].append({'id':'unused','kind':'timeline','goal':'未消费','depends':['m'],'doc_ids':[]});self.assertIsNone(AD.assemble(p)[0])
 def test_cycle(self):
  p=plan();p['plan'][1]['depends']=['m'];self.assertTrue(SP.validate_plan(p,DOCS));self.assertIsNone(AD.assemble(p)[0])
 def test_missing_reference(self):
  p=plan();p['plan'][3]['depends'].append('missing');self.assertIsNone(AD.assemble(p)[0])
 def test_provenance_and_conflicts(self):
  a={'fact_key':'profit','value':7,'doc_id':'A','public_date':'2018-01-01','evidence':'原文A'};b={**a,'value':9,'doc_id':'B','public_date':'2019-01-01','evidence':'原文B'};raw=copy.deepcopy([a,b]);m=merge([[a],[b]],['a','b']);self.assertEqual([a,b],raw);self.assertTrue(all(x['potential_conflict'] for x in m));self.assertEqual(m[1]['origins'][-1]['original_record'],b);self.assertEqual(m[0]['trust_status'],'UNVERIFIED_MATERIAL')
 def test_no_silent_zip_drop(self):
  with self.assertRaises(ValueError):merge([[],[]],['a'])
 def test_preserve_different_evidence(self):
  rows=[[{'fact_key':'fee','value':7,'doc_id':'A','evidence':'first'}],[{'fact_key':'fee','value':7,'doc_id':'B','evidence':'second'}]];self.assertEqual(len(merge(rows,['a','b'])),2)
 def test_unknown_source_explicit(self):
  m=merge([[{'value':1}]],['a']);self.assertEqual(m[0]['metadata_missing'],['doc_id','public_date'])
 def test_cache_identity_and_program_execution(self):
  g=AD.assemble(plan())[0][0];n=next(n for n in g.nodes if n.node_id=='m');outs={'a':{'facts':[{'value':1,'doc_id':'A'}]},'b':{'facts':[{'value':2,'doc_id':'B'}]}};r,a=execute(n,outs,{});self.assertEqual(len(r['doc_extracts']),2);self.assertEqual(a['model_calls'],0);outs['b']['facts'][0]['value']=3;self.assertNotEqual(a['cache_identity'],execute(n,outs,{})[1]['cache_identity'])
if __name__=='__main__':unittest.main()

class IdentityTests(unittest.TestCase):
 def test_explicit_task_identity(self):
  g=AD.assemble(plan(),task_id="kdx_002450")[0][0];self.assertEqual(g.task_id,"kdx_002450")

class BudgetTests(unittest.TestCase):
 def test_second_historical_dispatch_should_stop(self):
  from repair_budget_gate import check
  with self.assertRaisesRegex(ValueError,'TOKEN_CAP'):check(1970,0,1,1486,640)
 def test_input_bound_required(self):
  from repair_budget_gate import check
  with self.assertRaisesRegex(ValueError,'INPUT_BOUND_UNKNOWN'):check(0,0,0,None,640)
 def test_pending_boundary(self):
  from repair_budget_gate import check
  self.assertEqual(check(1000,500,1,2000,500),2500)
  with self.assertRaises(ValueError):check(1000,501,1,2000,500)
