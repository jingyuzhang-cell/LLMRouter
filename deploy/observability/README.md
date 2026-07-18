# Staging observability

1. Mount `run_secrets/llmrouter_metrics_token` as `/run/secrets/llmrouter_metrics_token` in Prometheus.
2. Export the same value as `LLMROUTER_METRICS_TOKEN` in the LLMRouter service.
3. Run the OpenTelemetry Collector with `otel-collector.yml` and set the service environment:
   `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://otel-collector:4318/v1/metrics`.
   If the service uses an HTTP proxy, add `otel-collector` to `NO_PROXY`.
4. Run Prometheus with `prometheus.yml` and `alerts.yml`.

Keep `quality-alerts.disabled.yml` unloaded until the real quality cascade records actual escalation events and `quality_cascade_enabled` is set to true.
