import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from strict_meter import StrictMeter
from pilot_common import BudgetExceeded,Meter
class Fake(StrictMeter):
 def _transport(self,*a):
  self.sent=getattr(self,'sent',0)+1
  if getattr(self,'fail',False):raise TimeoutError('mock')
  return {'usage':getattr(self,'usage',{'input_tokens':4,'output_tokens':6}),'text':'{}','stop_reason':getattr(self,'stop','end_turn'),'latency_s':0.1}
class Tests(unittest.TestCase):
 def make(self,cls=Fake,cap=20):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);return cls(ledger_path=Path(t.name)/'new.jsonl',max_calls=2,max_guaranteed_actual=cap)
 def call(self,m,p='a',upper=4):return m.call('glm53','s','u',max_tokens=6,purpose=p,input_upper=upper,bound_evidence='Stub exact input count')
 def test_exact_boundary(self):
  m=self.make(cap=10);self.call(m);self.assertEqual(m.sent,1)
 def test_insufficient_before_transport(self):
  m=self.make(cap=9)
  with self.assertRaises(BudgetExceeded):self.call(m)
  self.assertFalse(hasattr(m,'sent'))
 def test_unknown_input_rejected(self):
  m=self.make()
  with self.assertRaises(BudgetExceeded):self.call(m,upper=None)
  self.assertFalse(hasattr(m,'sent'))
 def test_pending_survives_crash(self):
  m=self.make();m.fail=True
  with self.assertRaises(TimeoutError):self.call(m)
  n=Fake(ledger_path=m.ledger,max_calls=2,max_guaranteed_actual=19)
  with self.assertRaisesRegex(BudgetExceeded,'UNKNOWN_PRIOR'):self.call(n)
  with self.assertRaisesRegex(BudgetExceeded,'UNKNOWN_PRIOR'):self.call(n,p='b')
  self.assertFalse(hasattr(n,'sent'))
 def test_completed_dedup_restart(self):
  m=self.make();self.call(m);n=Fake(ledger_path=m.ledger,max_calls=2,max_guaranteed_actual=20);self.call(n);self.assertFalse(hasattr(n,'sent'))
 def test_truncated_settled_no_retry(self):
  m=self.make();m.stop='max_tokens'
  for i in range(2):
   with self.assertRaises(BudgetExceeded):self.call(m)
  self.assertEqual(m.sent,1);self.assertEqual(m.summary()['charged_tokens'],10);self.assertEqual(json.loads(m.journal.read_text().splitlines()[-1])['actual_tokens'],10)
 def test_unknown_usage_keeps_full_reserve(self):
  m=self.make();m.usage={}
  with self.assertRaises(BudgetExceeded):self.call(m)
  self.assertEqual(len(m.journal.read_text().splitlines()),1)
 def test_provider_overshoot_latched(self):
  m=self.make();m.usage={'input_tokens':50,'output_tokens':6}
  with self.assertRaisesRegex(BudgetExceeded,'BOUND_VIOLATION'):self.call(m)
  with self.assertRaises(BudgetExceeded):self.call(m,p='b')
  self.assertEqual(m.sent,1)
 def test_original_http_output_setting(self):
  # Real transport construction with Mock HTTP, no key/config/network access.
  class Response:
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def read(self):return json.dumps({'content':[{'type':'text','text':'{}'}],'usage':{'input_tokens':4,'output_tokens':6},'stop_reason':'end_turn'}).encode()
  m=self.make(cls=StrictMeter);seen=[]
  def opening(req,**kw):seen.append(json.loads(req.data));return Response()
  with patch('pilot_common._api_key',return_value='MOCK'),patch('pilot_common.urllib.request.urlopen',side_effect=opening):self.call(m)
  self.assertEqual(seen[0]['max_tokens'],6);self.assertEqual(seen[0]['thinking'],{'type':'disabled'})
if __name__=='__main__':unittest.main()
