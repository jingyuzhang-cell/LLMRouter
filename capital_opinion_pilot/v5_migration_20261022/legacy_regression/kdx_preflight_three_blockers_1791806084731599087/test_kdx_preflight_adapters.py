import unittest
from unittest.mock import Mock,patch
from kdx_preflight_adapters import MetadataHTTP,final_exit_probe
class Tests(unittest.TestCase):
 def test_post_not_possible(self):
  m=MetadataHTTP(8127);m.opener=Mock()
  with self.assertRaises(ValueError):m('POST','/v1/completions',1)
  m.opener.open.assert_not_called()
 def test_metadata_timeout_limit(self):
  with self.assertRaises(ValueError):MetadataHTTP(8127)('GET','/health',4)
 def test_clean_keeps_other_experiment(self):
  snap={'processes':[{'pid':44,'gpu_uuid':'mock'}]}
  r=final_exit_probe(123,snap,snapshot=lambda timeout:snap,members=lambda pid:[])
  self.assertTrue(r['confirmed']);self.assertEqual(r['other_experiment_pids'],[44])
 def test_new_gpu_pid_residual_rejected(self):
  r=final_exit_probe(123,{'processes':[]},snapshot=lambda timeout:{'processes':[{'pid':555}]},members=lambda pid:[])
  self.assertFalse(r['confirmed'])
 def test_session_alive_rejected(self):
  r=final_exit_probe(123,{'processes':[]},snapshot=lambda timeout:{'processes':[]},members=lambda pid:[123])
  self.assertFalse(r['confirmed'])
if __name__=='__main__':unittest.main()
