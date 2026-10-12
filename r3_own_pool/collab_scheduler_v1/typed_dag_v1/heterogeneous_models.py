"""Explicit type baseline and serial local service; no learned routing claim."""
import hashlib,json,os,socket,subprocess,time
from pathlib import Path
from urllib import request
from .protocol import ValidationError
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import append,StopRun

TYPE_BASELINE={'extraction':'medium','reasoning':'large','verification':'coder'}

def allocate(graph,bindings,policy='heterogeneous_type_baseline'):
    before=graph.content_hash;assign={}
    if policy not in ('heterogeneous_type_baseline','single_medium_baseline'):raise ValueError('Unknown allocation policy')
    for n in graph.nodes:
        # Tool nodes do not invoke a model; executor still requires an assignment entry.
        slot='medium' if n.node_type=='transformation' or policy=='single_medium_baseline' else TYPE_BASELINE[n.node_type]
        if slot not in bindings:raise ValidationError('Selected model unavailable: '+slot)
        assign[n.node_id]=slot
    used={assign[n.node_id] for n in graph.nodes if n.node_type!='transformation'}
    if graph.content_hash!=before:raise AssertionError('Allocation changed graph')
    return dict(graph_hash=before,policy=policy,assignment=assign,llm_models=sorted(used),heterogeneous=len(used)>1,learned=False,optimality_claim=False,rule=TYPE_BASELINE if policy=='heterogeneous_type_baseline' else {'all_llm':'medium'},tool_model_entries='placeholders; no tool LLM call')

def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(8*1024*1024),b''):h.update(data)
    return h.hexdigest()

def audit_pool(configs,provenance_dir,*,verify_weights=True,tokenizer_loader=None):
    result={};paths=set();names=set();identities=set()
    for slot,cfg in configs.items():
        path=Path(cfg['path']).resolve()
        if path in paths or cfg['served'] in names:raise ValidationError('Aliased model binding')
        paths.add(path);names.add(cfg['served'])
        conf=json.loads((path/'config.json').read_text());gen=json.loads((path/'generation_config.json').read_text())
        provenance_path=Path(provenance_dir)/(slot+'_MODEL_PROVENANCE.json');provenance=json.loads(provenance_path.read_text())
        for name,expected in provenance['config_sha256'].items():
            if file_sha(path/name)!=expected:raise ValidationError('Model configuration changed: '+slot+'/'+name)
        weights=provenance['weight_sha256'];actual={}
        for name,expected in weights.items():
            if not (path/name).is_file():raise ValidationError('Missing weights: '+slot+'/'+name)
            if verify_weights:
                actual[name]=file_sha(path/name)
                if actual[name]!=expected:raise ValidationError('Weights changed: '+slot+'/'+name)
        identity=hashlib.sha256(json.dumps(actual if verify_weights else weights,sort_keys=True).encode()).hexdigest()
        if identity in identities:raise ValidationError('Two bindings use the same checkpoint content')
        identities.add(identity)
        toks={n:file_sha(path/n) for n in ('tokenizer.json','tokenizer_config.json')}
        tok=tokenizer_loader(str(path)) if tokenizer_loader else None
        result[slot]=dict(path=str(path),served=cfg['served'],weights_identity_sha256=identity,weights_verified=verify_weights,weight_bytes=sum((path/n).stat().st_size for n in weights),config_sha256=provenance['config_sha256'],tokenizer_sha256=toks,tokenizer_loaded=tok is not None,tokenizer_class=type(tok).__name__ if tok is not None else None,context_limit=conf.get('max_position_embeddings'),service_context_limit=8192,output_limit=768,quantization=conf.get('quantization_config'),provenance_sha256=file_sha(provenance_path),service_loading='NOT_TESTED_THIS_ROUND',generation_config=gen)
    return result

def heterogeneous_wall_preflight(envelope,tasks,wall_seconds,*,load_cap_s=300,unload_cap_s=20):
    # Generation is contiguous on medium; any of six execution/recovery calls may switch.
    per_task_activations=1+sum(b.calls for b in envelope.stages.values() if b.phase=='execution')
    starts=tasks*per_task_activations
    required=starts*(load_cap_s+unload_cap_s)+tasks*envelope.totals()['requests']*envelope.timeout+envelope.cleanup
    evidence=dict(tasks=tasks,max_model_activations=starts,load_cap_s=load_cap_s,unload_cap_s=unload_cap_s,request_wall_cap_s=envelope.timeout,worst_service_wall_s=required,available_wall_s=wall_seconds,allowed=required<=wall_seconds,model_file_audit_and_cpu_time='Additional; global deadline stops if insufficient. No completion guarantee.')
    if not evidence['allowed']:raise StopRun('Heterogeneous wall envelope insufficient: '+json.dumps(evidence,sort_keys=True))
    return evidence

class SerialModelService:
    """Own one server at a time. Never stop a service owned by another session."""
    def __init__(self,configs,pool,directory,deadline,*,load_cap_s=300,port=8128,max_activations=14,budget=None,request_id_headers=False):
        self.configs=configs;self.pool=pool;self.directory=Path(directory);self.deadline=deadline;self.load_cap=load_cap_s;self.port=port;self.max_activations=max_activations;self.activations=0;self.budget=budget;self.startup_s=0.0;self.active=None;self.proc=None;self.log=None
        self.request_id_headers=request_id_headers
        self.opener=request.build_opener(request.ProxyHandler({}))
    def close(self):
        if self.proc is not None:
            proc=self.proc
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=15)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
            if self.log is not None:self.log.close()
            append(self.directory/'MODEL_LIFECYCLE.jsonl',dict(event='stopped',model=self.active,unix=time.time()))
        self.proc=self.log=None;self.active=None
    def activate(self,slot):
        if slot not in self.configs or slot not in self.pool or not self.pool[slot]['weights_verified']:raise ValidationError('Unavailable/unverified model: '+slot)
        self.deadline()
        if self.active==slot and self.proc is not None and self.proc.poll() is None:return
        if self.budget is not None:
            remaining_requests=sum(self.budget.envelope.remaining(c)['requests'] for c in self.budget.stage_counts.values())
            starts=self.max_activations-self.activations
            remaining_wall=self.budget.caps['wall_seconds']-(self.budget.clock()-self.budget.start)
            needed=starts*(self.load_cap+20)+remaining_requests*self.budget.envelope.timeout+self.budget.envelope.cleanup
            append(self.directory/'MODEL_WALL_PREFLIGHT.jsonl',dict(model=slot,remaining_activations=starts,remaining_requests=remaining_requests,remaining_wall_s=remaining_wall,needed_wall_s=needed,allowed=remaining_wall>=needed))
            if remaining_wall<needed:raise StopRun('Remaining model-switch wall envelope insufficient')
        self.close();self.deadline()
        if self.activations>=self.max_activations:raise StopRun('Model activation cap')
        gpu=subprocess.run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],capture_output=True,text=True)
        if gpu.returncode or gpu.stdout.strip():raise RuntimeError('GPU busy; not stopping external process')
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1',self.port))==0:raise RuntimeError('Endpoint occupied')
        cfg=self.configs[slot];start=time.monotonic();self.activations+=1;self.log=(self.directory/(slot+'_MODEL_SERVER.log')).open('a')
        self.proc=subprocess.Popen(['/root/autodl-tmp/r3_venv/bin/vllm','serve',cfg['path'],*(['--enable-request-id-headers'] if self.request_id_headers else []),'--served-model-name',cfg['served'],'--port',str(self.port),'--max-model-len','8192','--max-num-seqs','1','--gpu-memory-utilization','.90','--dtype','auto','--generation-config','vllm','--structured-outputs-config','{"backend":"xgrammar","disable_any_whitespace":true}'],stdout=self.log,stderr=subprocess.STDOUT,env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
        self.active=slot
        try:
            while True:
                self.deadline()
                if self.proc.poll() is not None:raise RuntimeError('Selected model service exited: '+slot)
                if time.monotonic()-start>=self.load_cap:raise StopRun('Model load deadline: '+slot)
                try:
                    with self.opener.open(f'http://127.0.0.1:{self.port}/health',timeout=2) as r:healthy=r.status==200
                except Exception:healthy=False
                if healthy:
                    with self.opener.open(f'http://127.0.0.1:{self.port}/v1/models',timeout=2) as r:ids={x['id'] for x in json.loads(r.read())['data']}
                    if cfg['served'] not in ids:raise RuntimeError('Endpoint model identity mismatch')
                    break
                time.sleep(1)
            self.startup_s+=time.monotonic()-start
            append(self.directory/'MODEL_LIFECYCLE.jsonl',dict(event='ready',model=slot,served=cfg['served'],weights_identity_sha256=self.pool[slot]['weights_identity_sha256'],startup_s=time.monotonic()-start,activation=self.activations,endpoint=f'http://127.0.0.1:{self.port}'))
        except BaseException:self.close();raise
    def check_provider(self,slot,provider_model):
        if slot!=self.active or provider_model!=self.configs[slot]['served']:raise RuntimeError('Requested/active/provider model mismatch; no fallback')

def prepare_metered_request(slot,prompt,key,budget,tokenizers,pool):
    """Count with selected model's own chat template; never a medium-tokenizer alias."""
    if slot not in tokenizers or slot not in pool:raise ValidationError('Tokenizer/model unavailable: '+slot)
    try:body=json.loads(prompt)
    except ValueError:body=json.loads(prompt.split('\n',1)[1])
    op=body.get('operation');contract=body.get('contract')
    maxout=768 if op in ('plan_typed_dag','repair_semantic_plan','plan_goal_ir','repair_goal_ir') else 384 if op=='review_coverage' else 160 if contract in ('verify_value.v1','verify_expression.v1') else 256
    ninput=len(tokenizers[slot].apply_chat_template([dict(role='user',content=prompt)],tokenize=True,add_generation_prompt=True))
    if ninput+maxout>min(8192,pool[slot]['context_limit']):raise StopRun('Selected model context limit')
    kind={'plan_typed_dag':'plan','repair_semantic_plan':'repair','plan_goal_ir':'plan','repair_goal_ir':'repair','review_coverage':'review'}.get(op,'recovery' if budget.recovery_mode and key.split(':')[3]==budget.recovery_target else 'node')
    reservation=budget.check_request(kind,ninput,maxout)
    append(budget.path.parent/'REQUEST_PRECHECK.jsonl',dict(task=budget.task,phase=budget.phase,model=slot,served=pool[slot]['served'],weights_identity_sha256=pool[slot]['weights_identity_sha256'],tokenizer_sha256=pool[slot]['tokenizer_sha256'],prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),input_tokens=ninput,max_output_tokens=maxout,reservation=reservation,operation=op,contract=contract))
    return dict(body=body,maxout=maxout,slot=slot,ninput=ninput)
