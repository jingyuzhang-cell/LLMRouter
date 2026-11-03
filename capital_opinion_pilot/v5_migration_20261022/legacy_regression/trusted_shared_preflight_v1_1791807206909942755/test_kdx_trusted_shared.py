import tempfile,unittest
from pathlib import Path
from kdx_trusted_shared_protocol import start_admission
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name);self.p={'protocol_id':'shared1','wall_seconds':300,'quarantine_path':str(self.root/'quarantine')};self.a={'operators_agreed':True,'coordination_evidence':'MOCK ONLY','window_start':0,'window_end':400,'collaborative_lock_available':True}
 def call(self,gpu=(),history=()):return start_admission(self.p,self.a,gpu,self.root/'run',history,now=1)
 def test_coordinated_gate(self):self.assertEqual(self.call()['generation_requests'],0)
 def test_missing_agreement(self):
  self.a['operators_agreed']=False
  with self.assertRaises(ValueError):self.call()
 def test_short_window(self):
  self.a['window_end']=299
  with self.assertRaises(ValueError):self.call()
 def test_quarantine(self):
  Path(self.p['quarantine_path']).touch()
  with self.assertRaises(ValueError):self.call()
 def test_gpu_busy(self):
  with self.assertRaises(ValueError):self.call(gpu=[1])
 def test_historical_duplicate(self):
  with self.assertRaises(ValueError):self.call(history=[{'protocol_id':'shared1'}])
 def test_lock_busy(self):
  self.a['collaborative_lock_available']=False
  with self.assertRaises(ValueError):self.call()
if __name__=='__main__':unittest.main()
