import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from kdx_execution_adapter import Corpus,KDXNodeAdapter,ROOT
from strict_meter import StrictMeter
from pilot_common import Meter,BudgetExceeded
from merge_contract_v2 import merge
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.c=Corpus();cls.plan=json.loads((ROOT/'v3_kdx_repair.json').read_text())['arms'][0]['plan']
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.m=StrictMeter(Path(self.tmp.name)/'calls.jsonl',max_calls=2,max_guaranteed_actual=20);self.a=KDXNodeAdapter(self.c,self.plan,self.m)
 def test_all_document_tail_and_locations(self):
  for d in self.c.documents:
   chunks=[x for x in self.c.chunks if x['document_id']==d]
   self.assertEqual(max(x['end'] for x in chunks),self.c.documents[d]['actual_chars']);self.assertTrue(all(self.c.locate(x) for x in chunks))
 def test_real_local_search_all_sources(self):
  rows=self.c.search(['康得新','处罚','问询'],list(self.c.documents));self.assertEqual(len(rows),5)
 def test_missing_required_evidence(self):
  with self.assertRaises(ValueError):self.c.search(['ABSENT_zzzzz'],list(self.c.documents))
 def test_other_task_documents_rejected(self):
  with self.assertRaises(ValueError):self.c.search(['处罚'],['st_announce_2024_020'])
 def test_wrong_index(self):
  with patch.object(self.c,'task_id','wrong'):
   with self.assertRaisesRegex(ValueError,'TASK_INDEX'):self.a.prepare('t1',{},'Q')
 def test_legacy_meter_rejected(self):
  with self.assertRaisesRegex(ValueError,'STRICT_METER'):KDXNodeAdapter(self.c,self.plan,Meter(Path(self.tmp.name)/'old.jsonl'))
 def test_graph_structure_same(self):
  self.assertEqual([(n.node_id,n.dependencies) for n in self.a.graph.nodes],[(t['id'],t['depends']) for t in self.plan['plan']])
 def test_each_node_binding_preparation(self):
  up={n.node_id:{p:[] for p in __import__('pilot_dag_contracts').td.CONTRACTS[n.output_contract][2]} for n in self.a.graph.nodes}
  fragments=self.c.search(['康得新'],list(self.c.documents))
  for n in self.a.graph.nodes:
   _,inputs,payload=self.a.prepare(n.node_id,up,'Q',fragments);self.assertEqual(payload['task_id'],'kdx_002450');self.assertTrue(inputs)
 def test_forged_fragment_rejected(self):
  f=self.c.search(['康得新'],list(self.c.documents));f=[dict(x) for x in f];f[0]['text']='forged'
  with self.assertRaisesRegex(ValueError,'FORGED'):self.a.prepare('t2',{'t1':{'evidence_index':[]}},'Q',f)
 def test_joint_reservation_rejects_before_http(self):
  with patch.object(self.m,'_transport') as http:
   with self.assertRaises(BudgetExceeded):self.a.dispatch_node('t1',{},'Q',alias='glm53',input_upper=19,bound_evidence='mock exact tokenizer',max_output=2)
   http.assert_not_called()
 def test_mock_node_result_and_dedup(self):
  r={'usage':{'input_tokens':5,'output_tokens':5},'text':'{"evidence_index": []}','latency_s':0,'stop_reason':'end_turn'}
  with patch.object(self.m,'_transport',return_value=r) as http:
   for _ in range(2):self.a.dispatch_node('t1',{},'Q',alias='glm53',input_upper=5,bound_evidence='mock',max_output=5)
   self.assertEqual(http.call_count,1)
 def test_timeout_full_reservation_and_restart(self):
  with patch.object(self.m,'_transport',side_effect=TimeoutError):
   with self.assertRaises(TimeoutError):self.a.dispatch_node('t1',{},'Q',alias='glm53',input_upper=5,bound_evidence='mock',max_output=5)
  self.assertEqual(self.m.summary()['pending_reserve'],10)
  fresh=KDXNodeAdapter(self.c,self.plan,StrictMeter(self.m.ledger,max_calls=2,max_guaranteed_actual=20))
  with patch.object(fresh.meter,'_transport') as http:
   with self.assertRaises(BudgetExceeded):fresh.dispatch_node('t1',{},'Q',alias='glm53',input_upper=5,bound_evidence='mock',max_output=5)
   http.assert_not_called()
 def test_conflicts_preserved_not_adjudicated(self):
  rows=merge([[{'fact_key':'x','value':1,'doc_id':'a','public_date':'2020'}],[{'fact_key':'x','value':2,'doc_id':'b','public_date':'2021'}]],['a','b'])
  self.assertTrue(all(r['potential_conflict'] for r in rows));self.assertEqual([r['value'] for r in rows],[1,2])
if __name__=='__main__':unittest.main()
