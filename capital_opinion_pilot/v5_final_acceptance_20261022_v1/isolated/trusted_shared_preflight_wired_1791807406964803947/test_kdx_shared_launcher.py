import time,unittest
from unittest.mock import patch
import test_kdx_preflight_launcher as original
class SharedTests(unittest.TestCase):
 def setUp(self):
  original.Tests.setUp(self);self.protocol.update(protocol_kind='TRUSTED_SHARED_PREFLIGHT',protocol_id='shared-mock',wall_seconds=300,quarantine_path=str(self.root/'q'))
  self.coordination={'operators_agreed':True,'coordination_evidence':'MOCK attestation only','window_start':time.time()-1,'window_end':time.time()+400,'collaborative_lock_available':True}
 def run_shared(self):
  with patch('kdx_preflight_launcher.validate_package',return_value=self.protocol),patch('kdx_trusted_shared_protocol.offline_validate',return_value=self.protocol):return self.runner().execute(authorized=True,coordination=self.coordination)
 def test_shared_success(self):self.assertEqual(self.run_shared()['result'],'PASS_METADATA_ONLY')
 def test_missing_operator_agreement(self):
  self.coordination['operators_agreed']=False
  with self.assertRaises(ValueError):self.run_shared()
  self.service.start.assert_not_called()
 def test_missing_window(self):
  self.coordination['window_end']=time.time()+50
  with self.assertRaises(ValueError):self.run_shared()
  self.service.start.assert_not_called()
 def test_quarantine_exists(self):
  (self.root/'q').touch()
  with self.assertRaises(ValueError):self.run_shared()
  self.service.start.assert_not_called()
 def runner(self):return original.Tests.runner(self)
 def test_shared_health_timeout_cleanup(self):
  r=self.runner();r.metadata=lambda *a,**kw:(_ for _ in ()).throw(TimeoutError())
  with patch('kdx_preflight_launcher.validate_package',return_value=self.protocol),patch('kdx_trusted_shared_protocol.offline_validate',return_value=self.protocol):result=r.execute(authorized=True,coordination=self.coordination)
  self.assertEqual(result['primary_error']['type'],'TimeoutError');self.service.stop.assert_called_once()
 def test_shared_cleanup_failure(self):
  self.service.stop.side_effect=RuntimeError('cleanup')
  result=self.run_shared();self.assertEqual(result['cleanup_error']['type'],'RuntimeError')
if __name__=='__main__':unittest.main()
