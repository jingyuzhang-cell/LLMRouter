# Attempt 1 — infrastructure failure (0 real model calls)

The authorized real run started, passed all gates, created the run
directory, and attempted to start the model server. The GPU had
DISAPPEARED from the system (nvidia-smi: "No devices were found"; no
PCI device visible). start_model correctly refused. Fail-stop fired:
INCOMPLETE written, exception preserved, server cleanup attempted.

Resource consumption: 0 requests / 0 tokens / 0 GPU seconds.

Per the GO ruling ("fail-stop, no repair-restart"), the run is
terminal. The operator must decide whether the GPU environment has
been restored before any re-authorization.
