# Two-task interleaved zero-call admission

Modified ab_review_diagnostic.py: cell_specs verifies four unique ordered cells and additive global envelopes; run_cell invokes existing InitialDAGGenerator with zero repairs/no fallbacks, original Schema, source validation and review. Separate per-run directories, MeteredExecutor caches and DISPATCH ledgers; same public task UID for paired methods but distinct run IDs T1_A/T1_B/T2_B/T2_A. Cell exceptions keep usage/reservations and continue; global deadline/loading errors stop globally. No DAG executor/scorer invoked. Gold file never read in runner; hash-only verify binds it.

State inventory is nine states exactly as requested (not ten): NOT_STARTED, GENERATION_FAILED, STRUCTURE_REJECTED, CONTRACT_REJECTED, SOURCE_REJECTED, REVIEW_REJECTED, ACCEPTED, RESOURCE_STOP, INFRASTRUCTURE_ERROR. Raw validation events are retained; classifier is report-only, never a validation substitute. Strict JSON errors, type/source errors and skipped review cannot be accepted. Infrastructure/provider failures retain pending reservations. There are no retries or reallocations.

Stub trace: generic existing three-node fixtures only, first A fails, paired B and both remaining cells accepted; 7 Stub dispatch attempts, no HTTP. Independent ledgers and zero-dispatch resource refusal tested. Acceptance tasks are not used as Stub plans. Entire regression logs attached. Tests do not prove real model generation success.

Frozen cell resource maxima: T1-A 2 requests/12045 Tokens; T1-B 2/12321; T2-B 2/12308; T2-A 2/12032. Sum8/48706. A24077/B24629. Actual frozen generation inputs3085/3361/3348/3072 plus768 output; conditional review upper8192 including256 output. Unknown usage keeps full reserve; no group transfer. Generation-only, no nodes or scoring.

Wall envelope664=CPU94+load300+8 requests*30+cleanup30. Runtime checks elapsed CPU and remaining full load/request/cleanup envelope, and absolute alarm reserves cleanup. These are enforced caps inherited from measured preparation, not a guaranteed service performance bound. OS uninterruptible loading/cleanup cannot be proven to obey finite deadline; such infrastructure failures must be recorded. Fresh model health/weight identity remain execution-time gates. No loading was performed here.

Independence audit scans project roots with explicit exclusions. Exact matches and semantic keyword candidates are recorded; absence is not global proof. Arithmetic task-family overlap remains a semantic near-duplicate risk. No independent-generalization claim before reviewing these limitations. Original frozen packet remains unchanged; this version binds changed runner/tests and unchanged task contents.

Command for zero-call verification: python3 -m collab_scheduler_v1.typed_dag_v1.ab_review_diagnostic --packet collab_scheduler_v1/typed_dag_v1/planner_contract_acceptance_v2
Do not add --execute without new explicit authorization. Operational preparation is ready for reviewed diagnostic authorization, subject to declared independence and wall limitations. Real generation/review/execution/quality all remain untested in this packet. No Git commit/push, no model/HTTP, no frozen48 or scoring edits.
