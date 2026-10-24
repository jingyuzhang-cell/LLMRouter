"""Offline cache order, identity and real-engine facade regression."""
import copy,hashlib,json,socket,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from .stub_engine import StubEngine,StubModelServer,InjectedClock
from .supplementary_runner import RealServer,RealEngine
P=json.loads((Path(__file__).parent/'PRIORS_STUB_V1.json').read_text())
TASK=dict(uid='cache-test',question='Sum source facts?',ctx_table='table',ctx_text='text')
ANS={('e1','plain'):'{"facts":[]}',('e2','plain'):'{"facts":[]}',('r','plain'):'{"expression":"1"}'}
def dummy_call(*args):raise AssertionError('no real transport')
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.count=0
  self.net=patch('socket.socket',side_effect=AssertionError('no network'));self.net.start()
 def tearDown(self):self.net.stop();self.tmp.cleanup()
 def engine(self,server=None,snapshot=None):
  self.count+=1;s=server or StubModelServer(copy.deepcopy(ANS),copy.deepcopy(P));e=StubEngine(self.root/str(self.count),s,InjectedClock(),profile_key='v3_compat');e._cache=dict(snapshot or {});return e
 def call(self,e,node='e1',model='large',**kw):return e._call('A',dict(TASK),node,'plain',model,**kw)
 def test_hit_skips_switch_and_historical_service(self):
  e=self.engine();a=self.call(e);e.current_model='coder';before=e.clock.time();sw=e.switch_idx;requests=e.requests_total;tokens=e.tokens_total
  b=self.call(e);self.assertTrue(b['cached']);self.assertEqual(e.current_model,'coder');self.assertEqual(e.switch_idx,sw);self.assertEqual(e.clock.time(),before);self.assertEqual(e.requests_total,requests);self.assertEqual(e.tokens_total,tokens);self.assertEqual(b['latency_s'],0);self.assertEqual(b['cached_response_latency_s'],a['latency_s']);self.assertEqual(e.tasks[TASK['uid']].service_sum,a['latency_s'])
 def test_miss_switches(self):
  e=self.engine();self.call(e);e.current_model='coder';sw=e.switch_idx;b=self.call(e,node='e2');self.assertTrue(b['physical']);self.assertEqual(e.switch_idx,sw+1)
 def test_model_not_aliased(self):
  e=self.engine();self.call(e);b=self.call(e,model='medium');self.assertFalse(b['cached'])
 def test_version_not_aliased(self):
  e=self.engine();self.call(e);e.server.priors['version']='changed';self.assertFalse(self.call(e)['cached'])
 def test_input_question_not_aliased(self):
  e=self.engine();self.call(e);t=dict(TASK,question='Different question');self.assertFalse(e._call('A',t,'e1','plain','large')['cached'])
 def test_source_change_rejected_before_switch(self):
  e=self.engine();self.call(e);e.current_model='coder';sw=e.switch_idx
  with self.assertRaises(ValueError):e._call('A',dict(TASK,ctx_table='changed'),'e1','plain','large')
  self.assertEqual(e.switch_idx,sw)
 def test_parameter_and_contract_kind_not_aliased(self):
  e=self.engine();self.call(e);e.profile_key=None;self.assertFalse(self.call(e)['cached']);e.server.answers[('e1','esc')]='{"facts":[]}'
  self.assertFalse(e._call('A',dict(TASK),'e1','esc','large')['cached'])
 def test_upstream_change_invalidates_downstream(self):
  e=self.engine();self.call(e);self.call(e,node='e2');self.call(e,node='r',model='medium');e.tasks[TASK['uid']].answers['e1']='changed';self.assertFalse(self.call(e,node='r',model='medium')['cached'])
 def test_recovery_no_cache_and_fault_do_not_poison(self):
  e=self.engine();a=self.call(e);e.server.set_fault(TASK['uid'],'e1','large','bad');self.assertEqual(self.call(e)['answer'],'bad');e.server.faults.clear();self.assertEqual(self.call(e)['answer'],a['answer']);self.assertTrue(self.call(e,no_cache=True)['physical'])
 def test_legacy_snapshot_not_trusted(self):
  e=self.engine();a=self.call(e);legacy={('large',a['input_sha']):dict(answer='bad',usage={'total_tokens':0},latency_s=999)}
  e2=self.engine(e.server,legacy);b=self.call(e2);self.assertTrue(b['physical']);self.assertNotEqual(b['answer'],'bad')
 def test_new_snapshot_no_switch(self):
  e=self.engine();self.call(e);e2=self.engine(e.server,e._cache);b=self.call(e2);self.assertTrue(b['cached']);self.assertEqual(e2.switch_idx,0)
 def test_timeout_does_not_create_cache_or_success(self):
  e=self.engine();e.server.draw=lambda *a,**k:(_ for _ in ()).throw(TimeoutError('offline timeout'))
  with self.assertRaises(TimeoutError):self.call(e)
  self.assertFalse(e._cache);self.assertEqual(e.requests_total,0)
 def test_early_stop_before_dispatch(self):
  e=self.engine();e._switch=lambda *a:(_ for _ in ()).throw(RuntimeError('deadline'))
  with self.assertRaises(RuntimeError):self.call(e)
  self.assertEqual(e.server.invocations,0);self.assertFalse(e._cache)
 def test_duplicate_run_still_rejected(self):
  e=self.engine()
  with self.assertRaises(ValueError):StubEngine(e.directory,e.server,InjectedClock())
 def test_real_facade_verified_cache_without_gpu(self):
  root=self.root/'models';root.mkdir();model=root/'large';model.mkdir()
  for name in ('config.json','weights.bin','tokenizer.json','tokenizer_config.json'):(model/name).write_text(name)
  sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
  raw=root/'router_v2/label_repair_experiment/raw';raw.mkdir(parents=True)
  manifest={'config_sha256':{'config.json':sha(model/'config.json')},'weight_sha256':{'weights.bin':sha(model/'weights.bin')}}
  (raw/'large_MODEL_PROVENANCE.json').write_text(json.dumps(manifest));src=root/'fake_module.py';src.write_text('frozen transport/config')
  mod=SimpleNamespace(ROOT=root,MODELS={'large':{'path':str(model),'served':'test-large'}},sha=sha,__file__=str(src),call_model=dummy_call)
  clock=InjectedClock();manager=SimpleNamespace(state={'model':'coder'},starts=0,_mod=lambda:mod)
  def start(m):manager.starts+=1;clock.advance(10);manager.state['model']=m
  manager.start=start;manager.stop_current=lambda:None
  server=RealServer({},manager,None,{TASK['uid']:TASK},self.root);server._b=lambda:(mod,None,None);server.build_prompt=lambda n,k,u:json.dumps(dict(task=TASK,node=n,kind=k));server.draw=lambda *a,**k:dict(answer='{"facts":[]}',usage={'total_tokens':1},latency_s=.2)
  e=RealEngine(self.root/'real1',server,clock,seed='test',manager=manager);server.engine=e;self.call(e)
  e2=RealEngine(self.root/'real2',server,clock,seed='test',manager=manager);server.engine=e2;e2._cache=dict(e._cache);e2.current_model='coder';starts=manager.starts
  self.assertTrue(self.call(e2)['cached']);self.assertEqual(manager.starts,starts)
  (model/'tokenizer.json').write_text('new tokenizer');self.assertFalse(self.call(e2)['cached'])
  (model/'weights.bin').write_text('wrong checkpoint')
  with self.assertRaises(ValueError):self.call(e2)
  self.assertEqual(manager.starts,starts+1)
if __name__=='__main__':unittest.main()
