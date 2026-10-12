# Planner contract publication and independent preparation

No HTTP requests, inference, model service, execution, scoring, commits or push in this preparation.

## Actual changes
- planner_catalogue.py: catalogue() derives operation names, contract IDs, node types, required roles/cardinality, typed outputs and task inputs from protocol.CONTRACTS and goal_ir.OPERATIONS. calculate is deterministic expression evaluation; form_expression produces unevaluated syntax. No new executable operation.
- generation.py: both modes receive identical public_task.operation_catalogue and available_node_types, and the same GOAL_FIRST instruction. Existing representation-specific instructions and Schema remain distinct. Repair and independent review share the public catalogue. Existing validator/executor/allocation/scoring unchanged.
- test_planner_catalogue.py: five tests for actual contracts, registry subset, version hash, deterministic calculation inputs, variable topology wording/no semantic guarantee.

## Fairness
Two tasks share identical public_task dictionaries across A/B (checked during freeze). A describes producer refs; B describes symbols with role-keyed inputs. Operation descriptions, source manifest, required source declarations, planning model and strict validation/review requirements are identical. Different representation instructions and Schema overhead are saved and Token-measured. No answer enters Prompt. No fixed node count or automatic unknown producer completion.

## Independent tasks and evidence limits
TASK_1: archival scanning usable pages; TASK_2: greenhouse combined survival percentage. Public sources and requirements are separate from GOLD_ONLY.json. New UID and exact question were searched in typed_dag_v1 historical text artifacts before writing inputs: no matches. This is bounded exposure evidence, not a universal workspace/training-data proof. Tasks were never given Stub answers or used for candidate tuning; capture stopped before any generation response. Source/Prompt/Schema/catalogue/file hashes frozen in PROTOCOL.json. Original historical packets unchanged.

## Tests
323 typed tests +18 original evaluator/runtime tests =341 passed (previous336 +5). Logs attached. Existing multi-root, forward-reference, three/five-node and historical replay tests remain in full suite.

## Proposed generation-only diagnostic
2 tasks x2 representations x(generate1 + conditional review1): at most8 requests. Order T1-A,T1-B,T2-B,T2-A; separate cell ledgers/cache and independent arm envelopes. No repair, retry, fallback success, node execution or scoring. Review skipped if no admitted candidate; spare resources cannot fund other attempts.
Actual local Tokenizer measured every complete generation message including context, manifest, catalogue and embedded full Schema; transport Schema is saved separately. Max generation output768. Each review reserves8192 total (input hard cap7936, output256); dynamic review input must be measured before dispatch and refused if too long. Unknown failure usage retains entire reservation. Global48706 Tokens, A24077, B24629; no transfers. This is a hard bounded request envelope, not a promise that a candidate fits or succeeds.
Wall proposal664 seconds = prior offline CPU-preflight cap94 +load cap300 +8x30 HTTP timeout +cleanup30. CPU/load values are inherited caps, not fresh measured loading performance; revalidation required. One medium activation, no model switching for this generation-only diagnostic. Execution-stage heterogeneous loading and execution Token/wall envelope are NOT authorized or frozen by this proposal.

## Metrics
Report HTTP and full Schema separately; initial structural legality; required input/source paths; final goal chain; independent semantic review; nonfallback acceptance. Preserve denominators, skipped/not-tested status and raw failures. True execution completion and answer correctness remain NOT TESTED and require separate real execution envelope. Source path presence is not fact correctness or proof of complete semantic coverage. Catalogue and backward planning are guidance, not a correctness guarantee.

## Remaining blockers / stop
The existing ab_review_diagnostic.py entry is single-task A then B. No multi-task interleaving adapter is frozen here; PROTOCOL explicitly marks preparation not executable. This must be implemented and Stub-tested before requesting real authorization. Existing diagnostic tasks are exposed and are not reused as independent evidence. Small two-task diagnostic cannot establish stable success rate or generalization. Unknown semantic relevance, operation intent, factual support and unit meaning still require review and eventual actual execution.
No real experiment can start from this packet yet. Stop here as requested; no automatic launch.
