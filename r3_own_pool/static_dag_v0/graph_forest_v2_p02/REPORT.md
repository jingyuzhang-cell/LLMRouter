# P0-2: Normalized 3×2 action-utility study — 96-task normalized follow-up panel (2026-09-27)

**326 real calls** (38 V1 repairs + 96 B + 96 C′-extraction + 96 C′-reasoning),
exactly the frozen budget estimate. Panel: the **96-task normalized follow-up
panel** (fresh_static; chosen because it is the only panel with 96/96
exact-target derivability and 96/96 structured-source locatability —
DRYRUN.json; frozen200 supports 134/200 at best). All future references to
this experiment use "96-task normalized follow-up panel", never "200-task".
Protocol frozen pre-run (`PROTOCOL.json`); C′ pilot gate passed at exactly
6/10 propagation. Oracle validation offline only. **No NL modification
sentence anywhere**; question text unchanged in all arms.

## Six cells (96 tasks)

| write | A Reuse | B Regenerate | C′ Full rerun |
|---|---|---|---|
| V0 raw | **Q=0.3333**, C=0, L=0 | Q=0.3333, C=231 tok, L=0.36s | Q=0.1667, C=4423 tok, L=4.82s |
| V1 deployable validated | Q=0.3229, C=105 tok (amortized N=1), L=0.25s | = V0-B | = V0-C′ |

Paired: A−B ΔQ=0.000 (McNemar p=1.0); A−C′ ΔQ=+0.167 (p=0.0009);
B−C′ ΔQ=+0.167 (p=0.0009). C/L CIs (paired bootstrap 10k): B
231 [226,236] tok; C′ 4423 [4233,4625] tok / 4.82 [4.35,5.35] s.

## The four conditional quantities (V(a|s) inputs)

stored-correct n=33 / stored-wrong n=63:

| a | P(harm \| stored correct) | P(recover \| stored wrong) | ΔC (tok) | ΔL (s) |
|---|---|---|---|---|
| A reuse (V0) | 0.061 (2/33)* | 0.016 (1/63) | 0 | 0 |
| A reuse (V1) | 0.152 (5/33) | 0.048 (3/63) | 105 | 0.25 |
| B regenerate | 0.121 (4/33) | 0.048 (3/63) | 231 | 0.36 |
| C′ full rerun | **0.606 (20/33)** | 0.048 (3/63) | 4423 | 4.82 |

*A's 2/33 losses are a distinct phenomenon from intervention harm — see
Finding 3 (update-aware validity), not model-call damage.

## Findings

1. **The GFv2-20 "regeneration collapses 12→3" was an NL-interface artifact.**
   With the normalized protocol (original question, structured facts[0]×1.10),
   B ties A overall (p=1.0): B breaks 4/33 correct (12%) but fixes 3/63 wrong
   (5%) — net wash. The earlier collapse came from the appended "Assume X is
   10% higher" sentence disturbing regeneration, not from regeneration itself.
   Old C (0/20) stays as the historical diagnostic of NL-interface damage.
2. **A and B tie on Q but differ in mechanism** — B regenerates more actively:
   it recovers more of the wrong states (3/63 vs A's 1/63) AND breaks more of
   the correct ones (4/33 vs 2/33); the two effects exactly cancel. This is
   the most direct experimental statement yet of **more intervention ⇏ higher
   utility**. The open problem P1b must solve: keep the 3 recoveries while
   avoiding the 4 harms.
3. **Originally correct ≠ counterfactually reusable.** A makes ZERO model
   calls, yet loses 2/33 stored-correct tasks under the fact update: a stored
   expression that answers correctly on the original facts does not
   necessarily encode the true dependency (coincidental correctness on the
   original values, missing dependency, wrong formula coinciding at the
   original point, incomplete provenance). This upgrades P1b's target from
   P(output correct) to **Update-aware Trust**
   T_reuse = P(stored computation remains valid under update δ | s).
   (Inheritance is 31/33 here vs 20/20 on the GFv2-20 subset.)
4. **C′'s bottleneck is the modified-source → extraction propagation stage**:
   only 48/96 (50%) structured mutations were correctly captured by
   re-extraction; the overall Q=0.1667 is *consistent with* this propagation
   loss (≈0.50 × ~0.33 conditional-on-propagation), though a per-task causal
   attribution has not been verified. Full rerun at 19× B's cost halves Q —
   re-extraction is both the cost and the failure point (first-occurrence
   mutation policy per frozen protocol; multi-occurrence values are the main
   ambiguity).
5. **Under the current frozen model pool, prompts, and action set, runtime
   interventions recover at most 4.8% of contaminated states** — observed
   overall quality is therefore mainly bounded by write-state quality. (Not a
   permanent ceiling claim: future semantic verifiers, decomposition, other
   models, or tool execution may raise recovery.)
6. **Empirical Pareto dominance — the first real multi-objective action data:**
   A Pareto-dominates B (Q equal at 0.3333; C 0<231; L 0<0.36) and strictly
   dominates C′ (Q 0.3333>0.1667; C 0<4423; L 0<4.82). V1-Reuse (0.3229, 105,
   0.25s) is itself dominated by Raw-Reuse — deployable write-validation is
   now 2-for-2 net-negative across panels. In THIS history state the
   state-conditioned Pareto front degenerates to a single action: Raw-Reuse.
   Other states (structural change, verified corruption, high distrust) are
   expected to expand the front — that is precisely the scheduler's reason to
   exist.

## Policy statement (scoped)

On this 96-task normalized follow-up panel, under the current action set and
frozen model pool, Raw-Reuse is the observed most efficient strategy: equal
overall Q to reasoning regeneration at zero new model tokens, and strictly
dominant over full rerun.

## Artifacts

`DRYRUN.json` (panel feasibility), `PROTOCOL.json` (pre-run freeze),
`REQUESTS/RESPONSES.jsonl` + `RAW_KEYS.json` (326 calls, pilot 6/10),
`RESULTS.json` (cells, strata, paired stats), scripts
`graph_forest_v2_p02_{dryrun,freeze,run,analyze}.py`.
