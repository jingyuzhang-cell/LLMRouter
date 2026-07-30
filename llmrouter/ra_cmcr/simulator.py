"""Deterministic fault/cost simulation for fallback policies."""
from dataclasses import dataclass
from typing import Mapping
RECOVERABLE={"timeout","rate_limit","model_unavailable","temporary_unavailable"}
@dataclass
class SimulationResult:
    success:bool;final_model:str|None;attempts:list[str];total_cost:float;total_latency_ms:float;failure_category:str|None;duplicate_call:bool;budget_exhausted:bool
def simulate(chain:list[str], outcomes:Mapping[str,str], costs:Mapping[str,float], latencies:Mapping[str,float], total_cost_budget:float=1e9,total_latency_budget_ms:float=1e9, fallback_mode="fixed"):
    attempts=[];cost=latency=0.;failure=None
    candidates=chain[:1] if fallback_mode=="none" else list(dict.fromkeys(chain))
    for model in candidates:
        if model in attempts:return SimulationResult(False,None,attempts,cost,latency,"duplicate_call",True,False)
        next_cost=costs[model];next_latency=latencies[model]
        if cost+next_cost>total_cost_budget or latency+next_latency>total_latency_budget_ms:return SimulationResult(False,None,attempts,cost,latency,"budget_exhausted",False,True)
        attempts.append(model);cost+=next_cost;latency+=next_latency;outcome=outcomes.get(model,"success")
        if outcome=="success":return SimulationResult(True,model,attempts,cost,latency,None,False,False)
        failure=outcome
        if outcome not in RECOVERABLE:break
    return SimulationResult(False,None,attempts,cost,latency,failure,False,False)
def compare_policies(chain,outcomes,costs,latencies,**budgets):
    return {mode:simulate(chain,outcomes,costs,latencies,fallback_mode=mode,**budgets).__dict__ for mode in ("none","fixed","ra_cmcr")}
