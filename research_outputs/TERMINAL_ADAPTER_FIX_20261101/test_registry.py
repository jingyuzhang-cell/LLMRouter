import copy,hashlib,unittest
from evidence_registry import build_registry,resolve,adapt_registered
class RegistryTests(unittest.TestCase):
 def setUp(self):
  text='甲公司罚款100万元。甲公司罚款100万元。'
  self.sources={'D':{'raw_sha256':'a'*64,'pages':{'1':{'text':text,'page_sha256':hashlib.sha256(text.encode()).hexdigest()}}}}
  self.registry=build_registry(self.sources);self.ids=list(self.registry)
 def test_duplicate_text_has_distinct_position_identity(self):
  self.assertEqual(len(self.ids),2);self.assertNotEqual(self.ids[0],self.ids[1])
  a,b=[resolve(i,self.registry,self.sources) for i in self.ids]
  self.assertEqual(a['quote'],b['quote']);self.assertNotEqual(a['start'],b['start'])
 def test_unknown_id_rejected_not_guessed(self):
  with self.assertRaisesRegex(ValueError,'UNKNOWN_EVIDENCE_ID'):resolve('E1',self.registry,self.sources)
 def test_source_change_rejected(self):
  self.sources['D']['pages']['1']['text']+='改动'
  with self.assertRaisesRegex(ValueError,'SOURCE_VERSION_MISMATCH'):resolve(self.ids[0],self.registry,self.sources)
 def test_registry_tamper_rejected(self):
  self.registry[self.ids[0]]['quote']='伪造'
  with self.assertRaisesRegex(ValueError,'REGISTRY_SPAN_MISMATCH'):resolve(self.ids[0],self.registry,self.sources)
 def test_value_not_repaired_and_support_not_claimed(self):
  p={'complete':True,'answers':[{'fact_id':'F1','value':'999','evidence_ids':[self.ids[1]]}]}
  terminal,diag=adapt_registered(p,[dict(fact_id='F1',subject='甲公司',predicate='罚款',unit='万元')],self.registry,self.sources)
  c=terminal['claims'][0];self.assertEqual(c['value'],'999');self.assertEqual(c['citations'][0]['start'],11)
  self.assertEqual(diag['locations'][0]['semantic_support'],'NOT_DETERMINED_BY_REGISTRY')
 def test_stable_build(self):self.assertEqual(self.registry,build_registry(copy.deepcopy(self.sources)))
if __name__=='__main__':unittest.main()
