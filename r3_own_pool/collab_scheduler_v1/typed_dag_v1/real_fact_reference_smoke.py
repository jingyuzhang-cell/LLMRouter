"""Bounded real diagnostic on public synthetic tasks; no research panels."""
import argparse,fcntl,hashlib,json,time
from pathlib import Path
from urllib import request,error
from .generation import InitialDAGGenerator
from .execution import TypedExecutor
from .protocol import Limits,ValidationError
from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget,StopRun
from static_dag_v0 import run as engine

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);ap.add_argument('--parent');ap.add_argument('--resume-generated');args=ap.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    caps=dict(new_request_attempts=16,new_total_tokens=49152,request_token_reservation=8192,max_output_tokens=2048,wall_seconds=600,logical_calls_per_task_config_state=30)
    parent=None
    if args.parent:
        parent_path=Path(args.parent);parent=json.loads((parent_path/'RESULTS.json').read_text());pp=json.loads((parent_path/'PROTOCOL.json').read_text())
        caps=dict(pp['caps']);caps['new_request_attempts']-=parent['attempts'];caps['new_total_tokens']-=parent['charged_tokens'];caps['wall_seconds']-=parent['wall_s']
        if caps['new_request_attempts']<=0 or caps['new_total_tokens']<caps['request_token_reservation'] or caps['wall_seconds']<=0:raise StopRun('Parent envelope exhausted')
    tasks=[dict(task_id='typed-stage3-facts-change',domain='financial_arithmetic',context=dict(question='What is the increase in cash from last year to this year? Return the difference, not a percentage.',ctx_table='Last year cash: 6. This year cash: 17.',ctx_text='Cash figures use the same unit.'),required_outputs={'answer':'This year cash minus last year cash, numeric difference'}),dict(task_id='typed-stage3-facts-sum',domain='financial_arithmetic',context=dict(question='What is the total revenue of the two divisions? Return one number.',ctx_table='Division A revenue: 13. Division B revenue: 9.',ctx_text='Both divisions report revenue in the same unit.'),required_outputs={'answer':'Total revenue as a number'})]
    if args.resume_generated:
        saved_resume=json.loads(Path(args.resume_generated).read_text());eligible_ids={r['task_id'] for r in saved_resume['tasks'] if r['generation_status'] in ('GENERATED','REPAIRED')}
        tasks=[t for t in tasks if t['task_id'] in eligible_ids]
        if not tasks:raise ValueError('No matching non-fallback graph for continuation')
    package=Path(__file__).parent;names=['generation.py','execution.py','fact_semantics.py','protocol.py','generation_schema.py','assembly.py','semantic_ids.py',Path(__file__).name]
    protocol=dict(caps=caps,tasks=tasks,model=engine.MODELS['medium'],temperature=0,top_p=1,max_tokens=2048,max_plan_repairs=2,max_execution_attempts_per_node=2,code_sha={n:hashlib.sha256((package/n).read_bytes()).hexdigest() for n in names},resume_generated=args.resume_generated,compact_grammar=True,extraction_protocol="source-selection.v1",parent_budget=dict(path=args.parent,attempts=parent['attempts'],charged_tokens=parent['charged_tokens'],wall_s=parent['wall_s']) if parent else None,purpose='Development mechanics diagnostic, stop on first non-fallback COMPLETE and correct final score; not an efficacy experiment',no_historical_budget_reuse=True,created=time.time())
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
    lock_path=engine.ROOT/'collect/logs/local_gpu.lock';lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old=engine.OUT;engine.OUT=out;proc=log=None;started=time.monotonic();rows=[];budget=Budget(out,caps);load_s=0;success=False;abort=None
        def snapshot():
            result=dict(tasks=rows,success=success,attempts=budget.attempts,tokens=budget.actual_tokens,pending=budget.pending,charged_tokens=budget.charged,model_load_s=load_s,wall_s=time.monotonic()-started,abort=abort,real_diagnostic=True)
            (out/'RESULTS.json').write_text(json.dumps(result,indent=2))
        try:
            original_popen=engine.subprocess.Popen
            def compact_popen(command,*args,**kwargs):
                if args_resume and isinstance(command,list) and 'serve' in command and any('vllm' in str(x) for x in command):command=command+['--structured-outputs-config','{"backend":"xgrammar","disable_any_whitespace":true}']
                return original_popen(command,*args,**kwargs)
            args_resume=True
            engine.subprocess.Popen=compact_popen
            try:proc,log,load_s=engine.start_model('medium')
            finally:engine.subprocess.Popen=original_popen
            from transformers import AutoTokenizer
            tokenizer=AutoTokenizer.from_pretrained(engine.MODELS['medium']['path'],local_files_only=True)
            def dispatch(model,prompt):
                budget.check()
                ids=tokenizer.apply_chat_template([dict(role='user',content=prompt)],tokenize=True,add_generation_prompt=True)
                if len(ids)+2048>8192:raise StopRun('Request context/reservation exceeds 8192; reservation retained')
                payload=dict(model=engine.MODELS[model]['served'],messages=[dict(role='user',content=prompt)],temperature=0,top_p=1,max_tokens=2048,stream=False,response_format={'type':'json_object'})
                if prompt.startswith('{'):
                    planner_input=json.loads(prompt)
                    if planner_input.get('operation') in ('plan_typed_dag','repair_semantic_plan'):
                        payload['response_format']={'type':'json_schema','json_schema':{'name':'semantic_plan','strict':True,'schema':planner_input['plan_json_schema']}}
                if prompt.startswith('Execute the subtask.'):
                    contract_input=json.loads(prompt.split('\n',1)[1])
                    if contract_input['contract']=='facts.v1':
                        from .fact_semantics import source_selection_schema
                        payload['response_format']={'type':'json_schema','json_schema':{'name':'source_selection','strict':True,'schema':source_selection_schema(contract_input['source_candidates'])}}
                req=request.Request('http://127.0.0.1:8128/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                remaining=caps['wall_seconds']-(time.monotonic()-started)
                if remaining<=0:raise StopRun('wall budget before HTTP')
                try:
                    with request.build_opener(request.ProxyHandler({})).open(req,timeout=min(180,remaining)) as response:data=json.loads(response.read())
                except error.HTTPError as exc:raise RuntimeError('Backend HTTP '+str(exc.code)+': '+exc.read().decode(errors='replace')) from exc
                return dict(status='delivered',answer=data['choices'][0]['message']['content'],usage=data['usage'],finish_reason=data['choices'][0]['finish_reason'],provider_id=data.get('id'),provider_model=data.get('model'))
            ex=MeteredExecutor(out,budget,dispatch,lambda m:None,{'medium':engine.MODELS['medium']['served']})
            gen=InitialDAGGenerator(ex,'medium',max_repairs=2,limits=Limits(max_nodes=6,max_depth=6,max_llm_calls=6))
            for task in tasks:
                print('GENERATE '+task['task_id'],flush=True)
                if args.resume_generated:
                    from types import SimpleNamespace
                    from .protocol import Graph,validate
                    source=Path(args.resume_generated);saved=json.loads(source.read_text());oldrow=next(r for r in saved['tasks'] if r['task_id']==task['task_id'] and r['generation_status'] in ('GENERATED','REPAIRED'))
                    graph=Graph.from_json(json.dumps(oldrow['graph']));validate(graph,task['required_outputs'],gen.limits)
                    a=SimpleNamespace(graph=graph,status='REUSED_GENERATED',semantic_status=oldrow['semantic_status'],accounting=dict(new_requests=0,new_tokens=0,source=str(source),source_sha=hashlib.sha256(source.read_bytes()).hexdigest(),new_generation=False))
                else:a=gen.generate(**task)
                row=dict(task_id=task['task_id'],generation_status=a.status,semantic_status=a.semantic_status,generation_accounting=a.accounting,graph=a.graph.to_dict() if a.graph else None,executions=[],recoveries=[])
                rows.append(row);snapshot()
                if a.graph is None or a.status not in ('GENERATED','REPAIRED','REUSED_GENERATED'):
                    row['execution_skipped']='not a non-fallback generated graph';snapshot();continue
                runner=TypedExecutor(a.graph,{n.node_id:'medium' for n in a.graph.nodes},ex,task['context'],required_outputs=task['required_outputs'],limits=gen.limits,extraction_mode="source_selection")
                b=runner.run();row['executions'].append(b);snapshot()
                for _ in range(6):
                    if b['status']=='COMPLETE':break
                    failed=[u for u in runner.validation.order if runner.status[u]=='failed'] if hasattr(runner.validation,'order') else [u for layer in runner.validation.layers for u in layer if runner.status[u]=='failed']
                    eligible=[u for u in failed if runner.attempts[u]<2]
                    if not eligible:break
                    u=eligible[0];ts=time.monotonic();a0=budget.attempts;t0=budget.actual_tokens
                    try:b=runner.recover_failed(u,'medium',max_attempts=2)
                    except ValidationError as exc:
                        row['recoveries'].append(dict(node_id=u,status='REQUIRES_REVIEW',reason=str(exc)));break
                    row['recoveries'].append(dict(node_id=u,status=b['status'],new_requests=budget.attempts-a0,new_tokens=budget.actual_tokens-t0,wall_s=time.monotonic()-ts));row['executions'].append(b);snapshot()
                from collab_scheduler_v1.joint_search_v1.scoring_contract_final import score_v21
                expected={'typed-stage3-facts-change':11.0,'typed-stage3-facts-sum':22.0}[task['task_id']]
                row['execution_success']=b['status']=='COMPLETE';row['task_quality_success']=bool(row['execution_success'] and score_v21(b['final_outputs'].get('answer'),expected));row['evaluation_only_expected']=expected
                success=row['task_quality_success'];snapshot()
                print(json.dumps(dict(task_id=task['task_id'],generated=a.status,execution=b['status'],quality=row['task_quality_success'],requests=budget.attempts,tokens=budget.actual_tokens)),flush=True)
                if success:break
        except BaseException as exc:
            abort=repr(exc);snapshot();print('ABORT '+abort,flush=True)
        finally:
            if proc is not None:engine.stop_model(proc,log)
            engine.OUT=old;snapshot()
        return 0 if success else 2
if __name__=='__main__':raise SystemExit(main())
