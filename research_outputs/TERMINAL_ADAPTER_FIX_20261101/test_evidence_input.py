import copy,hashlib,unittest
from evidence_registry import build_registry
from evidence_input import prepare,finish
class InputBoundary(unittest.TestCase):
 def setUp(self):
  text='甲公司罚款100万元。乙公司罚款200万元。'
  self.sources={'D':{'raw_sha256':'a'*64,'pages':{'1':{'text':text,'page_sha256':hashlib.sha256(text.encode()).hexdigest()}}}}
  self.registry=build_registry(self.sources);self.ids=list(self.registry)
  self.slots=[dict(fact_id='F1',subject='甲公司',predicate='罚款',unit='万元')]
  self.messages,self.receipt=prepare('T','核对金额',[self.ids[0]],self.registry,self.sources,self.slots)
  self.response={'complete':True,'answers':[dict(fact_id='F1',value='999',evidence_ids=[self.ids[0]])]}
 def call(self):return finish(self.response,self.messages,self.receipt,self.slots,self.registry,self.sources)
 def test_complete_path_does_not_correct_wrong_value(self):
  terminal,diagnostics=self.call();self.assertEqual(terminal['claims'][0]['value'],'999')
  self.assertEqual(terminal['claims'][0]['citations'][0]['quote'],'甲公司罚款100万元。')
  self.assertEqual(diagnostics['locations'][0]['semantic_support'],'NOT_DETERMINED_BY_REGISTRY')
 def test_existing_but_unseen_evidence_rejected(self):
  self.response['answers'][0]['evidence_ids']=[self.ids[1]]
  with self.assertRaisesRegex(ValueError,'UNSEEN_EVIDENCE_ID'):self.call()
 def test_foreign_id_rejected(self):
  self.response['answers'][0]['evidence_ids']=['other_task:ev']
  with self.assertRaisesRegex(ValueError,'UNSEEN_EVIDENCE_ID'):self.call()
 def test_prompt_tamper_rejected(self):
  self.messages[1]['content']+='changed'
  with self.assertRaisesRegex(ValueError,'DISPATCH_INPUT_CHANGED'):self.call()
 def test_schema_change_rejected(self):
  self.slots[0]['subject']='乙公司'
  with self.assertRaisesRegex(ValueError,'DISPATCH_INPUT_CHANGED'):self.call()
 def test_registry_change_rejected(self):
  self.registry[self.ids[0]]['quote']='改写'
  with self.assertRaisesRegex(ValueError,'REGISTERED_EVIDENCE_CHANGED'):self.call()
if __name__=='__main__':unittest.main()
