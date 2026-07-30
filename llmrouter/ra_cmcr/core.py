"""Formal RA-CMCR interfaces. Framework only; no effectiveness claim."""
from __future__ import annotations
from dataclasses import asdict,dataclass,field
from typing import Any,Callable,Mapping,Protocol
import time,uuid

class QueryFeatureExtractor(Protocol):
    def extract(self, query:Mapping[str,Any])->Mapping[str,float]: ...
class RiskEstimator(Protocol):
    def estimate(self, features:Mapping[str,float],model:str)->float: ...
class CostEstimator(Protocol):
    def estimate(self,model:str,prompt_tokens:int=0,completion_tokens:int=0)->float: ...
@dataclass(frozen=True)
class RouteDecision:
    initial_model:str; predicted_risk:float; estimated_cost:float; quality_escalation_model:str|None=None; reason:str=""
class QualityCascade(Protocol):
    def decide(self,decision:RouteDecision,probe:Mapping[str,Any]|None)->RouteDecision: ...
class AvailabilityFallback(Protocol):
    def candidates(self,model:str,error_category:str)->list[str]: ...
@dataclass
class TelemetryEvent:
    request_id:str; initial_model:str; final_model:str|None=None; quality_escalated:bool=False; service_fallback:bool=False; predicted_risk:float|None=None; prompt_tokens:int=0; completion_tokens:int=0; estimated_cost:float=0.; stage_latency_ms:dict[str,float]=field(default_factory=dict); circuit_state:dict[str,Any]=field(default_factory=dict); success:bool=False; failure_category:str|None=None; attempts:list[dict[str,Any]]=field(default_factory=list)
class Telemetry:
    def __init__(self,sink:Callable[[dict],None]|None=None):self.records=[];self.sink=sink
    def start(self,decision:RouteDecision)->TelemetryEvent:
        e=TelemetryEvent(str(uuid.uuid4()),decision.initial_model,predicted_risk=decision.predicted_risk,estimated_cost=decision.estimated_cost);return e
    def emit(self,event:TelemetryEvent):
        row=asdict(event);self.records.append(row)
        if self.sink:self.sink(row)
class RACMCRRuntime:
    def __init__(self,features:QueryFeatureExtractor,risk:RiskEstimator,cost:CostEstimator,quality:QualityCascade,availability:AvailabilityFallback,telemetry:Telemetry):self.features=features;self.risk=risk;self.cost=cost;self.quality=quality;self.availability=availability;self.telemetry=telemetry
    def new_decision(self,query,model,risk_limit=.03):
        f=self.features.extract(query);r=float(self.risk.estimate(f,model));return RouteDecision(model,r,float(self.cost.estimate(model)),reason="risk_within_limit" if r<=risk_limit else "risk_exceeds_limit")
