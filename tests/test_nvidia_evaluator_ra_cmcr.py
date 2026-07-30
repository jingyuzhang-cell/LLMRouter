import json
from pathlib import Path
import pandas as pd
import pytest
from llmrouter.evaluation.one_time import evaluate_matrix_once,EvaluationLockedError
from llmrouter.ra_cmcr.core import RouteDecision,Telemetry
from llmrouter.ra_cmcr.simulator import simulate,compare_policies

def matrix(n=40):
 models=["cheap","medium","strong"];queries=[];rows=[];pred={}
 for i in range(n):
  q=f"q{i}";task="task_a" if i<n//2 else "task_b";queries.append({"query":q,"task_name":task})
  vals={"cheap":1.0 if i%4==0 else 0.0,"medium":.5,"strong":1.0 if i%5 else 0.0}
  pred[q]="cheap" if i%2==0 else "strong"
  for m in models:
   for rep in (1,2):rows.append({"query":q,"task_name":task,"model_name":m,"repeat_index":rep,"performance":vals[m],"prompt_tokens":100,"completion_tokens":10,"success":True})
 return pd.DataFrame(rows),pd.DataFrame(queries),pred,{"cheap":{"size_b":3,"input_price":.2,"output_price":.2},"medium":{"size_b":8,"input_price":.5,"output_price":.5},"strong":{"size_b":119,"input_price":.9,"output_price":.9}}

def test_one_time_evaluator_and_known_baselines(tmp_path):
 r,q,p,info=matrix();report=evaluate_matrix_once(r,q,p,info,tmp_path,repeats=500,random_simulations=100)
 assert report["overall"]["always_strong"]["performance"]==pytest.approx(.8)
 assert report["overall"]["oracle"]["performance"]>=report["overall"]["router"]["performance"]
 assert report["overall"]["always_cheap"]["actual_token_cost"]<report["overall"]["always_strong"]["actual_token_cost"]
 assert report["overall"]["router"]["harm_count"]==8
 assert report["overall"]["router"]["rescue_count"]==2
 assert report["paired_router_vs_strong"]["performance_delta_ci95"][0]<=report["paired_router_vs_strong"]["performance_delta"]<=report["paired_router_vs_strong"]["performance_delta_ci95"][1]
 assert set(report["per_task"])=={"task_a","task_b"}
 weighted=sum(v["router"]["performance"]*20 for v in report["per_task"].values())/40
 assert weighted==pytest.approx(report["overall"]["router"]["performance"])
 assert report["overall"]["random_1000_mean"]["performance"]<=report["overall"]["oracle"]["performance"]
 assert (tmp_path/"EVALUATED_ONCE").exists()
 with pytest.raises(EvaluationLockedError):evaluate_matrix_once(r,q,p,info,tmp_path)

def test_degenerate_router_alarm(tmp_path):
 r,q,_,info=matrix();p={x:"strong" for x in q["query"]};report=evaluate_matrix_once(r,q,p,info,tmp_path,repeats=100,random_simulations=10)
 assert report["degenerate_task_alarm"];assert report["nondegenerate_task_count"]==0

@pytest.mark.parametrize("failure",["timeout","rate_limit","model_unavailable","temporary_unavailable"])
def test_recoverable_faults_fallback(failure):
 x=simulate(["primary","strong","medium"],{"primary":failure,"strong":"success"},{"primary":1,"strong":2,"medium":1},{"primary":10,"strong":20,"medium":10})
 assert x.success and x.final_model=="strong" and x.attempts==["primary","strong"]

def test_auth_or_invalid_does_not_fallback():
 x=simulate(["primary","strong"],{"primary":"authentication"},{"primary":1,"strong":2},{"primary":10,"strong":20})
 assert not x.success and x.attempts==["primary"]

def test_strong_failure_medium_success_and_all_fail():
 costs={"primary":1,"strong":2,"medium":1};lat={m:10 for m in costs}
 x=simulate(list(costs),{"primary":"timeout","strong":"model_unavailable","medium":"success"},costs,lat)
 assert x.success and x.final_model=="medium"
 y=simulate(list(costs),{m:"timeout" for m in costs},costs,lat)
 assert not y.success and len(y.attempts)==3

def test_cost_latency_budget_and_dedup():
 costs={"p":1,"s":2};lat={"p":20,"s":30}
 assert simulate(["p","s"],{"p":"timeout","s":"success"},costs,lat,total_cost_budget=2).budget_exhausted
 assert simulate(["p","s"],{"p":"timeout","s":"success"},costs,lat,total_latency_budget_ms=40).budget_exhausted
 x=simulate(["p","p","s"],{"p":"timeout","s":"success"},costs,lat)
 assert x.attempts==["p","s"] and not x.duplicate_call

def test_no_fallback_fixed_and_ra_comparison():
 x=compare_policies(["p","s"],{"p":"timeout","s":"success"},{"p":1,"s":2},{"p":10,"s":20})
 assert not x["none"]["success"] and x["fixed"]["success"] and x["ra_cmcr"]["success"]

def test_telemetry_separates_quality_and_service_fallback():
 t=Telemetry();e=t.start(RouteDecision("cheap",.02,.1,quality_escalation_model="strong"))
 e.quality_escalated=True;e.service_fallback=False;e.final_model="strong";e.success=True;t.emit(e)
 assert t.records[0]["quality_escalated"] and not t.records[0]["service_fallback"]
