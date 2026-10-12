# Trace60 actual diagnostic — qualified results

3 requests,6235 known Tokens plus7592 unknown-use reservation=13827 charged, within4/31226. Earlier7250 unknown-use record unchanged. Last normal wall snapshot245.936s; final cleanup exception prevented accurate final full-wall persistence, so do not present this as exact E2E duration. Request/trace/ledger/protocol evidence retained.

A generation HTTP200 after54.83s dispatch-to-body (56.36s metered generation stage),262 output Tokens; review HTTP200 after5.03s,159 output Tokens. Both request headers echo their matching unique IDs. Full JSON/Schema/contract/goal chain passed, five-node nonfallback Graph saved. No60s timeout in A. Types extraction/reasoning/transformation/verification/verification, n0->n1; n0,n1->n2->n3->n4. Declared source paths pass for the frozen table-only requirements; model review PASS.

IMPORTANT: actual text leakage17/cleaning28 has no extraction node or other execution input binding. Frozen requirements accidentally only demandctx_table, notctx_text. This is missing necessary source declaration plus semantic-review false assurance, not proof of complete task semantics. Do not claim genuine end-to-end success or answer correctness. Graph was NOT executed/scored. Raw review, graph and context evidence retained. No task/Schema rewritten midrun.

B dispatched once with its own ID;60.000s absolute timer before response headers, UNKNOWN_TIMEOUT. No JSON/status/usage/DAG received; retain7592 reservation, skip review, stop globally, no retry. Server aggregate logs show queued work but lack request-specific schema/prefill/decode timing; these remainUNKNOWN. Cannot infer a model reasoning failure.

CLEANUP BUG: main finally references mark imported only inside dispatch; NameError before service.close. Raw RESULTS records service_stopped=false and is preserved. Recovery inspection confirms both owned PIDs28727/28784 absent, GPU process list empty, lock released; no kill necessary. This establishes resources absent at inspection, not normal cleanup success or exact service stopping time. Separate recovery record attached. Need a new-version scope fix and finally/error cleanup integration test before further real runs.

389/389 post-run regressions pass; this does not cover/negate the observed cleanup scope defect. No extra requests/node execution/scoring, no Git commit/push, historical records/fixed48/scoring unchanged. Stop here. Runner-level acceptance1/2 is not semantic completeness; no method advantage claimed from one development task.
