import hashlib,unittest
from adapter import adapt,locate,project_slots
class AdapterTests(unittest.TestCase):
 def setUp(self):
  text='甲公司罚款100万元。\n董事会于9月3日召开。'
  self.sources={'D':{'raw_sha256':'a'*64,'pages':{'1':{'text':text,'page_sha256':hashlib.sha256(text.encode()).hexdigest()}}}}
  self.slots=[dict(fact_id='F1',subject='甲公司',predicate='罚款',unit='万元')]
 def test_metadata_filled_value_unchanged(self):
  raw={'complete':True,'answers':[dict(fact_id='F1',value='100',quote='甲公司罚款100万元。',doc='E1')]}
  result,issues=adapt(raw,self.slots,self.sources);c=result['claims'][0]
  self.assertEqual(c['subject'],'甲公司');self.assertEqual(c['predicate'],'罚款');self.assertEqual(c['value'],'100')
  self.assertEqual(c['citations'][0]['doc_id'],'D')
 def test_reference_fields_rejected(self):
  for key in ('value','description','source_evidence','accepted_values','derivation'):
   with self.subTest(key=key),self.assertRaises(ValueError):
    adapt({'claims':[]},[{**self.slots[0],key:'PRIVATE'}],self.sources)
 def test_full_quote_not_prefix(self):
  c,status=locate('甲公司罚款100万元。董事会于9月5日召开。',self.sources)
  self.assertIsNone(c);self.assertEqual(status,'QUOTE_NOT_FOUND')
 def test_ambiguity_refused(self):
  self.sources['D2']=self.sources['D']
  c,status=locate('甲公司罚款100万元。',self.sources,'E1')
  self.assertIsNone(c);self.assertEqual(status,'AMBIGUOUS_QUOTE')
 def test_explicit_conflict_preserved(self):
  out,issues=adapt({'claims':[dict(fact_id='F1',subject='乙公司',value='100',citations=[])]},self.slots,self.sources)
  self.assertEqual(out['claims'][0]['subject'],'乙公司')
  self.assertTrue(any(x.get('reason')=='EXPLICIT_SLOT_CONFLICT' for x in issues))
 def test_hash_tamper_refused(self):
  self.sources['D']['pages']['1']['text']+='changed'
  self.assertEqual(locate('甲公司罚款100万元。',self.sources)[1],'INVALID_SOURCE_HASH')
 def test_unknown_fact_not_dropped_or_filled(self):
  out,issues=adapt({'claims':[dict(fact_id='OTHER',value='999',citations=[])]},self.slots,self.sources)
  self.assertEqual(len(out['claims']),1);self.assertNotIn('subject',out['claims'][0])
  self.assertEqual(out['claims'][0]['value'],'999')
if __name__=='__main__':unittest.main()
