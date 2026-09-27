# P1b-3-B: Benchmark Semantics Adapter — FINAL trust-branch experiment (2026-09-27)

Step 1 zero calls (frozen adapter recompiles P1b-2's existing contracts);
Step 2 = 96 calls (the same frozen convention written into generation).
Three-layer criteria per protocol; policy replays frozen P0-2 outcomes;
primary metrics on the 76 held-out tasks.

## Full comparison (held-out)

| variant | L1 fidelity | harm caught | safe retained | FP | policy Q | C |
|---|---|---|---|---|---|---|
| P1b-2 original | 15/76 | 0/2 | 10/19 | 9 | 0.2632 | 573 |
| **Step1 adapter-recompile (0 calls)** | **30/76** | 0/2 | **17/19** | **2** | **0.2763** | 573 |
| Step2 generation-informed (96 calls) | 16/76 | 0/2 | 11/19 | 8 | 0.2500 | 651 |
| Step2 + adapter on top | 23/76 | 0/2 | 12/19 | 7 | 0.2500 | 685 |

## Findings

1. **The rule does all the work; calling the LLM again does nothing or
   hurts.** Step 1 (pure mechanical recompile of the model's EXISTING family
   choices under the train-derived raw-ratio convention, zero calls) is the
   best variant on every layer: fidelity doubled 15→30/76, false
   interventions 9→2, and the first policy gain of the entire verifier
   program (+1.3pp over Always-Reuse). Step 2's fresh generation — with the
   convention IN the prompt — lands at 16/76: the model still follows its
   own reading over the frozen instruction, and its fresh role choices are
   worse than the originals (adapter-on-top recovers only to 23/76). Rule
   contribution and regeneration contribution are cleanly separated, and
   regeneration's is ≤ 0.
2. **Stop condition FIRES: harm recall stays 0/2 in every variant.** Even
   with the benchmark convention corrected, both reuse-harm contracts remain
   equivalent to their stored computations — their coincidence is not a
   convention artifact. Per the pre-registered criterion, the trust-verifier
   direction CLOSES here.
3. **What survives for the scheduler**: T = **weak compatibility evidence**
   — T=True means "no benchmark-grounded semantic mismatch found"
   (endorsement correct 17/19 on safe states) and enters s=(x,h,b,f,T) as a
   SUPPORTING state feature; it is NOT a safety certificate and never a
   hard gate (harm recall 0/2: the two tasks that should not be reused were
   never flagged). T=False licenses nothing — P0-2's recover/harm ratios
   stand. Scheduler default stays Raw-Reuse.
4. **Where Step 1's real value lies**: not the one-task Q gain but the rule
   correction drastically cutting the verifier's OWN false interventions
   (9 -> 2). Step 1 produced the best observed policy result among the
   tested verifier variants (0.2763 vs 0.2632 for Always-Reuse),
   corresponding to ONE additional correct task on the 76-task held-out
   set; this is treated as descriptive rather than evidence of a
   generalizable accuracy gain.
5. **Cost accounting**: Delta-C(Step1) = 0 new calls (mechanical recompile
   of existing contracts); the 573-token column is the INHERITED total
   verifier cost from P1b-2's contract generation, not a Step-1 expense.

## Trust-branch closing summary (paper-ready)

Six verifier families evaluated across P1b-1/2/2.5/3: lexical checks,
cross-model agreement, LLM value verification, free-form contracts, typed
contracts, and convention-adapted contracts. Null chain localized at each
step; final state: one usable high-precision/zero-recall signal obtained at
zero marginal calls (the adapter recompile), everything else dominated by
Raw-Reuse. The mechanism finding stands: **evidence independence is a
property of error mechanism, not of model invocation — and within one model
family reading the same question, LLM interpretation is a shared error
mechanism.** The only interventions that ever worked were deterministic
program-side layers: perturbation equivalence, typed compilation, and the
train-frozen convention adapter.

Per the frozen plan, the next phase returns to the mainline:
collab_scheduler_v1 → real combinatorial space → SA-PGFS, with
G=(Y,X,Z,M), s=(x,h,b,f,T), and the measured action utilities from P0-2.

Artifacts: `RESULTS_STEP1.json`, `RESULTS_STEP2.json`, `CONTRACTS_test_v2.json`,
`REQUESTS/RESPONSES.jsonl`, `graph_forest_v2_p1b3_step1.py`,
`graph_forest_v2_p1b3_step2.py`.
