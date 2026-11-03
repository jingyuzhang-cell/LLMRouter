import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from strict_meter import StrictMeter
from kdx_local_single import attach_local_transport
class Tok:
 def apply_chat_template(self,*a,**kw):return [1,2,3]
class Tests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.m=StrictMeter(Path(self.t.name)/'l.jsonl',max_calls=1,max_guaranteed_actual=7)
 def test_integer_prompt_and_reservation(self):
  count=attach_local_transport(self.m,Tok(),'qwen','http://127.0.0.1:8000')
  class Resp:
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def read(self):return json.dumps({'model':'qwen','usage':{'prompt_tokens':3,'completion_tokens':2},'choices':[{'text':'{}','finish_reason':'stop'}]}).encode()
  def fake(req,timeout):
   self.assertEqual(json.loads(req.data)['prompt'],[1,2,3]);self.assertEqual(self.m.summary()['pending_reserve'],7);return Resp()
  with patch('urllib.request.urlopen',side_effect=fake):self.m.call('local_qwen7b','s','u',max_tokens=4,input_upper=count('s','u'),bound_evidence='MOCK_IDS')
 def test_context_rejected(self):
  attach_local_transport(self.m,Tok(),'qwen','http://127.0.0.1:8000',4)
  with patch('urllib.request.urlopen') as http:
   with self.assertRaises(ValueError):self.m.call('local_qwen7b','s','u',max_tokens=4,input_upper=3,bound_evidence='MOCK')
   http.assert_not_called()
 def test_remote_and_legacy_rejected(self):
  with self.assertRaises(ValueError):attach_local_transport(self.m,Tok(),'qwen','https://remote')
if __name__=='__main__':unittest.main()
