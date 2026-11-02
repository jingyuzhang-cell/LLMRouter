import copy,json,socket,tempfile,unittest,os,shutil
from pathlib import Path
import batch
from paid_transport import Transport,Guard
import score

def fixture(body,timeout):
 x=json.loads(body['messages'][0]['content'].split('\n')[-1]);n=x['node_id'];c=x['contract'];d=x['input']
 if c=='capital.extract.v1':out={'claims':[{'id':n+':c1','statement':'SYNTHETIC TEST ONLY','citations':[d['evidence'][0]['id']]}]}
 elif c=='capital.report.v1':out={'report':{'text':'SYNTHETIC TEST ONLY '*200,'unknown':[],'citations':[f['id'] for f in d['findings']]}}
 else:out={'findings':[{'id':n+':f1','statement':'SYNTHETIC TEST ONLY','status':'UNKNOWN','citations':[d['claims'][0]['id']]}]}
 return {'model':body['model'],'choices':[{'finish_reason':'stop','message':{'content':json.dumps(out)}}],'usage':{'prompt_tokens':100,'completion_tokens':60,'total_tokens':160}}

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.old=socket.socket;socket.socket=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('NETWORK_FORBIDDEN'));self.addCleanup(setattr,socket,'socket',self.old)
  self.config=json.loads((batch.ROOT/'EXPERIMENT_CONFIG.json').read_text())
 def test_one_batch_full_outputs_shared_snapshots_and_40_requests(self):
  out=Path(self.tmp.name)/'run';pairs=batch.execute(self.config,out,send=fixture)
  ledger=json.loads((out/'LEDGER.json').read_text());self.assertEqual(len(ledger['calls']),40)
  self.assertFalse(ledger['stopped']);self.assertEqual(len(pairs),3)
  for pair in pairs:
   a,b=pair['arms'];self.assertEqual(a['snapshot_sha256'],b['snapshot_sha256']);self.assertEqual(a['decision_inputs_sha256'],b['decision_inputs_sha256'])
   for arm in (a,b):
    self.assertTrue(arm['task_complete']);raw=json.loads((out/arm['full_output_file']).read_text())
    self.assertGreater(len(raw['outputs']['answer']['text']),160)
    self.assertEqual({r['node'] for r in raw['trace']},{'timeline','relations','verify','report'})
    self.assertIsNone(arm['Q'])
  self.assertEqual(score.export(out),6)
  with self.assertRaisesRegex(ValueError,'REVIEW_PENDING'):score.score(out,out/'blind_review/DECISIONS_TEMPLATE.json')
  if os.environ.get('DYNAMIC_PI_OFFLINE_EVIDENCE_DIR'):shutil.copytree(out,os.environ['DYNAMIC_PI_OFFLINE_EVIDENCE_DIR'])
 def test_http_failure_stops_batch_unknown_billing(self):
  def broken(body,timeout):raise TimeoutError('fixture transport')
  out=Path(self.tmp.name)/'failed';batch.execute(self.config,out,send=broken)
  ledger=json.loads((out/'LEDGER.json').read_text());self.assertTrue(ledger['stopped']);self.assertEqual(len(ledger['calls']),1)
  self.assertEqual(ledger['calls'][0]['status'],'UNKNOWN')
  result=json.loads((out/'RESULT.json').read_text());self.assertEqual(sum(len(p['arms']) for p in result['pairs']),6)
 def test_normal_invalid_output_is_not_transport_stop(self):
  def malformed(body,timeout):
   r=fixture(body,timeout);r['choices'][0]['message']['content']='not json';return r
  out=Path(self.tmp.name)/'invalid';batch.execute(self.config,out,send=malformed)
  ledger=json.loads((out/'LEDGER.json').read_text());self.assertFalse(ledger['stopped']);self.assertEqual(len(ledger['calls']),2)
  result=json.loads((out/'RESULT.json').read_text());self.assertEqual(len(result['pairs']),3)
  self.assertTrue(all(p['status']=='PROFILE_INCOMPLETE_REFUSAL' for p in result['pairs']))
 def test_preflight_cannot_dispatch(self):
  c,issues=batch.preflight();self.assertIn('NO_MATCHING_BATCH_AUTHORIZATION',issues);self.assertNotIn('REFERENCE_POLICY_NOT_ACCEPTED',issues)

if __name__=='__main__':unittest.main(verbosity=2)
