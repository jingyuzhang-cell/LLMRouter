# P1a: Runtime Detector Audit — zero model calls (2026-09-26)

**Headline**: Observed deployable signals provide **no measurable gain toward
the clairvoyant fault-aware selection bound** (Q = 0.4917). The internal DAG
detector does detect many faults (interface faults 100%) — but detection that
exists only AFTER choosing Dynamic is not information for choosing Single vs
Dynamic:

    Arm selection → DAG execution → failure detection → recovery
    (step 1)        (step 2)        (step 3)             (step 4)

Existing detector signals live at steps 3–4; the clairvoyant gain requires
knowing fault status before step 1. All analysis from frozen artifacts; fault
maps regenerated deterministically (60/60/60 exact match with `injected`).

## 1. In-DAG detector audit (dynamic arm internals)

| fault type | stage-correct recall | correction success |
|---|---|---|
| e1 / e2 (interface) | 58/58, 42/42 (100%) | 17/58 (29%), 9/42 (21%) |
| r (reasoning) | see three-capability split below | — |
| v (verification) | 39/39 (100%) | 15/39 (38%) |

**Three-capability decomposition, r faults (41 total)**:

    R_detect  = 33/41 (80%)   fault surfaces somewhere (16 at r-stage, 17 late at v-stage)
    R_localize = 16/41 (39%)  correctly attributed to the reasoning node;
                              the 17 late surfacings reroute v — mislocalized repair
    P(correct | correctly localized) = 6/16 (38%)   even knowing where, rerouting r→large
                              fixes only 38%

    Detection ≠ Diagnosis ≠ Correction — each layer loses more than the last;
    8/41 r-faults never surface at all.

**Healthy-task triggering**: when the internal anomaly/fallback signals are
INTERPRETED as intervention triggers, healthy-task trigger rate reaches
**380/420 (90%)** (e_fb 345, v_esc 232, r_esc 50; multi-fire). e_fb's original
design semantics is fallback activation rather than a strict binary fault
detector — re-labelling it as a detector is our interpretation, so we state
the method implication in that form: **the high trigger rate gives these
signals no discriminative power for selective intervention**.

## 2. Single-level fault visibility: structurally unidentifiable UNDER THIS PROTOCOL

In the current Frozen200 fault-injection protocol, the Single arm's fault is
applied only at the evaluation/bookkeeping level (task marked failed, cost
doubled) — the model's actual returned content is unchanged. Therefore no
observable fault signature exists for a deployment policy to inspect before
arm selection, and recovering the injection state from the Single output is
structurally unidentifiable **in this harness**. (Counterfactual check:
injecting the actual pool texts into the single call would make 58/58 pool
entries schema-visible — cross-schema outputs; but this is an artifact of the
fault model. A semantics-preserving fault — well-formed wrong answer — stays
invisible to schema checks regardless; GFv2 documents that regime.)

## 3. Policy table (exact per-seed counterfactuals; escalation uses recorded dynamic outcomes)

| policy | Q | C (tok/task) | L (s/task) | gap to 0.4917 |
|---|---|---|---|---|
| Always-Single | 0.3967 | 613 | 0.46 | −0.095 |
| Always-Dynamic | 0.4033 | 2530 | 7.10 | −0.088 |
| SFE-schema (single-first, escalate on schema fail) | 0.3967 | 678 | 0.67 | −0.095 |
| Clairvoyant fault-aware | **0.4917** | 1425 | 2.77 | 0 |
| Selective oracle | 0.5150 | — | — | +0.023 |

τ sweep (escalate on schema-fail OR soft anomalies): soft escalation is
anti-informative — Q drops to 0.362 at τ=1; the curve never leaves the
Always-Single/Always-Dynamic hull (`pareto.png`).

## 4. Where the 8.8pp opportunity actually sits

The 0.4033 → 0.4917 fault-aware selection opportunity mainly requires
identifying fault status BEFORE entering the expensive DAG. Existing
schema/parse/DAG-internal signals either appear only after arm selection, or
are insensitive to semantics-preserving errors — two factors (temporal
position of observability + semantic visibility) jointly put the bound out of
reach. It is NOT a claim that all 8.8pp reduce to "reasoning semantic-error
detection": it is an arm-selection information problem.

## 5. Method consequences

1. The chain sharpens from "Runtime Diagnosability → Trust Estimation" to:

       Observability → Localization → Correctability → Selective Intervention

   with measured per-layer losses (80% → 39% → 38% for r faults; interface
   faults observable but only 21–29% correctable; semantic faults unobservable
   by every current primitive).
2. **P1b redefined as Semantic Trust Estimation**: inputs are node-level
   executable evidence (fact/expression dependency consistency, operand
   coverage, unit/ratio/percent semantics, intermediate execution trace,
   result-vs-evidence consistency, structured downstream counter-evidence,
   provenance/historical node reliability); the target is
   **P(node output is trustworthy | s_t)** — what the Graph Forest ultimately
   needs — not P(fault).
3. **Fault-family boundary for evaluation**: the Single-fault harness (fault
   at bookkeeping level, output unchanged) must not be the only validation
   scenario for semantic verifiers — any output-based detector is structurally
   blind there; that is a property of the protocol, not the detector. P1b
   must be evaluated on two fault families: (a) bookkeeping/latent faults and
   (b) observable semantic corruption — GFv2's well-formed-wrong errors are
   the natural source for (b). The two questions stay separate: which errors
   are unobservable in the information-theoretic sense, vs which are
   observable but not yet recognized by current verifiers.
4. P0-2 (200-task 3×2 + C′) proceeds next, with expectation set: existing
   runtime signals alone cannot beat the Always-Single/Always-Dynamic hull.

Artifacts: `AUDIT.json` (all tables incl. three-capability split), `pareto.png`
(τ-sweep mini-Pareto), `frozen200_p1a_detector_audit.py` (reproducible from
frozen artifacts).
