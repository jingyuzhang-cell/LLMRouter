"""Approved fresh-task acceptance; no history, resume, or search entrypoints."""
import argparse,fcntl,hashlib,json,time,socket,subprocess,os,shutil,signal,threading
from pathlib import Path
from urllib import request,error
from .generation import InitialDAGGenerator
from .execution import TypedExecutor
from .protocol import Limits,validate
from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget,StopRun,append
from static_dag_v0 import run as engine

CAPS=dict(new_request_attempts=24,new_total_tokens=24000,request_token_reservation=8192,max_output_tokens=768,wall_seconds=1200,logical_calls_per_task_config_state=30)

class ScopedBudget(Budget):
    def __init__(self,path,caps=CAPS):
        super().__init__(path,dict(caps));self.task=None;self.phase=None;self.next_reservation=None;self.buckets={};self.task_attempts={};self.pending_bucket={};self.envelope=None;self.stage_counts={};self.next_kind=None;self.recovery_mode=False
    def bind_envelope(self,envelope,tasks):
        evidence=envelope.to_dict()
        try:envelope.admit(tasks,self.caps)
        except StopRun as e:
            append(self.path.parent/'ENVELOPE_ADMISSION.jsonl',dict(allowed=False,reason=str(e),envelope=evidence));raise
        self.envelope=envelope;self.stage_counts={t:{} for t in tasks}
        append(self.path.parent/'ENVELOPE_ADMISSION.jsonl',dict(allowed=True,tasks=tasks,envelope=evidence))
    def check_request(self,kind,ninput,maxout):
        e=self.envelope
        if e is None:raise StopRun('No admitted end-to-end resource envelope')
        reservation=e.check_size(kind,ninput,maxout);bound=e.stages[kind]
        if bound.phase!=self.phase or self.task not in self.stage_counts:raise StopRun('Stage/task mismatch')
        counts=self.stage_counts[self.task]
        if counts.get(kind,0)>=bound.calls:raise StopRun('Stage request cap: '+kind)
        hypothetical=dict(counts);hypothetical[kind]=hypothetical.get(kind,0)+1
        future=e.remaining(hypothetical);same=e.remaining(hypothetical,self.phase)
        other=sum(e.remaining(c)['tokens'] for t,c in self.stage_counts.items() if t!=self.task)
        other_requests=sum(e.remaining(c)['requests'] for t,c in self.stage_counts.items() if t!=self.task)
        charged_phase=self.buckets.get((self.task,self.phase),0)
        reasons=[]
        if charged_phase+reservation+same['tokens']>e.phase_tokens[self.phase]:reasons.append('phase_future_tokens')
        if self.charged+reservation+future['tokens']+other>self.caps['new_total_tokens']:reasons.append('global_future_tokens')
        if self.task_attempts[self.task]+1+future['requests']>e.task_requests:reasons.append('task_future_requests')
        if self.attempts+1+future['requests']+other_requests>self.caps['new_request_attempts']:reasons.append('global_future_requests')
        wall=self.caps['wall_seconds']-(self.clock()-self.start)
        if wall<(1+future['requests']+other_requests)*e.timeout+e.cleanup:reasons.append('future_wall_slots')
        append(self.path.parent/'ENVELOPE_PREFLIGHT.jsonl',dict(task=self.task,kind=kind,known_tokens=self.actual_tokens,unknown_reserved_tokens=sum(self.pending.values()),request_max_reservation=reservation,future_task=future,other_tasks_tokens=other,phase_future_tokens=same['tokens'],wall_remaining_s=wall,allowed=not reasons,reasons=reasons))
        if reasons:raise StopRun('Envelope preflight: '+','.join(reasons))
        self.next_reservation=reservation;self.next_kind=kind;self._next_maxout=maxout
        return reservation
    def release_unused(self,phase):
        if self.envelope:
            for k,b in self.envelope.stages.items():
                if b.phase==phase:self.stage_counts[self.task][k]=b.calls
            append(self.path.parent/'ENVELOPE_RELEASE.jsonl',dict(task=self.task,phase=phase,reason='phase ended; no further dispatch permitted'))
    def select(self,task,phase):
        self.task=task;self.phase=phase;self.buckets.setdefault((task,phase),0);self.task_attempts.setdefault(task,0)
    def preflight(self,reservation,*,future_tokens=0,future_requests=0,min_wall_s=0):
        """Actual known usage plus retained unknown reservations; no predicted cache credits."""
        if any(type(v) is not int or v<0 for v in (reservation,future_tokens,future_requests)) or reservation<=0:raise ValueError('Invalid resource envelope')
        elapsed=self.clock()-self.start
        phase_spend=self.buckets.get((self.task,self.phase),0)
        execution_spend=self.buckets.get((self.task,'execution'),0)
        protected=max(0,6000-execution_spend) if self.phase=='generation' else 0
        evidence=dict(task=self.task,phase=self.phase,known_tokens=self.actual_tokens,unknown_reserved_tokens=sum(self.pending.values()),current_max_reservation=reservation,future_max_tokens=future_tokens,execution_protected_tokens=protected,phase_charged=phase_spend,task_requests_remaining=12-self.task_attempts.get(self.task,0),global_requests_remaining=self.caps['new_request_attempts']-self.attempts,global_tokens_remaining=self.caps['new_total_tokens']-self.charged,wall_remaining_s=self.caps['wall_seconds']-elapsed)
        reasons=[]
        if phase_spend+reservation+future_tokens>6000:reasons.append('phase_token_envelope')
        if self.charged+reservation+future_tokens+protected>self.caps['new_total_tokens']:reasons.append('execution_reserve_protected')
        if evidence['task_requests_remaining']<1+future_requests:reasons.append('task_request_envelope')
        if evidence['global_requests_remaining']<1+future_requests:reasons.append('global_request_envelope')
        if evidence['wall_remaining_s']<=min_wall_s:reasons.append('wall_envelope')
        evidence.update(allowed=not reasons,reasons=reasons)
        append(self.path.parent/'STAGE_PREFLIGHT.jsonl',evidence)
        if reasons:raise StopRun('Stage preflight: '+','.join(reasons))
        return evidence
    def reserve(self,key):
        if self.task is None or self.phase not in ('generation','execution') or type(self.next_reservation) is not int or self.next_reservation<=0:raise StopRun('Missing scoped reservation')
        bucket=(self.task,self.phase)
        if self.task_attempts[self.task]>=(self.envelope.task_requests if self.envelope else 12):raise StopRun('per-task request cap')
        if self.envelope:
            self.check_request(self.next_kind,self.next_reservation-self._next_maxout,self._next_maxout)
        if self.buckets[bucket]+self.next_reservation>(self.envelope.phase_tokens[self.phase] if self.envelope else 6000):raise StopRun('phase Token cap; execution reserve cannot fund generation')
        self.caps['request_token_reservation']=self.next_reservation
        idx=super().reserve(key)
        if self.envelope:self.stage_counts[self.task][self.next_kind]=self.stage_counts[self.task].get(self.next_kind,0)+1
        self.buckets[bucket]+=self.next_reservation;self.task_attempts[self.task]+=1;self.pending_bucket[idx]=bucket
        append(self.path.parent/'PHASE_BUDGET.jsonl',dict(event='reserved',id=idx,task=self.task,phase=self.phase,tokens=self.next_reservation))
        return idx
    def settle(self,idx,response):
        before=self.pending[idx];bucket=self.pending_bucket[idx]
        try:super().settle(idx,response)
        finally:
            # Known usage may settle before an infrastructure/wall StopRun.
            if idx not in self.pending:
                self.buckets[bucket]+=response['usage']['total_tokens']-before;self.pending_bucket.pop(idx)
                append(self.path.parent/'PHASE_BUDGET.jsonl',dict(event='settled',id=idx,task=bucket[0],phase=bucket[1],actual_tokens=response['usage']['total_tokens']))
    def summary(self):
        return dict(attempts=self.attempts,actual_tokens=self.actual_tokens,charged_tokens=self.charged,pending=dict(self.pending),task_attempts=dict(self.task_attempts),phase_charged={t+':'+p:n for (t,p),n in self.buckets.items()})

def response_format(body):
    """Shared real HTTP structured-output routing; zero-call testable."""
    if body.get('operation') in ('plan_typed_dag','repair_semantic_plan','plan_goal_ir','repair_goal_ir'):
        from .service_schema import to_service_schema
        service,_=to_service_schema(body['plan_json_schema'])
        return {'type':'json_schema','json_schema':dict(name='semantic_plan',strict=True,schema=service)}
    if body.get('operation')=='review_coverage':
        return {'type':'json_schema','json_schema':dict(name='coverage_review',strict=True,schema=body['review_json_schema'])}
    if body.get('contract')=='facts.v1':
        from .fact_semantics import source_selection_schema
        return {'type':'json_schema','json_schema':dict(name='source_selection',strict=True,schema=source_selection_schema(body['source_candidates']))}
    return {'type':'json_object'}


def main():
    invocation_started=time.monotonic()
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);ap.add_argument('--execute',action='store_true');ap.add_argument('--manifest',required=True);ap.add_argument('--evaluation',required=True);ap.add_argument('--budget-plan');ap.add_argument('--allocation-policy',choices=['heterogeneous_type_baseline','single_medium_baseline'],default='heterogeneous_type_baseline');ap.add_argument('--planning-mode',choices=['semantic','goal_ir'],default='semantic');args=ap.parse_args()
    if not args.execute:raise ValueError('Explicit --execute required')
    manifest_path=Path(args.manifest);manifest=json.loads(manifest_path.read_text());tasks=manifest['tasks']
    from .protocol import digest
    if not 1<=len(tasks)<=4 or len({t['task_id'] for t in tasks})!=len(tasks):raise ValueError('One to four unique frozen tasks required')
    for task in tasks:
        if set(task)!={'task_id','domain','context','required_outputs'} or digest(task)!=manifest['content_sha256'][task['task_id']]:raise ValueError('Public task hash/fields mismatch')
    if hashlib.sha256(Path(args.evaluation).read_bytes()).hexdigest()!=manifest['evaluation_only_sha256']:raise ValueError('Evaluation source hash mismatch')
    out=Path(args.output);out.mkdir(exist_ok=False,parents=True)
    package=Path(__file__).parent
    from .resource_envelope import ResourceEnvelope,StageBound
    plan=json.loads(Path(args.budget_plan).read_text()) if args.budget_plan else {}
    active_caps={**CAPS,**plan.get('caps',{})}
    envelope=ResourceEnvelope(stages={k:StageBound(**v) for k,v in plan['stages'].items()} if 'stages' in plan else None,phase_tokens=plan.get('phase_tokens'))
    code=[package/n for n in ('fresh_acceptance.py','generation.py','semantic_ids.py','semantic_validation.py','producer_plan.py','assembly.py','execution.py','fact_semantics.py','protocol.py','generation_schema.py','coverage_review.py','goal_ir.py','service_schema.py','resource_envelope.py','heterogeneous_models.py')]
    code += [Path(engine.__file__),Path(__file__).parents[1]/'joint_search_v1/scoring_contract_final.py']
    # Final evaluator labels are stored separately, never passed to planner/executor.
    shutil.copyfile(args.evaluation,out/'EVALUATION_ONLY.json')
    protocol=dict(tasks=tasks,manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),caps=active_caps,resource_envelope=envelope.to_dict(),task_phase_tokens=envelope.phase_tokens,max_repairs=1,max_execution_recoveries=1,max_nodes=5,models=engine.MODELS,allocation_policy=args.allocation_policy,planning_mode=args.planning_mode,no_http_retries=True,no_resume=True,no_historical_budget=True,code_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in code},evaluation_only_sha=hashlib.sha256((out/'EVALUATION_ONLY.json').read_bytes()).hexdigest(),approval='Explicit --execute for externally approved frozen task manifest; no implicit budget authorization',created_unix=time.time())
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2))
    lockpath=engine.ROOT/'collect/logs/local_gpu.lock';lockpath.parent.mkdir(exist_ok=True,parents=True)
    with lockpath.open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        budget=ScopedBudget(out,active_caps);budget.start=invocation_started;started=budget.start;rows=[];proc=log=None;abort=None;load_s=None;service=None;stage_a_load_s=0;sample_stop=threading.Event();sampler=None
        def snapshot():
            (out/'RESULTS.json').write_text(json.dumps(dict(tasks=rows,budget=budget.summary(),wall_s=time.monotonic()-started,model_load_s=stage_a_load_s+(service.startup_s if service is not None else 0),abort=abort,service_stopped=service is not None and service.active is None),ensure_ascii=False,indent=2))
        def deadline():
            budget.check()
            if time.monotonic()-started>=active_caps['wall_seconds']-envelope.cleanup:raise StopRun('cleanup wall-clock reserve')
        try:
            from .heterogeneous_models import heterogeneous_wall_preflight,audit_pool,SerialModelService,allocate,prepare_metered_request
            budget.bind_envelope(envelope,[t['task_id'] for t in tasks])
            if args.allocation_policy=='heterogeneous_type_baseline':
                try:wall_evidence=heterogeneous_wall_preflight(envelope,len(tasks),active_caps['wall_seconds'])
                except StopRun as exc:
                    append(out/'HETEROGENEOUS_WALL_PREFLIGHT.jsonl',dict(allowed=False,reason=str(exc)));raise
                append(out/'HETEROGENEOUS_WALL_PREFLIGHT.jsonl',wall_evidence)
            old_handler=signal.getsignal(signal.SIGALRM)
            def hard_deadline(signum,frame):raise StopRun('Hard wall deadline; cleanup reserved')
            signal.signal(signal.SIGALRM,hard_deadline);signal.setitimer(signal.ITIMER_REAL,max(.001,active_caps['wall_seconds']-envelope.cleanup-(time.monotonic()-started)))
            deadline()
            busy=subprocess.run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],capture_output=True,text=True)
            if busy.returncode or busy.stdout.strip():raise RuntimeError('GPU busy')
            with socket.socket() as s:
                if s.connect_ex(('127.0.0.1',8128))==0:raise RuntimeError('Port occupied')
            from transformers import AutoTokenizer
            pool=audit_pool(engine.MODELS,engine.ROOT/'router_v2/label_repair_experiment/raw',verify_weights=True)
            (out/'MODEL_POOL.json').write_text(json.dumps(pool,ensure_ascii=False,indent=2))
            tokenizers={slot:AutoTokenizer.from_pretrained(cfg['path'],local_files_only=True) for slot,cfg in engine.MODELS.items()}
            # Stage A health/model GETs produce no inference requests. All costs share this wall clock.
            service=SerialModelService(engine.MODELS,pool,out,deadline,max_activations=3)
            def sample_gpu():
                while not sample_stop.is_set():
                    q=subprocess.run(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5)
                    append(out/'GPU_MEMORY_SAMPLES.jsonl',dict(monotonic=time.monotonic(),model=service.active if service is not None else None,memory_mib=q.stdout.strip(),query_status=q.returncode))
                    sample_stop.wait(.5)
            sampler=threading.Thread(target=sample_gpu,daemon=True);sampler.start()
            a_rows=[]
            for slot in ('medium','large','coder'):
                ts=time.monotonic();service.activate(slot)
                a_rows.append(dict(model=slot,status='PASS',served=engine.MODELS[slot]['served'],weights_identity_sha256=pool[slot]['weights_identity_sha256'],tokenizer_sha256=pool[slot]['tokenizer_sha256'],load_and_switch_s=time.monotonic()-ts,health='GET /health and /v1/models; no inference request',tokenizer_class=type(tokenizers[slot]).__name__))
                (out/'STAGE_A_RESULTS.json').write_text(json.dumps(a_rows,ensure_ascii=False,indent=2))
            service.close();stage_a_load_s=service.startup_s
            remaining_wall=active_caps['wall_seconds']-(time.monotonic()-started)
            b_admission=heterogeneous_wall_preflight(envelope,len(tasks),remaining_wall)
            append(out/'STAGE_B_ADMISSION.jsonl',dict(**b_admission,stage_a_passed=True,actual_requests=budget.attempts,actual_tokens=budget.actual_tokens))
            service=SerialModelService(engine.MODELS,pool,out,deadline,budget=budget,max_activations=7*len(tasks) if args.allocation_policy=='heterogeneous_type_baseline' else 1)
            opener=service.opener
            prepared={}
            def prepare_request(prompt,key,model):
                deadline();prepared.clear();prepared.update(prepare_metered_request(model,prompt,key,budget,tokenizers,pool))
            def dispatch(model,prompt):
                deadline()
                if prepared['slot']!=model or service.active!=model:raise RuntimeError('Prepared/selected/active model mismatch')
                cfg=engine.MODELS[model];body=prepared['body'];fmt=response_format(body)
                if body.get('operation') in ('plan_typed_dag','repair_semantic_plan','plan_goal_ir','repair_goal_ir'):
                    from .service_schema import to_service_schema
                    _,audit=to_service_schema(body['plan_json_schema']);append(out/'SCHEMA_TRANSPORT.jsonl',dict(task=budget.task,operation=body['operation'],**audit))
                payload=dict(model=cfg['served'],messages=[dict(role='user',content=prompt)],temperature=0,top_p=1,max_tokens=prepared['maxout'],stream=False,response_format=fmt)
                append(out/'HTTP_INPUTS.jsonl',dict(task=budget.task,phase=budget.phase,payload=payload))
                req=request.Request('http://127.0.0.1:8128/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                try:
                    from .resource_envelope import request_deadline
                    with request_deadline(envelope.timeout):
                        with opener.open(req,timeout=min(envelope.timeout,active_caps['wall_seconds']-envelope.cleanup-(time.monotonic()-started))) as r:data=json.loads(r.read())
                except error.HTTPError as e:
                    body_error=e.read().decode(errors='replace')
                    from .service_schema import classify_http
                    append(out/'HTTP_ERRORS.jsonl',dict(status=e.code,body=body_error,error_code=classify_http(e.code,body_error),usage='UNKNOWN; retain request reservation'))
                    raise RuntimeError('HTTP '+str(e.code)+': '+body_error) from e
                append(out/'HTTP_OUTPUTS.jsonl',dict(task=budget.task,phase=budget.phase,data=data))
                service.check_provider(model,data.get('model'))
                append(out/'MODEL_DISPATCH_IDENTITY.jsonl',dict(task=budget.task,phase=budget.phase,selected_model=model,provider_model=data.get('model'),weights_identity_sha256=pool[model]['weights_identity_sha256'],provider_id=data.get('id')))
                choice=data['choices'][0]
                return dict(status='delivered',answer=choice['message']['content'],usage=data['usage'],finish_reason=choice.get('finish_reason'),provider_id=data.get('id'),provider_model=data.get('model'))
            class PreparedExecutor(MeteredExecutor):
                def call(self,key,model,prompt,uid=None,node=None):
                    prepare_request(prompt,key,model)
                    return super().call(key,model,prompt,uid,node)
            ex=PreparedExecutor(out,budget,dispatch,service.activate,{slot:cfg['served'] for slot,cfg in engine.MODELS.items()})
            limits=Limits(max_nodes=5,max_depth=5,max_llm_calls=5)
            gen=InitialDAGGenerator(ex,'medium',max_repairs=1,limits=limits,planning_mode=args.planning_mode,strict_planning_schema=True)
            for task in tasks:
                deadline();task_start=time.monotonic();row=dict(task_id=task['task_id'],status='STARTED',stages=[],executions=[],recoveries=[]);rows.append(row);snapshot()
                def measure(label,fn):
                    a0=budget.attempts;t0=budget.actual_tokens;ts=time.monotonic()
                    try:return fn()
                    finally:row['stages'].append(dict(stage=label,requests=budget.attempts-a0,known_tokens=budget.actual_tokens-t0,wall_s=time.monotonic()-ts));snapshot()
                budget.select(task['task_id'],'generation')
                a=measure('generation_and_repair',lambda:gen.generate(**task))
                row.update(first_structural_legal=any(e.get('phase')=='structural_validation' and e.get('status')=='PASS' and e.get('attempt')==0 for e in a.events),repair_structural_legal=any(e.get('phase')=='structural_validation' and e.get('status')=='PASS' and e.get('attempt')==1 for e in a.events),semantic_review_attempted=any(e.get('phase')=='semantic_review' for e in a.events),semantic_review_pass=a.semantic_status=='MODEL_REVIEW_PASS_NOT_PROOF',generation_status=a.status,first_legal=a.status=='GENERATED',repaired_legal=a.status=='REPAIRED',fallback=a.status=='FALLBACK',generation_events=a.events,graph=a.graph.to_dict() if a.graph else None)
                if a.graph is None or a.status not in ('GENERATED','REPAIRED'):
                    budget.release_unused('generation');budget.release_unused('execution')
                    row.update(status='GENERATION_FAILED',task_wall_s=time.monotonic()-task_start);snapshot();continue
                validate(a.graph,task['required_outputs'],limits)
                (out/(task['task_id']+'_GRAPH.json')).write_text(a.graph.to_json())
                budget.release_unused('generation')
                budget.select(task['task_id'],'execution');allocation=allocate(a.graph,ex.bindings,args.allocation_policy);assignment=allocation['assignment'];row['model_assignment']=assignment;row['allocation']=allocation
                (out/(task['task_id']+'_ASSIGNMENT.json')).write_text(json.dumps(allocation,ensure_ascii=False,indent=2))
                runner=TypedExecutor(a.graph,assignment,ex,task['context'],required_outputs=task['required_outputs'],limits=limits,extraction_mode='source_selection')
                b=measure('execution',runner.run);row['executions'].append(b)
                if b['status']!='COMPLETE':
                    failed=[u for layer in runner.validation.layers for u in layer if runner.status[u]=='failed']
                    if failed:
                        try:
                            budget.recovery_mode=True;budget.recovery_target=failed[0]
                            b=measure('recovery',lambda:runner.recover_failed(failed[0],assignment[failed[0]],max_attempts=2));row['executions'].append(b);row['recoveries'].append(dict(node_id=failed[0],model=assignment[failed[0]],status=b['status']))
                        except ValueError as e:row['recoveries'].append(dict(node_id=failed[0],status='REQUIRES_REVIEW',reason=str(e)))
                def score_final():
                    from collab_scheduler_v1.joint_search_v1.scoring_contract_final import score_v21
                    gold=json.loads((out/'EVALUATION_ONLY.json').read_text())[task['task_id']]
                    row.update(final_answer=b['final_outputs'].get('answer'),execution_complete=b['status']=='COMPLETE',all_nodes_done=all(s=='done' for s in b['node_status'].values()),task_quality_success=bool(b['status']=='COMPLETE' and score_v21(b['final_outputs'].get('answer'),gold)),evaluation_only_gold=gold)
                measure('scoring',score_final)
                budget.release_unused('execution');budget.recovery_mode=False
                row.update(status='FINISHED',task_wall_s=time.monotonic()-task_start);snapshot();print(json.dumps(dict(task_id=task['task_id'],generated=a.status,execution=b['status'],correct=row['task_quality_success'],budget=budget.summary())),flush=True)
        except BaseException as exc:
            abort=repr(exc)
            if rows:rows[-1]['abort']=abort
            append(out/'STOP.jsonl',dict(reason=abort,budget=budget.summary(),wall_s=time.monotonic()-started))
            print('STOP '+abort,flush=True)
        finally:
            if 'old_handler' in locals():signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old_handler)
            if service is not None:service.close()
            sample_stop.set()
            if sampler is not None:sampler.join(timeout=6)
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=15)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
            if log is not None:log.close()
            snapshot()
    return 0 if abort is None else 2
if __name__=='__main__':raise SystemExit(main())
