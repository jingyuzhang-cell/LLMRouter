"""Two-request continuation of an unchanged LLM-generated graph; exact cache provenance."""
import json,time,fcntl,hashlib,argparse
from pathlib import Path
from urllib import request
from .protocol import Graph,validate
from .execution import TypedExecutor
from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget
from collab_scheduler_v1.joint_search_v1.scoring_contract_final import score_v21
from static_dag_v0 import run as engine

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);a=ap.parse_args();base=Path(__file__).parent
    sources=[base/'stage3_repair_real_01',base/'stage3_repair_real_02']
    previous=sum(sum(json.loads(l)['event']=='reserved' for l in (p/'DISPATCH.jsonl').read_text().splitlines()) for p in sources)
    if previous!=16:raise RuntimeError('Expected reconciled 16 attempts; refuse changed budget')
    source=sources[-1];meta=json.loads((source/'RESULTS.json').read_text());row=meta['tasks'][0]
    if row['generation_status'] not in ('GENERATED','REPAIRED'):raise RuntimeError('No generated graph')
    graph=Graph.from_json(json.dumps(row['graph']));validate(graph)
    task=json.loads((source/'PROTOCOL.json').read_text())['tasks'][0]
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    caps=dict(new_request_attempts=2,new_total_tokens=8192,request_token_reservation=4096,max_output_tokens=2048,wall_seconds=300,logical_calls_per_task_config_state=10)
    (out/'PROTOCOL.json').write_text(json.dumps(dict(caps=caps,global_attempt_cap=18,previous_attempts=previous,source=str(source),graph=graph.to_dict(),task=task,source_sha={f:hashlib.sha256((source/f).read_bytes()).hexdigest() for f in ['RESULTS.json','TRAJECTORY.jsonl','PROTOCOL.json']},code_sha={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),base/'execution.py',base/'protocol.py',base/'generation_schema.py']},purpose='No regeneration or topology edit; bounded execution continuation'),indent=2))
    lock_path=engine.ROOT/'collect/logs/local_gpu.lock'
    with lock_path.open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);old=engine.OUT;engine.OUT=out;proc=log=None;start=time.monotonic();budget=Budget(out,caps)
        try:
            proc,log,load=engine.start_model('medium')
            def dispatch(model,prompt):
                payload=dict(model=engine.MODELS[model]['served'],messages=[dict(role='user',content=prompt)],temperature=0,top_p=1,max_tokens=2048,response_format={'type':'json_object'})
                req=request.Request('http://127.0.0.1:8128/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                with request.build_opener(request.ProxyHandler({})).open(req,timeout=180) as r:data=json.loads(r.read())
                return dict(status='delivered',answer=data['choices'][0]['message']['content'],usage=data['usage'],finish_reason=data['choices'][0]['finish_reason'],provider_id=data.get('id'))
            ex=MeteredExecutor(out,budget,dispatch,lambda m:None,{'medium':engine.MODELS['medium']['served']})
            # Import only exact completed, noninjected cache identities from this task.
            imported=[]
            for line in (source/'TRAJECTORY.jsonl').read_text().splitlines():
                entry=json.loads(line);identity=entry['cache_identity'];response=entry['response']
                if not entry['key'].startswith('typed:dag:') or entry.get('injected_fault') or response.get('injected_fault') or entry.get('alias_of'):continue
                if identity[0]!=ex.bindings['medium'] or identity[4]!='typed-v1' or identity[2]!=hashlib.sha256(task['task_id'].encode()).hexdigest():raise RuntimeError('Cache identity mismatch')
                ex.cache[tuple(identity)]=dict(event_id=entry['event_id'],response=response);imported.append(dict(identity=identity,source_event=entry['event_id']))
            (out/'CACHE_IMPORT.json').write_text(json.dumps(imported,indent=2))
            runner=TypedExecutor(graph,{n.node_id:'medium' for n in graph.nodes},ex,task['context']);result=runner.run()
            summary=dict(execution=result,generation_source=str(source),generation_status=row['generation_status'],unchanged_graph_hash=graph.content_hash,execution_success=result['status']=='COMPLETE',task_quality_success=bool(score_v21(result['final_outputs'].get('answer'),11.0)),quality_expected=11.0,new_requests=budget.attempts,new_tokens=budget.actual_tokens,global_attempts=previous+budget.attempts,model_load_s=load,wall_s=time.monotonic()-start)
            (out/'RESULTS.json').write_text(json.dumps(summary,indent=2))
        except BaseException as exc:
            (out/'ABORT.json').write_text(json.dumps(dict(error=repr(exc),attempts=budget.attempts,tokens=budget.actual_tokens,pending=budget.pending),indent=2));raise
        finally:
            if proc is not None:engine.stop_model(proc,log)
            engine.OUT=old
if __name__=='__main__':main()
