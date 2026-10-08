# Archived Old Smoke Results (P1-B v2)

Frozen: do not overwrite, do not re-run. Preserved as evidence for code version dag_patch_p1b.py (commit 026d8fd).

## Summary
- 24/48 calls used; 6 trajectories (4 random fault + 2 directed)
- Directed r-fault: Dynamic Patch split r→r1,r2; real LLM executed new nodes
- Random fault30: all collaborative strategies Q=0; Single Q=1 (single task, not generalizable)
- v-node responses contained markdown fences (```json ... ```); old parser could not read them
- 5/150 clean responses had fences; all parse correctly with v3's _strip_fences fix

## Known limitations of old version
- scheduler_overhead_s included model call time (double-counting)
- v did not demonstrably consume r2.val (placeholder string used)
- detection only covered r-unparseable (not e1/e2/v faults)
- Q=0 may partly reflect parse failures, not wrong answers
