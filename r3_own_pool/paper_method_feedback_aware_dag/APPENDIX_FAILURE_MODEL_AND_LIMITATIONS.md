# Appendix Material — Failure Model Definition & Limitations

Source artifacts: static_dag_v0/BENCHMARK_PROTOCOL.md, VERIFIER_SUBSET_PROTOCOL.md,
corrected_replay/BUG_REPORT.md, adaptive_benchmark/STAT_CHECK.md. All numbers
recomputed and verified (STAT_CHECK: 18/18 accuracies match, 0 problems).

## A. Failure Model Definition (for the Adaptive Failure Benchmark)

**Capability fault.** A fault is a triple (task t, node k, model m): every execution
of model m for node k on task t returns a failing output, regardless of prompt. Under
greedy decoding (temperature 0) this is literal — re-executing the same (model, prompt)
reproduces the same output — so a same-model retry or a whole-flow re-execution cannot
repair the fault; only executing a DIFFERENT model on that node can. This models
persistent capability failures (the assigned model cannot handle this subtask), which
are exactly the failures a model-pool workflow can respond to by re-assignment.

**Injected outputs are real failures, not synthetic strings.** For each faulted
(task, node, planned model) triple the failing output is sampled from actual failing
outputs of the frozen panel, by node kind: e-node failures are parse-failing/empty
facts answers (79 available); r-node failures are expressions that parse but fail the
restricted interpreter (18); v-node failures are prose/non-JSON verifier answers (107).
Sampling is seeded (20260923); the 10% fault set is a subset of the 20% set, itself a
subset of the 30% set.

**Injection procedure.** floor(120 x p) tasks sampled without replacement; one faulted
node per task, uniform over {e1, e2, r, v}. Methods then apply their recovery policy
and nothing else: Router retries the same call (fault persists; cost counted as the
task's clean call x2); Static re-executes the whole flow with fixed models (the faulted
node reproduces the fault; downstream nodes run for real on the corrupt upstream;
no feedback, no model switching); Dynamic applies its deployable detection and local
recovery (recovery targets are different models, hence not faulted; recovery calls are
real executions, identical (model, prompt) pairs reused at temperature 0).

**Why this model, and what it does not cover.** The capability fault is the failure
regime in which recovery policy — the object of study — is the differentiator. Two
other regimes are explicitly out of scope: (i) transient/infrastructure faults (a
one-off glitch), where a same-model retry repairs everything; under that regime all
three methods return to clean accuracy and the comparison is cost-only — we report
that cost table separately (Router +1 call, Static +4 calls, Dynamic +1–3 calls per
fault); (ii) adversarial or Byzantine failures (wrong-but-plausible outputs designed
to pass checks), which no execution-level signal in our pool detects. The benchmark
does not claim coverage of (i)/(ii) as accuracy regimes.

**Detection semantics (unchanged from the panel protocol).** e fails = facts
unparseable or empty; r fails = expression unparseable or unexecutable; v fails =
value unparseable or disagrees with the r value. Gold answers are never used to
trigger anything — the close-to-gold check in the v stage is the frozen RD rule kept
identical across arms for comparability; it only skips recovery, never triggers it.

## B. Limitations

1. **Single seed.** Fault sets, nodes and injected outputs use one fixed seed
   (20260923). The paired Help/Harm structure (Dynamic never harms vs Static at any
   rate: 11/0, 14/0, 17/0) is robust in sign, but per-rate accuracies carry
   sampling noise; a multi-seed replication is straightforward future work.
2. **Model scale and stack.** All results use local Qwen2.5 7B/14B(-GPTQ) models on
   one 24GB GPU. The 14B GPTQ-Int8 model shows session-level nondeterminism under
   greedy decoding: re-running identical prompts across server sessions diverged in
   2/20 probe calls (~10%), and 38 same-prompt divergences were measured among the
   full-graph arm's mapped calls. This bounds the FG−RD difference (−2.5pp, p=0.25)
   and adds noise to any re-execution-based comparison; it does not affect calls
   reused verbatim.
3. **Fault coverage.** The benchmark covers capability faults only (see A). Transient
   faults are reported as a cost-only secondary reading; adversarial outputs are not
   covered.
4. **Single domain.** The frozen panel is 120 TAT-QA arithmetic table-text tasks with
   a fixed 4-node DAG. Cross-domain replication (e.g., code, math proofs) is not
   claimed; the earlier Selective-DAG experiments on TAT-QA-200/MultiHiertt-100 give
   partial external consistency for the decomposition-cost phenomenon, not for the
   fault benchmark.
5. **Supplementary status.** All experiments in this pack were designed after prior
   results on the same panel were known (including after a parser-bug correction that
   changed reported numbers; see corrected_replay/BUG_REPORT.md for the full account
   and the correction method). They are honestly labeled supplementary: an
   independent confirmation requires a fresh frozen panel untouched by any of this
   analysis. No threshold was tuned after seeing results; protocols were frozen
   before execution for every experiment in the pack.
6. **Budget accounting.** Budget numbers are post-hoc violation statistics against
   1.2x the Static arm's realized tokens (no hard limit at execution, identical
   accounting for every method); wall-clock latency is sequential per-call latency
   excluding model-server startup, reported separately where relevant.
7. **Recovery is bounded by the model pool.** The verifier ablation shows detection
   precision of 82% on reasoning errors but a 21% repair rate — escalation cannot
   fix tasks that no pool model can solve. Claims are scoped to recovery within a
   capable pool, not to lifting the capability ceiling.
