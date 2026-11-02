import copy,json,unittest
from build import RUN,DAG,match_input
class InputTests(unittest.TestCase):
 def setUp(self):
  self.cache=json.loads((RUN/'cal_1.RAW.json').read_text())['cache']
  self.nodes=json.loads(DAG.read_text())['nodes']
 def payload(self,n):
  d=json.loads((RUN/'requests'/('cal_1__'+n['node_id'])/'REQUEST.json').read_text())
  s=d['messages'][0]['content'];return json.loads(s[s.index('\n')+1:])
 def test_all_four_saved_inputs(self):
  for n in self.nodes:
   if n['node_id'] in ('timeline_1','relations_1','verify_1','report_1'):
    match_input(n,self.payload(n),self.cache)
 def test_uncommitted_parent_rejected(self):
  n=next(n for n in self.nodes if n['node_id']=='timeline_1')
  self.cache['extract_1']['commit']=False
  with self.assertRaisesRegex(ValueError,'UNCOMMITTED'):match_input(n,self.payload(n),self.cache)
 def test_changed_input_rejected(self):
  n=next(n for n in self.nodes if n['node_id']=='timeline_1');p=self.payload(n);p['input']['claims']=[]
  with self.assertRaisesRegex(ValueError,'INPUT_MISMATCH'):match_input(n,p,self.cache)
 def test_wrong_contract_rejected(self):
  n=next(n for n in self.nodes if n['node_id']=='timeline_1');p=self.payload(n);p['contract']='wrong'
  with self.assertRaisesRegex(ValueError,'CONTRACT_MISMATCH'):match_input(n,p,self.cache)
if __name__=='__main__':unittest.main()
