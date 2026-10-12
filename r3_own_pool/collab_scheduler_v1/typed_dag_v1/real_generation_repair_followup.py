"""Separate two-task smoke; never reads research task panels or gold labels."""
import argparse,json,time,fcntl,hashlib
from pathlib import Path
from urllib import request,error
from .generation import InitialDAGGenerator
from .protocol import Limits
from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget
from static_dag_v0 import run as engine

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);ap.add_argument('--tasks',type=int,choices=[1,2],default=2);args=ap.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    caps=dict(new_request_attempts=6,new_total_tokens=24576,request_token_reservation=4096,max_output_tokens=2048,wall_seconds=300,logical_calls_per_task_config_state=20)
    tasks=[dict(task_id='typed-stage3-repair-sum',domain='financial_arithmetic',context=dict(question='What is the total revenue of the two divisions? Return one number.',ctx_table='Division A revenue: 13. Division B revenue: 9.',ctx_text='Both divisions report revenue in the same unit.'),required_outputs={'answer':'Total revenue as a number'}),dict(task_id='typed-stage3-repair-change',domain='financial_arithmetic',context=dict(question='What is the increase in cash from last year to this year? Return the difference, not a percentage.',ctx_table='Last year cash: 6. This year cash: 17.',ctx_text='Cash figures use the same unit.'),required_outputs={'answer':'This year cash minus last year cash, numeric difference'})]
    tasks=tasks[1:2]
    package=Path(__file__).parent
    protocol=dict(caps=caps,tasks=tasks,model=engine.MODELS['medium'],temperature=0,top_p=1,max_tokens=2048,code_sha={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [package/'generation.py',package/'execution.py',package/'protocol.py',package/'generation_schema.py',package/'assembly.py',Path(__file__)]},purpose='Mechanics smoke, not algorithm efficacy',created=time.time())
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
    lock_path=engine.ROOT/'collect/logs/local_gpu.lock';lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old=engine.OUT;engine.OUT=out;proc=log=None;started=time.monotonic();rows=[]
        try:
            budget=Budget(out,caps)
            proc,log,load_s=engine.start_model('medium')
            def dispatch(model,prompt):
                payload=dict(model=engine.MODELS[model]['served'],messages=[dict(role='user',content=prompt)],temperature=0,top_p=1,max_tokens=2048,stream=False,response_format={"type":"json_object"})
                req=request.Request('http://127.0.0.1:8128/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                try:
                    with request.build_opener(request.ProxyHandler({})).open(req,timeout=180) as response:data=json.loads(response.read())
                except error.HTTPError as exc:
                    raise RuntimeError('Backend HTTP '+str(exc.code)+': '+exc.read().decode(errors='replace')) from exc
                return dict(status='delivered',answer=data['choices'][0]['message']['content'],usage=data['usage'],finish_reason=data['choices'][0]['finish_reason'],provider_id=data.get('id'),provider_model=data.get('model'))
            ex=MeteredExecutor(out,budget,dispatch,lambda m:None,{'medium':engine.MODELS['medium']['served']})
            gen=InitialDAGGenerator(ex,'medium',max_repairs=1,limits=Limits(max_nodes=6,max_depth=5,max_llm_calls=5))
            for task in tasks:
                a,b=gen.generate_and_execute(**task,allocate=lambda g:{n.node_id:'medium' for n in g.nodes})
                from collab_scheduler_v1.joint_search_v1.scoring_contract_final import score_v21
                expected={'typed-stage3-repair-sum':22.0,'typed-stage3-repair-change':11.0}[task['task_id']]
                quality=bool(b and score_v21(b['final_outputs'].get('answer'),expected))
                rows.append(dict(task_quality_success=quality,quality_expected=expected,execution_success=bool(b and b['status']=='COMPLETE'),task_id=task['task_id'],generation_status=a.status,semantic_status=a.semantic_status,generation_accounting=a.accounting,graph=a.graph.to_dict() if a.graph else None,execution=b))
                (out/'RESULTS.json').write_text(json.dumps(dict(tasks=rows,requests=budget.attempts,tokens=budget.actual_tokens,model_load_s=load_s,wall_s=time.monotonic()-started),indent=2))
        except BaseException as exc:
            (out/'ABORT.json').write_text(json.dumps(dict(error=repr(exc),attempts=budget.attempts if 'budget' in locals() else None,known_tokens=budget.actual_tokens if 'budget' in locals() else None,pending=budget.pending if 'budget' in locals() else None,completed_tasks=rows),indent=2))
            raise
        finally:
            if proc is not None:engine.stop_model(proc,log)
            engine.OUT=old
if __name__=='__main__':main()
