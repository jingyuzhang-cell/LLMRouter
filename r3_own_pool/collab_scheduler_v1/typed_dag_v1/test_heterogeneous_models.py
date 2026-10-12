import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from .heterogeneous_models import allocate,prepare_metered_request,SerialModelService,heterogeneous_wall_preflight,audit_pool,file_sha
from .protocol import ValidationError
from .test_producer_plan import producers
from .producer_plan import compile_producer_plan
from .semantic_ids import assemble_semantic
from .test_semantic_ids import CTX
from .fresh_acceptance import ScopedBudget,CAPS
from .resource_envelope import ResourceEnvelope
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun

CONFIG={s:dict(path='/test/'+s,served='different/'+s) for s in ('medium','large','coder')}
POOL={s:dict(served='different/'+s,context_limit=32768,weights_verified=True,weights_identity_sha256='weights-'+s,tokenizer_sha256={'tokenizer.json':'tok-'+s}) for s in CONFIG}
class Tokenizer:
 def __init__(self,n):self.n=n
 def apply_chat_template(self,*a,**k):return [0]*self.n

def graph(size=5):return assemble_semantic(compile_producer_plan(producers(size))[0],'hetero-stub',CTX,{'answer':'sum'})
class HeterogeneousTests(unittest.TestCase):
 def budget(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);b=ScopedBudget(Path(t.name),{**CAPS,'new_total_tokens':56000,'wall_seconds':5400});b.bind_envelope(ResourceEnvelope(phase_tokens={'generation':14000,'execution':14000}),['hetero-stub']);b.select('hetero-stub','execution');return b
 def test_three_models_and_graph_unchanged(self):
  g=graph();h=g.content_hash;a=allocate(g,CONFIG);self.assertEqual(a['llm_models'],['coder','large','medium']);self.assertTrue(a['heterogeneous']);self.assertFalse(a['learned']);self.assertEqual(g.content_hash,h)
 def test_single_baseline_label(self):
  a=allocate(graph(),CONFIG,'single_medium_baseline');self.assertFalse(a['heterogeneous']);self.assertEqual(a['llm_models'],['medium'])
 def test_unavailable_model_rejected(self):
  with self.assertRaises(ValidationError):allocate(graph(),{'medium':1})
 def test_three_nodes(self):self.assertEqual(len(allocate(graph(3),CONFIG)['assignment']),3)
 def test_multiroot_forward_nodes(self):
  p=producers(5);p['nodes'].reverse();g=assemble_semantic(compile_producer_plan(p)[0],'hetero-stub',CTX,{'answer':'sum'});self.assertEqual(sum(not n.dependencies for n in g.nodes),2);allocate(g,CONFIG)
 def test_separate_tokenizers(self):
  b=self.budget();tok={s:Tokenizer(n) for s,n in zip(CONFIG,(10,20,30))};prompt=json.dumps({'contract':'expression.v1'})
  sizes=[prepare_metered_request(s,prompt,'typed:dag:v1:x:attempt1:task',b,tok,POOL)['ninput'] for s in CONFIG];self.assertEqual(sizes,[10,20,30])
 def test_tokenizer_unavailable_no_fallback(self):
  b=self.budget()
  with self.assertRaises(ValidationError):prepare_metered_request('coder','{}','key',b,{'medium':Tokenizer(10)},POOL)
 def test_tokenizer_growth_bound(self):
  b=self.budget()
  with self.assertRaises(StopRun):prepare_metered_request('large',json.dumps({'contract':'expression.v1'}),'typed:dag:v1:x:y:z',b,{'large':Tokenizer(2049)},POOL)
 def test_provider_mismatch(self):
  with tempfile.TemporaryDirectory() as d:
   m=SerialModelService(CONFIG,POOL,d,lambda:None);m.active='large'
   with self.assertRaises(RuntimeError):m.check_provider('large','different/medium')
   m.check_provider('large','different/large')
 def test_20min_rejected(self):
  with self.assertRaises(StopRun):heterogeneous_wall_preflight(ResourceEnvelope(),2,1200)
 def test_90min_envelope(self):
  r=heterogeneous_wall_preflight(ResourceEnvelope(),2,5400);self.assertEqual(r['max_model_activations'],14);self.assertEqual(r['worst_service_wall_s'],5110)
 def test_serial_switch_and_load_failure_stub(self):
  class Process:
   code=None
   def poll(self):return self.code
   def terminate(self):self.code=0
   def kill(self):self.code=-9
   def wait(self,timeout):return self.code
  class Response:
   status=200
   def __init__(self,m):self.m=m
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def read(self):return json.dumps({'data':[{'id':'different/'+self.m.active}]}).encode()
  with tempfile.TemporaryDirectory() as d:
   m=SerialModelService(CONFIG,POOL,d,lambda:None);m.opener=Mock();m.opener.open.side_effect=lambda *a,**k:Response(m)
   with patch('subprocess.run',return_value=Mock(returncode=0,stdout='')),patch('socket.socket') as sock,patch('subprocess.Popen',side_effect=lambda *a,**k:Process()) as start:
    sock.return_value.__enter__.return_value.connect_ex.return_value=111
    m.activate('medium');m.activate('medium');m.activate('large');m.activate('coder');self.assertEqual(start.call_count,3);self.assertEqual(m.active,'coder');m.close()
    m.opener.open.side_effect=RuntimeError('Stub service failure');m.load_cap=0
    with self.assertRaises(StopRun):m.activate('large')
    self.assertIsNone(m.active)
 def test_model_unverified_no_start(self):
  with tempfile.TemporaryDirectory() as d:
   pool=copy.deepcopy(POOL);pool['large']['weights_verified']=False;m=SerialModelService(CONFIG,pool,d,lambda:None)
   with patch('subprocess.Popen') as start:
    with self.assertRaises(ValidationError):m.activate('large')
    start.assert_not_called()
 def test_aliased_path_rejected_offline(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);cfg={};prov=root/'provenance';prov.mkdir()
   for s in ('medium','coder'):
    p=root/s;p.mkdir();(p/'config.json').write_text('{"max_position_embeddings":32768}');(p/'generation_config.json').write_text('{}');(p/'tokenizer.json').write_text('{}');(p/'tokenizer_config.json').write_text('{}');(p/'weights.safetensors').write_text(s)
    cfg[s]=dict(path=str(p),served='different/'+s)
    (prov/(s+'_MODEL_PROVENANCE.json')).write_text(json.dumps(dict(config_sha256={n:file_sha(p/n) for n in ('config.json','generation_config.json')},weight_sha256={'weights.safetensors':file_sha(p/'weights.safetensors')})))
   pool=audit_pool(cfg,prov);self.assertNotEqual(pool['medium']['weights_identity_sha256'],pool['coder']['weights_identity_sha256'])
   cfg['coder']['path']=cfg['medium']['path']
   with self.assertRaises(ValidationError):audit_pool(cfg,prov)

class MixedPipelineTests(unittest.TestCase):
 def pipeline(self,size,recover=False):
  from .execution import TypedExecutor
  from .generation import InitialDAGGenerator
  from .protocol import Limits
  from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
  with tempfile.TemporaryDirectory() as d:
   b=ScopedBudget(Path(d),{**CAPS,'new_total_tokens':56000,'wall_seconds':5400});b.bind_envelope(ResourceEnvelope(phase_tokens={'generation':14000,'execution':14000}),['hetero-stub']);b.select('hetero-stub','generation')
   toks={s:Tokenizer(n) for s,n in zip(CONFIG,(100,120,140))};active=[None];switches=[];requests=[];reasoning_attempt=[0]
   def switch(s):
    if active[0]!=s:switches.append(s);active[0]=s
   def dispatch(s,p):
    self.assertEqual(s,active[0]);requests.append(s)
    try:x=json.loads(p)
    except ValueError:x=json.loads(p.split('\n',1)[1])
    op=x.get('operation')
    if op=='plan_typed_dag':answer=json.dumps(producers(size))
    elif op=='review_coverage':answer=json.dumps(dict(status='PASS',error_code='NONE',node_refs=[],evidence='Stub fixture only.',replan=False))
    elif x['contract']=='facts.v1':answer=json.dumps(dict(facts=[dict(value=int(x['inputs']['context']),evidence=x['inputs']['context'])]))
    elif x['contract']=='expression.v1':
     reasoning_attempt[0]+=1;answer=json.dumps(dict(expression='bad_ref' if recover and reasoning_attempt[0]==1 else '+'.join(x['available_fact_variables'])))
    else:answer=json.dumps(dict(value=x['inputs']['value']))
    n=toks[s].n
    return dict(status='delivered',answer=answer,provider_model=CONFIG[s]['served'],usage=dict(prompt_tokens=n,completion_tokens=10,total_tokens=n+10),finish_reason='stop')
   class StubMetered(MeteredExecutor):
    def call(self,key,model,prompt,uid=None,node=None):
     prepare_metered_request(model,prompt,key,b,toks,POOL)
     return super().call(key,model,prompt,uid,node)
   ex=StubMetered(Path(d),b,dispatch,switch,{s:c['served'] for s,c in CONFIG.items()})
   g=InitialDAGGenerator(ex,'medium',limits=Limits(max_nodes=5,max_llm_calls=5,max_depth=5)).generate('hetero-stub','financial_arithmetic',CTX,{'answer':'sum'})
   self.assertEqual(g.status,'GENERATED');before=g.graph.content_hash;a=allocate(g.graph,ex.bindings);b.release_unused('generation');b.select('hetero-stub','execution')
   run=TypedExecutor(g.graph,a['assignment'],ex,CTX);result=run.run()
   if recover:
    self.assertEqual(result['status'],'INCOMPLETE');target=next(n.node_id for n in g.graph.nodes if n.node_type=='reasoning');b.recovery_mode=True;b.recovery_target=target
    result=run.recover_failed(target,a['assignment'][target],max_attempts=2);self.assertEqual(b.stage_counts['hetero-stub']['recovery'],1)
   self.assertEqual(result['status'],'COMPLETE');self.assertEqual(result['final_outputs']['answer'],5 if size==5 else 2);self.assertEqual(g.graph.content_hash,before)
   for r in ex.events:self.assertEqual(r['response']['provider_model'],CONFIG[r['model']]['served'])
   if size==5:self.assertEqual(set(requests),set(CONFIG))
   self.assertEqual(b.pending,{});self.assertEqual(b.attempts,len(requests))
   checks=[json.loads(x) for x in (Path(d)/'REQUEST_PRECHECK.jsonl').read_text().splitlines()]
   self.assertTrue(all(c['input_tokens']==toks[c['model']].n for c in checks));self.assertIn('large',switches)
 def test_five_node_mixed_end_to_end(self):self.pipeline(5)
 def test_three_node_mixed_end_to_end(self):self.pipeline(3)
 def test_failed_reasoning_same_selected_model_recovery(self):self.pipeline(5,True)
