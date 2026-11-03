import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from kdx_preflight_launcher import Preflight
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.service=Mock();self.service.process.pid=123;self.service.process.poll.return_value=None;self.service.quarantine=self.root/'quarantine';self.service.exit_probe=lambda pid:True
  def start():self.root.joinpath('run').mkdir()
  self.service.start.side_effect=start
  self.service.stop.side_effect=lambda:self.service.exit_probe(123)
  self.protocol={'isolation_enforced':True,'model_command':['vllm','serve','model','--served-model-name','qwen'],'lock_path':str(self.root/'lock')}
 def runner(self,metadata=None):return Preflight(self.root,self.root/'run',service_factory=Mock(return_value=self.service),metadata=metadata or (lambda method,path,timeout: {'status':200} if path=='/health' else {'data':[{'id':'qwen'}]}),gpu_snapshot=lambda timeout:{'processes':[]},timer=Mock())
 def test_unauthorized_no_start(self):
  with self.assertRaises(ValueError):self.runner().execute()
  self.service.start.assert_not_called()
 def test_success_metadata_only(self):
  with patch('kdx_preflight_launcher.validate_package',return_value=self.protocol):r=self.runner().execute(authorized=True)
  self.assertEqual(r['model_requests'],0);self.assertEqual(r['result'],'PASS_METADATA_ONLY');self.service.stop.assert_called_once()
 def test_timeout_cleanup(self):
  def bad(*a,**kw):raise TimeoutError()
  with patch('kdx_preflight_launcher.validate_package',return_value=self.protocol):r=self.runner(bad).execute(authorized=True)
  self.assertEqual(r['primary_error']['type'],'TimeoutError');self.service.stop.assert_called_once();self.assertTrue(self.service.quarantine.exists())
 def test_identity_error_cleanup(self):
  self.service.check_identity.side_effect=ValueError('wrong')
  with patch('kdx_preflight_launcher.validate_package',return_value=self.protocol):r=self.runner().execute(authorized=True)
  self.assertEqual(r['result'],'FAILED_OR_QUARANTINED')
 def test_cleanup_error_separate(self):
  self.service.stop.side_effect=RuntimeError('cleanup')
  with patch('kdx_preflight_launcher.validate_package',return_value=self.protocol):r=self.runner().execute(authorized=True)
  self.assertIsNone(r['primary_error']);self.assertEqual(r['cleanup_error']['type'],'RuntimeError')
 def test_unisolated_real_start_blocked(self):
  self.protocol['isolation_enforced']=False
  with patch('kdx_preflight_launcher.validate_package',return_value=self.protocol):
   with self.assertRaisesRegex(ValueError,'ISOLATION'):self.runner().execute(authorized=True)
  self.service.start.assert_not_called()
if __name__=='__main__':unittest.main()
