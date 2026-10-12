import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from .request_trace import new_id,exchange
from .ab_review_diagnostic import request_wall_gate
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun
class TraceTests(unittest.TestCase):
 def test_unique(self):self.assertEqual(len({new_id() for _ in range(100)}),100)
 def perform(self,timeout=60,error=None):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'trace';rid=new_id()
   class Response:
    status=200;headers={'X-Request-Id':rid}
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self):return b'{}'
   opener=SimpleNamespace(open=lambda *a,**k:Response())
   if error:opener.open=lambda *a,**k:(_ for _ in ()).throw(error)
   if error:
    with self.assertRaises(type(error)):exchange(opener,object(),timeout,p,rid)
   else:self.assertEqual(exchange(opener,object(),timeout,p,rid),(200,'{}'))
   return [json.loads(l) for l in p.read_text().splitlines()]
 def test_correlation(self):
  r=self.perform();self.assertEqual(r[0]['request_id'],r[1]['server_request_id'])
 def test_unknown_server_stages(self):
  r=self.perform();self.assertTrue(all(r[0][x]=='UNKNOWN' for x in ('schema','prefill','decode')))
 def test_both_timeout_configs(self):
  for n in (30,60):self.assertEqual(self.perform(n)[0]['timeout_s'],n)
 def test_response_complete(self):self.assertEqual(self.perform()[-1]['stage'],'body_complete')
 def test_disconnect_may_continue(self):
  r=self.perform(error=StopRun('Request wall timeout'));self.assertTrue(r[-1]['server_may_continue']);self.assertFalse(r[-1]['server_cancel_confirmed'])
 def test_no_retry(self):self.assertEqual(sum(x['stage']=='dispatch' for x in self.perform(error=TimeoutError())),1)
 def test_wall_refusal60(self):
  with self.assertRaises(StopRun):request_wall_gate(575,dict(wall_seconds=664,request_timeout_s=60,cleanup_reserve_s=30))
