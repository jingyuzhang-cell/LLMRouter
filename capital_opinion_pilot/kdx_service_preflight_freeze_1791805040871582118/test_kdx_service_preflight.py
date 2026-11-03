import unittest
from kdx_service_preflight import metadata_request
class Tests(unittest.TestCase):
 def test_health(self):self.assertEqual(metadata_request('GET','/health')['path'],'/health')
 def test_model_metadata(self):self.assertEqual(metadata_request('GET','/v1/models')['method'],'GET')
 def test_generation_forbidden(self):
  for path in ['/v1/completions','/v1/chat/completions','/v1/tokenize']:
   with self.assertRaises(ValueError):metadata_request('POST',path)
if __name__=='__main__':unittest.main()
