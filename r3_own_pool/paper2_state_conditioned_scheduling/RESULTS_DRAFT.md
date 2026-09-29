# Paper 2 — Results draft (v1, 2026-09-28)

One-sentence argument: On a frozen 200-task financial-question panel with fully
measured workflow objectives, we show that heterogeneous multi-agent
collaboration is not globally superior, that runtime state restructures the
cooperative design space, and that state-conditioned surrogate-assisted Pareto
search recovers the measured cooperative front as sample-efficiently as the
strongest noisy multi-objective baseline — under a preregistered, hash-anchored
evaluation.

Terminology ledger (canonical forms used throughout):

| Canonical | First-use definition |
|---|---|
| Reference Cube | 15-configuration cooperative space G_collab = (Y, X, Z), measured on both states |
| Y / X / Z | topology (SER, SERV, Parallel-ER, DynamicDAG); node-level model assignment family (BALANCED, HETEROGENEOUS, QUALITY); recovery policy (none, local reroute) |
| Q / C / L | workflow quality (final-producer accuracy); workflow cost (node tokens, cold-run accounting); critical-path latency |
| s_clean / s_fault30 | clean state; frozen fault state (30% persistent node–model faults, 3 seeds, 200 tasks) |
| SA-PGFS | state-conditioned surrogate-assisted Pareto graph-forest scheduling (EHVI and cost-aware variants) |
| signed normalized HV gap | 1 − HV(found)/HV(true front); may be negative under observation noise |
| AUC-HV, N95%HV, recall | area under the HV curve over the evaluation budget; evaluations to 95% of true HV; fraction of true front found (deduplicated by objective vector) |

---

## Results

### A measured Reference Cube with a single-point global front

We first established ground truth for cooperative workflow design by measuring
all 15 legal configurations of the Reference Cube — four topologies (Y), three
heterogeneous model-assignment families (X) and, on the dynamic topology, two
recovery policies (Z) — on a frozen panel of 200 financial questions, under a
clean state and a frozen fault state (30% persistent node–model capability
faults, three seeds, 600 evaluations per configuration). Each configuration
was scored on three unified objectives: workflow quality (Q), workflow token
cost (C) and critical-path latency (L). An independent re-implementation of
the evaluator, resolving cache aliases from the raw execution ledgers,
reproduced all 15 per-configuration results exactly, and the cooperative
DynamicDAG configuration sharing the legacy study's model assignment agreed
with the legacy clean measurement to within 0.005 in Q and 3 tokens in C,
validating the pipeline across independent executions.

Against this ground truth, a single large model (Single) dominated every
cooperative configuration on all three objectives in both states
(Fig. 1a, Table 1): in the clean state, Single reached Q = 0.550 at C = 612.8
tokens and L = 0.46 s, whereas the best cooperative configuration
(SER-HETEROGENEOUS) reached Q = 0.370 at 963.5 tokens. Collaboration was
therefore not inherently superior on this panel: entering the cooperative
design space was justified only by constraints or states not captured by the
global front, which we test next.

### Runtime state restructures the cooperative design space

Although the global front was unchanged under faults (P_clean = P_fault =
{Single}), the fault state reshaped the cooperative subspace. Within G_collab,
the Pareto front expanded from two points in the clean state to three
structurally distinct points under faults, doubling its hypervolume
(0.052 to 0.101; Fig. 1b). The new front point was the recovery-enabled
configuration DynamicDAG–HETEROGENEOUS–local-reroute (Q = 0.343 ± 0.005,
C = 2089, L = 4.45 s), which traded roughly 622 additional tokens and 1.3 s
of critical-path latency for a 6.7-percentage-point quality gain over its
no-recovery counterpart — and did so consistently in all three fault seeds
(per-seed gains +0.060 to +0.075).

Recovery bought quality at measurable cost in every model-assignment family
(Δ_Z Q = +0.030, +0.067 and +0.023 for BALANCED, HETEROGENEOUS and QUALITY,
at +789, +622 and +613 tokens respectively; Table 2), indicating that the
value we measured attaches to the recovery dimension rather than to one
assignment family. The state also changed which *topology* was preferred:
SERV outranked DynamicDAG in the clean state, and the ranking reversed under
faults as local reroute activated. By contrast, the ranking of assignment
families (HETEROGENEOUS > QUALITY > BALANCED) was unchanged between states.
Runtime state, in this design space, acted primarily on topology and
recovery policy rather than on model-assignment preference.

Because these measurements contradicted two numbers in our legacy audit, we
re-examined the legacy fault ledgers before interpreting them. Forensic
replay of the recorded responses showed that injected extraction- and
reasoning-stage faults had been recorded as byte-identical no-ops in the
legacy static fault arm, and that the fault-side prompts implied by the
legacy code path exist in no execution ledger; the corresponding legacy
values (f30_static, f30_dynamic) were therefore retired from the evidence
chain (Methods; Supplementary Note 1), and the re-measured dynamic value
(0.343 here versus 0.403 legacy) accounts for the discrepancy. A
sensitivity audit over the two server sessions that contribute to the clean
ledger — 108 cross-session duplicate executions, 20 with divergent
temperature-zero outputs — left all 15 clean results bit-identical under
first-, last- and session-consistent resolution, bounding this source of
noise at zero for the reported quantities.

### Search efficiency on the measured front

We then asked how efficiently the measured cooperative front can be
discovered under a limited evaluation budget, comparing SA-PGFS — a
state-conditioned surrogate-assisted Pareto search over graph-forest
configurations — against representative search mechanisms adapted to the
same frozen configuration space and lookup evaluator: random search,
single-objective greedy selection, NSGA-II, scalarized Bayesian optimization
(qNParEGO), noisy expected-hypervolume-improvement search (qNEHVI) and
MCTS-based workflow search (AFlow-style). All methods shared a preregistered
protocol (200 paired replay seeds, common two-configuration initial design,
common per-seed fault noise, budget of eight evaluations, frozen surrogate
and reference point), so that comparisons isolate search behaviour rather
than implementation differences (Methods; Supplementary Note 2).

SA-PGFS recovered the true front as efficiently as the strongest baseline:
both SA-PGFS variants and qNEHVI reached a median signed normalized HV gap
indistinguishable from zero (−0.001), achieved 95% of true hypervolume in
160–165 of 200 seeds within the budget, and attained identical mean AUC-HV
(0.922; Table 3). Paired permutation tests resolved no difference between
SA-PGFS and qNEHVI (all P ≥ 0.46), while both significantly outperformed
every other mechanism — qNParEGO (+0.058 gap), AFlow-style MCTS (+0.014),
NSGA-II (+0.081), greedy (+0.070) and random (+0.085) — with P < 10⁻⁴ in
all twelve paired comparisons. The differentiation of SA-PGFS from qNEHVI
in our framework is consequently not acquisition strength on a single-state
table, which these data rule out, but the surrounding scheduling problem:
the feasible graph set, admissible recovery actions and Pareto archive are
defined relative to runtime state, allowing the outer scheduler to decide
when cooperative search is worth entering at all.

### Boundaries of the findings

Three boundaries qualify these results. First, all measurements come from a
single 200-task domain with one fault model; faults are a frozen state
intervention on node–model triples, and our conclusions concern the value of
recovery policies under that intervention rather than changes in model
capability. Second, the search comparison used a budget of eight
evaluations on a 15-configuration space in which evaluation costs are nearly
homogeneous; evolutionary and scalarized methods are known to favour larger
budgets, and the cost-aware acquisition differentiates only where evaluation
costs are heterogeneous, so the complexity boundary at which
surrogate-assisted Pareto search becomes preferable to simple scalarized
search remains open (preregistered follow-up in Supplementary Note 3).
Third, external mechanisms were adapted to the frozen space rather than
reproduced end-to-end; the comparison evaluates search behaviour, not the
original systems.

---

Figure/Table plan (main text): Fig. 1 (a: global front, both states;
b: cooperative fronts clean vs fault; c: Δ_Z trade-off). Table 1: 15
configurations × two states (Q, C, L). Table 2: Δ_Z per family with
per-seed ranges. Table 3: unified algorithm table (200 paired seeds,
P values). SI: provenance forensics, session-sensitivity audit, five-step
fault audit, frozen protocol and hash manifest, preregistered scale-up plan.

Assumptions or missing inputs: target journal and length limit not specified
(drafted at generic ~1,100-word Results); Methods section to be drafted
next from the frozen protocols; exact figure rendering awaits the
paper-level figure pass.
