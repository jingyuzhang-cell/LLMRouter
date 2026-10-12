# Post-diagnostic read-only failure analysis

No real requests/model loading, no repair of saved candidates, no changes to frozen Prompt/Schema/data/scoring. Added test_real_ab_v3_replay.py: four raw response regression tests. Source hash recorded below; old frozen packets remain bound to their original code and are not eligible for rerun after new test additions without a new version.

T1-A: transformation n3 selects itself for facts; actual producer kind calculated_result, expected source_fact. Compiler first-failure is PRODUCER_TYPE_MISMATCH. Candidate extraction only uses ctx_table; required text deductions have no declared extraction source. A second independent source concern, not evidence of an executed wrong answer.

T1-B: HTTP200 with finish_reason=length and completion_tokens768. The unfinished fifth step ref contains an extended repeated 10 sequence. This is observed output repetition plus truncation, not evidence that merely increasing output cap would create a valid graph. Four extraction steps plus a fifth expression step already occupy max5 nodes, but required final calculated_value has no completed producer; no extrapolation of the missing response is valid. Full JSON is unparseable. Do not auto-close JSON or manufacture steps.

T2-B: model final symbol answer (verified_value) differs from the actual verification output symbol verified_value. Compiler IR_GOAL_UNCOVERED. Four declared operations are plausible syntactically, but acceptance requires exact producer identity. Unit % on source facts is also a semantic concern for raw counts; no execution or semantic reviewer established its correctness.

T2-A: four extraction nodes then a transformation with expression n4 (self-produced number) and facts n5 (undefined). No declared expression-producing node. Five-node cap does not force failure: multiple facts can be represented by one registered facts output; nevertheless the program must not regroup sources or invent expression nodes to repair this candidate.

Next preparation should examine bounded identifier lengths/service grammar repetition and representation verbosity in generic, non-exposed Stub examples. Raising max output requires new equal A/B Token envelopes, not reuse of this exhausted/completed diagnostic. Exact reference/type defects are correctly rejected; adding more rejection rules alone does not establish generation reliability. Do not tune exposed tasks and then describe them as independent samples. Any proposed planner restructuring needs separate preparation before another authorized real experiment.

All four responses remain byte-identical and tests reject them. No legal graph, review, execution or quality evidence created by this replay. Stop here; no further real calls.
