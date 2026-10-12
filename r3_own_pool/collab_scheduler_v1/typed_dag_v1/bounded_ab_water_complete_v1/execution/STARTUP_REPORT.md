# Authorized water A/B startup stopped

Frozen hash/model-file/config/Tokenizer/packet checks passed and373/373 regressions passed. Initial GPU sample found external vLLM PID20648; subsequent sample empty. Attempted frozen entry once. Exclusive local_gpu.lock acquisition returned errno11 before model audit/loading/service creation or requests. Stopped, no retry/lock deletion/external service termination.

A/B both NOT_STARTED. No HTTP/Schema/DAG/review result exists; all success rates NOT_TESTED, not0%. Requests0, Tokens0, no pending reserve. No owned GPU process/service created, therefore no owned cleanup needed; external lock owner untouched. Original packet/source/historical evidence unchanged. Raw startup traceback saved.

This is infrastructure/resource admission failure, not model planning failure. Requires an available exclusive GPU lock before another separately invoked startup attempt. Do not remove a live lock or bypass mutual exclusion. No real diagnostic result or node/scoring execution. No commit/push.
