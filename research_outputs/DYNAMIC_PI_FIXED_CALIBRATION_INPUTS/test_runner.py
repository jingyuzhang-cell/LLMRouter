import json,tempfile,unittest
from pathlib import Path
from run_calibration import execute,ROOT
RAW=Path('/root/research_outputs/DYNAMIC_PI_DEV_EXPLORATION_RUN/cal_1.RAW.json')
class RunnerTests(unittest.TestCase):
 def sender(self,calls,fail=False):
  saved=json.loads(RAW.read_text())['cache']
  def send(body,timeout):
   calls.append(body)
   if fail:raise TimeoutError('OFFLINE_INJECTED_TIMEOUT')
   node=next(n for n in saved if n+':' in body['messages'][0]['content'])
   # Deliberately invalid first response; all others reuse saved responses ONLY as fixtures.
   output={'schema':saved[node]['output']} if len(calls)==1 else saved[node]['output']
   return {'model':body['model'],'choices':[{'message':{'content':json.dumps(output)},'finish_reason':'stop'}],
           'usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200}}
  return send
 def test_normal_failure_continues_and_keeps_unknown_quality(self):
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   r=execute(Path(d)/'run',send=self.sender(calls))
   self.assertEqual(len(calls),8);self.assertEqual(r['rows'][0]['status'],'MODEL_FAILURE')
   self.assertEqual(sum(x['status']=='CONTRACT_COMMITTED' for x in r['rows']),7)
   self.assertTrue(all(x['semantic_quality'] is None for x in r['rows']))
   self.assertEqual(r['origin'],'OFFLINE_CONTROL_TEST')
   self.assertIsNone(r['stop'])
 def test_transport_exception_stops_without_retry(self):
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   r=execute(Path(d)/'run',send=self.sender(calls,fail=True))
   self.assertEqual(len(calls),1);self.assertEqual(r['stop'],'SYSTEM_STOP')
   self.assertTrue(r['ledger']['stopped'])
 def test_no_live_lock_from_offline_tests(self):
  self.assertFalse((ROOT/'RUN_ONCE.lock').exists())
if __name__=='__main__':unittest.main()
