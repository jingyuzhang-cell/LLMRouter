import tempfile,unittest,fcntl,copy
from pathlib import Path
from kdx_execution_adapter import Corpus
from kdx_admission import Lineage,TokenBoundary,Lifecycle
class Service:
 def __init__(self):self.stopped=False
 def start(self):pass
 def identity_ok(self):return True
 def cancel(self):pass
 def stop(self):self.stopped=True
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.c=Corpus()
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
 def fact(self):
  c=self.c.chunks[0]
  return {'fact_id':'f1','content':'source claim','applicable_time':'UNRESOLVED','uncertainty':'UNVERIFIED','conflict':True,'origins':[{'chunk_id':c['fragment_id'],'document_id':c['document_id'],'source_hash':c['source_hash'],'start':c['start'],'end':c['end'],'quote':c['text'][:20]}]}
 def test_lineage_preserves_conflict(self):
  l=Lineage(self.c);f=l.register(self.fact());self.assertEqual(l.consume(['f1'],{'f1':f},['f1']),[f])
 def test_lineage_break(self):
  f=self.fact();f['origins'][0]['source_hash']='bad'
  with self.assertRaises(ValueError):Lineage(self.c).register(f)
 def test_missing_fact(self):
  with self.assertRaises(ValueError):Lineage(self.c).consume([],{},['f1'])
 def test_conflict_removed(self):
  l=Lineage(self.c);f=l.register(self.fact());f['conflict']=False
  with self.assertRaises(ValueError):l.consume(['f1'],{'f1':f})
 def test_token_no_estimate(self):
  with self.assertRaises(ValueError):TokenBoundary('GLM-5.3',None,None,None).bound({'model':'GLM-5.3'})
 def test_mock_full_request_count(self):
  b=TokenBoundary('mock','mock-tokenizer',lambda req:12,'MOCK ONLY',True);self.assertEqual(b.bound({'model':'mock','system':'S','messages':[]})[0],12)
 def test_token_identity(self):
  with self.assertRaises(ValueError):TokenBoundary('x','y',lambda r:1,'mock',True).bound({'model':'z'})
 def lifecycle(self):return Lifecycle(self.root/'gpu.lock',self.root/'run',100)
 def test_normal_cleanup(self):
  s=Service()
  with self.lifecycle().own_service(s,20,10) as admit:admit(60)
  self.assertTrue(s.stopped)
 def test_timeout_cleanup(self):
  s=Service()
  with self.assertRaises(TimeoutError):
   with self.lifecycle().own_service(s,20,10):raise TimeoutError()
  self.assertTrue(s.stopped)
 def test_occupied_lock(self):
  l=(self.root/'gpu.lock').open('a+');fcntl.flock(l,fcntl.LOCK_EX|fcntl.LOCK_NB);self.addCleanup(l.close)
  with self.assertRaises(BlockingIOError):
   with self.lifecycle().own_service(Service(),20,10):pass
 def test_duplicate_run(self):
  (self.root/'run').mkdir()
  with self.assertRaises(FileExistsError):
   with self.lifecycle().own_service(Service(),20,10):pass
 def test_wallclock_reject(self):
  with self.assertRaises(ValueError):
   with self.lifecycle().own_service(Service(),20,10) as admit:admit(101)
 def test_cleanup_failure_isolated(self):
  class Bad(Service):
   def stop(self):raise RuntimeError()
  life=self.lifecycle()
  with self.assertRaises(TimeoutError):
   with life.own_service(Bad(),20,10):raise TimeoutError()
  self.assertTrue(any(e['event']=='CLEANUP_FAILED' for e in life.events))
class EntryTests(unittest.TestCase):
 def test_old_entry_forbidden(self):
  from kdx_admission import FinalNodeGate
  with self.assertRaisesRegex(ValueError,'LEGACY_ENTRY'):FinalNodeGate(object(),None,None,None)
 def test_real_model_without_tokenizer_stops(self):
  from kdx_admission import TokenBoundary
  with self.assertRaisesRegex(ValueError,'TRUSTED_TOKEN_BOUND'):TokenBoundary('GLM-5.3',None,None,None).bound({'model':'GLM-5.3','messages':[]})
if __name__=='__main__':unittest.main()
