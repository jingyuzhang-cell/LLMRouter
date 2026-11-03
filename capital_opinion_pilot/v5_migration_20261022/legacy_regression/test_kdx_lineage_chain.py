"""Mock semantic outputs only, not execution of A or model generation."""
import copy,unittest
from kdx_execution_adapter import Corpus
from kdx_admission import Lineage
class Tests(unittest.TestCase):
 def setUp(self):
  self.c=Corpus();self.l=Lineage(self.c);self.rows=[]
  for i,doc in enumerate(list(self.c.documents)[:2]):
   c=next(x for x in self.c.chunks if x['document_id']==doc)
   self.rows.append(self.l.register({'fact_id':f'f{i}','content':c['text'][:20],'applicable_time':c['public_date'],'uncertainty':'CLAIM_ONLY','conflict':'UNRESOLVED','origins':[{'document_id':doc,'chunk_id':c['fragment_id'],'start':c['start'],'end':c['end'],'source_hash':c['source_hash'],'quote':c['text'][:20]}]}))
 def chain(self,change=None):
  ids=[r['fact_id'] for r in self.rows];p={r['fact_id']:copy.deepcopy(r) for r in self.rows}
  stages=[]
  for stage in ['facts','merge','reasoning','report']:
   if change:change(stage,p)
   stages.append(self.l.consume(ids,p,ids))
  return stages
 def test_all_stages_preserve_origins(self):self.assertEqual(len(self.chain()),4)
 def test_merge_loses_source(self):
  with self.assertRaises(ValueError):self.chain(lambda s,p:p['f0']['origins'].clear() if s=='merge' else None)
 def test_reasoning_drops_conflict(self):
  with self.assertRaises(ValueError):self.chain(lambda s,p:p['f0'].pop('conflict') if s=='reasoning' else None)
 def test_report_omits_fact(self):
  with self.assertRaises(ValueError):self.chain(lambda s,p:p.pop('f1') if s=='report' else None)
 def test_time_changed(self):
  with self.assertRaises(ValueError):self.chain(lambda s,p:p['f0'].update(applicable_time='wrong') if s=='report' else None)
if __name__=='__main__':unittest.main()
