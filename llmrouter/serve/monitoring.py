"""Persistent, aggregate-only resilience telemetry and alerting."""
from collections import Counter,deque
import json,os,threading
from pathlib import Path

NONRECOVERABLE={"authentication","invalid_request"}
class ResilienceMonitor:
 def __init__(self,max_latencies=10000,persistence_path=None,alert_thresholds=None,quality_cascade_enabled=False):
  self.lock=threading.Lock();self.max_latencies=max_latencies;self.persistence_path=Path(persistence_path) if persistence_path else None;self.quality_cascade_enabled=quality_cascade_enabled
  self.thresholds={"all_chain_failure_rate":.005,"p95_latency_regression_fraction":.15,"circuit_open_rate":.02,"duplicate_calls_prevented":0,"quality_escalation_rate":.25};self.thresholds.update(alert_thresholds or {})
  self.requests=0;self.successes=0;self.quality_escalations=0;self.service_fallbacks=0;self.all_chain_failures=0;self.duplicate_calls_prevented=0;self.circuit_open_skips=0;self.stream_aborts=0;self.errors=Counter();self.prompt_tokens=0;self.completion_tokens=0;self.estimated_cost=0.;self.latencies=deque(maxlen=max_latencies);self.p95_baseline_ms=None
  self._load()
 def _state(self):
  return {"requests":self.requests,"successes":self.successes,"quality_escalations":self.quality_escalations,"service_fallbacks":self.service_fallbacks,"all_chain_failures":self.all_chain_failures,"duplicate_calls_prevented":self.duplicate_calls_prevented,"circuit_open_skips":self.circuit_open_skips,"stream_aborts":self.stream_aborts,"errors":dict(self.errors),"prompt_tokens":self.prompt_tokens,"completion_tokens":self.completion_tokens,"estimated_cost":self.estimated_cost,"latencies":list(self.latencies),"p95_baseline_ms":self.p95_baseline_ms}
 def _load(self):
  if not self.persistence_path or not self.persistence_path.exists():return
  try:
   state=json.loads(self.persistence_path.read_text())
   for key in ("requests","successes","quality_escalations","service_fallbacks","all_chain_failures","duplicate_calls_prevented","circuit_open_skips","stream_aborts","prompt_tokens","completion_tokens"):setattr(self,key,int(state.get(key,0)))
   self.estimated_cost=float(state.get("estimated_cost",0));self.errors=Counter(state.get("errors",{}));self.latencies=deque(state.get("latencies",[]),maxlen=self.max_latencies);self.p95_baseline_ms=state.get("p95_baseline_ms")
  except (OSError,ValueError,TypeError):pass
 def _persist(self):
  if not self.persistence_path:return
  self.persistence_path.parent.mkdir(parents=True,exist_ok=True);tmp=self.persistence_path.with_suffix(self.persistence_path.suffix+".tmp");tmp.write_text(json.dumps(self._state()));os.replace(tmp,self.persistence_path)
 def record(self,*,success,primary,final,events,latency_s,usage=None,input_price=0.,output_price=0.,quality_escalated=False,duplicates_prevented=0):
  usage=usage or {};pt=int(usage.get("prompt_tokens",0) or 0);ct=int(usage.get("completion_tokens",0) or 0)
  with self.lock:
   self.requests+=1;self.successes+=int(success);self.quality_escalations+=int(quality_escalated);self.service_fallbacks+=int(bool(success and final and final!=primary));self.all_chain_failures+=int(not success);self.duplicate_calls_prevented+=int(duplicates_prevented);self.circuit_open_skips+=sum(e.get("outcome")=="circuit_open" for e in events);self.prompt_tokens+=pt;self.completion_tokens+=ct;self.estimated_cost+=(pt*input_price+ct*output_price)/1_000_000;self.latencies.append(float(latency_s)*1000)
   for e in events:
    if e.get("category"):self.errors[e["category"]]+=1
   if self.p95_baseline_ms is None and len(self.latencies)>=20:self.p95_baseline_ms=self._percentile(sorted(self.latencies),.95)
   self._persist()
 def record_stream_abort(self,category="stream_abort"):
  with self.lock:self.stream_aborts+=1;self._persist()
 @staticmethod
 def _percentile(lat,p):return lat[min(len(lat)-1,round((len(lat)-1)*p))] if lat else 0.
 def snapshot(self,circuits):
  with self.lock:
   n=self.requests;lat=sorted(self.latencies);p95=self._percentile(lat,.95);open_count=sum(v.get("state")=="open" for v in circuits.values());circuit_rate=open_count/max(len(circuits),1);nonrecoverable=sum(self.errors[x] for x in NONRECOVERABLE);regression=((p95/self.p95_baseline_ms)-1) if self.p95_baseline_ms else 0.
   alerts={"all_chain_failure_rate":n>0 and self.all_chain_failures/n>self.thresholds["all_chain_failure_rate"],"p95_latency_regression":self.p95_baseline_ms is not None and regression>self.thresholds["p95_latency_regression_fraction"],"circuit_open_rate":circuit_rate>self.thresholds["circuit_open_rate"],"nonrecoverable_error":nonrecoverable>0,"duplicate_calls_increase":self.duplicate_calls_prevented>self.thresholds["duplicate_calls_prevented"]}
   if self.quality_cascade_enabled:alerts["quality_escalation_rate"]=n>0 and self.quality_escalations/n>self.thresholds["quality_escalation_rate"]
   return {"requests":n,"successes":self.successes,"quality_cascade_enabled":self.quality_cascade_enabled,"quality_escalation_rate":self.quality_escalations/n if n else 0.,"service_fallback_rate":self.service_fallbacks/n if n else 0.,"all_chain_failure_rate":self.all_chain_failures/n if n else 0.,"error_categories":dict(self.errors),"nonrecoverable_error_count":nonrecoverable,"circuits":circuits,"circuit_open_rate":circuit_rate,"tokens":{"prompt":self.prompt_tokens,"completion":self.completion_tokens},"estimated_token_cost":self.estimated_cost,"latency_ms":{"p50":self._percentile(lat,.50),"p95":p95,"p99":self._percentile(lat,.99),"samples":len(lat),"baseline_p95":self.p95_baseline_ms,"p95_regression_fraction":regression},"duplicate_calls_prevented":self.duplicate_calls_prevented,"circuit_open_skips":self.circuit_open_skips,"stream_aborts":self.stream_aborts,"alert_thresholds":dict(self.thresholds),"alerts":alerts,"active_alerts":[k for k,v in alerts.items() if v]}
 def prometheus(self,circuits):
  s=self.snapshot(circuits);metrics={"llmrouter_requests_total":s["requests"],"llmrouter_successes_total":s["successes"],"llmrouter_quality_escalation_rate":s["quality_escalation_rate"],"llmrouter_service_fallback_rate":s["service_fallback_rate"],"llmrouter_all_chain_failure_rate":s["all_chain_failure_rate"],"llmrouter_estimated_token_cost_total":s["estimated_token_cost"],"llmrouter_latency_p50_ms":s["latency_ms"]["p50"],"llmrouter_latency_p95_ms":s["latency_ms"]["p95"],"llmrouter_latency_p99_ms":s["latency_ms"]["p99"],"llmrouter_latency_p95_baseline_ms":s["latency_ms"]["baseline_p95"] or 0.,"llmrouter_duplicate_calls_prevented_total":s["duplicate_calls_prevented"],"llmrouter_stream_aborts_total":s["stream_aborts"],"llmrouter_circuit_open_rate":s["circuit_open_rate"]}
  lines=[f"# TYPE {k} gauge\n{k} {v}" for k,v in metrics.items()]
  for category,value in s["error_categories"].items():lines.append(f'llmrouter_errors_total{{category="{category}"}} {value}')
  for name,state in circuits.items():lines.append(f'llmrouter_circuit_open{{model="{name}"}} {int(state.get("state")=="open")}')
  for name,value in s["alerts"].items():lines.append(f'llmrouter_alert_active{{alert="{name}"}} {int(value)}')
  return "\n".join(lines)+"\n"
class OpenTelemetryExporter:
    """OTLP metrics adapter enabled by OTEL_EXPORTER_OTLP_METRICS_ENDPOINT."""

    def __init__(self):
        self.enabled = False
        self.sdk_available = False
        self.endpoint = os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
        self._last = {}
        try:
            from opentelemetry import metrics
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        except ImportError:
            self.meter = None
            return
        self.sdk_available = True
        if not self.endpoint:
            self.meter = None
            return
        exporter = OTLPMetricExporter(endpoint=self.endpoint)
        interval = int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", "60000"))
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=interval)
        provider = MeterProvider(metric_readers=[reader])
        self._provider = provider
        self.meter = provider.get_meter("llmrouter.ra_cmcr")
        self.request_counter = self.meter.create_counter("llmrouter.requests")
        self.failure_counter = self.meter.create_counter("llmrouter.all_chain_failures")
        self.duplicate_counter = self.meter.create_counter("llmrouter.duplicate_calls_prevented")
        self.enabled = True

    def export(self, snapshot):
        if not self.enabled:
            return False
        current = {
            "requests": snapshot["requests"],
            "failures": round(snapshot["all_chain_failure_rate"] * snapshot["requests"]),
            "duplicates": snapshot["duplicate_calls_prevented"],
        }
        self.request_counter.add(max(0, current["requests"] - self._last.get("requests", 0)))
        self.failure_counter.add(max(0, current["failures"] - self._last.get("failures", 0)))
        self.duplicate_counter.add(max(0, current["duplicates"] - self._last.get("duplicates", 0)))
        self._last = current
        return True

    def force_flush(self, timeout_millis=10000):
        if not self.enabled:
            return False
        return self._provider.force_flush(timeout_millis=timeout_millis)
