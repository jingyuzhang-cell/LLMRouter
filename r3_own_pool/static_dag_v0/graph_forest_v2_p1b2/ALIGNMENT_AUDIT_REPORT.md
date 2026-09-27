# P1b-2.5: Semantic Alignment Audit — route decision, zero model calls (2026-09-27)

Separates the three post-P1b-2 hypotheses. No model calls; evidence from
MultiHiertt train (7830), the held-out evidence table, and P0-2 outcomes.

## 1. Convention probe (the decisive test)

Train questions containing percent-words: 799; their gold programs:
**722/799 (90%) use the RAW ratio (no ×100)**, 77 (10%) use ×100.
MultiHiertt has a consistent, learnable-from-train annotation convention:
percent-worded questions are annotated as unscaled ratios. The benchmark's
gold semantics is NOT natural-language semantics — it is a dataset
convention that a natural reading violates ~90% of the time on this family.

## 2. Evidence table + error encoding (76 held-out; 61 wrong/abstain contracts)

| error family | n | share |
|---|---|---|
| **language-gold conflict** (pct/growth wording, gold raw, contract ×100) | **31** | **51%** |
| other (residual family confusions) | 15 | 25% |
| schema-inexpressible (abstain) | 12 | 20% |
| true model misread | 2 | 3% |
| denominator/operand ambiguity | 1 | 2% |

Unit/table-side evidence ('%' in context without question wording) produced
0 conflicts — the data-grounded unit channel has no traction on this panel
(Route A unsupported HERE).

## 3. Strata (convention-conflict tasks carry disproportionate failure)

Ambiguous (pct-like wording + gold raw) = 32/76 tasks; within them the
explicit-percent-word core (18 tasks) has **reuse Q = 0/18**; the broader
ambiguous stratum Q_reuse = 0.250 vs aligned 0.273. The convention-conflict
tasks are where the stored channel's natural reading fails against gold.

## 4. Adapter preview (zero-call, upper-bound estimate)

Applying the train-derived frozen rule (pct-worded -> compile to raw ratio)
to the 34 pct-family contract choices: fidelity **15/76 -> 30/76 (doubled)**.
(Audit preview only; the formal experiment would freeze the adapter from
train and apply it at contract-generation time.)

## Route decision

**Route B: Benchmark Semantics Adapter** — honestly named
"benchmark-specific semantic grounding": convention learned from TRAIN only,
frozen before test (e.g., pct/growth-worded questions compile to raw-ratio
families; the 10% train ×100 minority bounds adapter accuracy at ~90% on the
convention itself). Expected effect chain: contract fidelity ~2x → the
equiv(contract,stored) signal stops being convention-dominated → trust
discrimination becomes testable for real. Route A (data-grounded units) is
kept for future domains but has zero conflicts to resolve here. Route C is
present only as the 10% train inconsistency — reported as a boundary, and
the aligned/ambiguous strata split (with Q(D_aligned) vs Q(D_ambiguous))
goes into the paper's evaluation findings either way.

**Method consequence for the second paper** (scoped): the training set
reveals a DOMINANT benchmark-specific annotation convention (90% raw-ratio
on percent-worded questions; ~10% exceptions remain) — natural-language
reading is the wrong prior HERE, and the dominant convention is cheaply
learnable from train. The value to the mainline is bounded to: calibrating
the trust signal to benchmark semantics so the scheduler may finally get a
usable state variable — NOT a new research line on benchmark semantics. This sharpens the Evidence-Independence principle:
independence must come from evidence the generator did not use — here, the
train-side program-convention statistics, which no generation-path LLM
consults at inference time.
