# P1b-1: Semantic-Contract Audit — shared interpretation errors limit update-aware trust (2026-09-27)

**Headline**: Independent generation does not guarantee independent evidence.
A verifier that never sees the stored computation still shares its
interpretation errors with the generation channel — endorsement happens
exactly where it should not.

Cohort accounting (exact): P1b-1 issued **136 verifier calls in total: two
20-task development passes and one frozen evaluation pass over the 96-task
P0-2 panel**. Because 20 tasks overlap with the development diagnostic set,
the primary held-out evaluation excludes those tasks and reports the remaining
**76 non-overlapping test tasks**. Single model ('large'), temperature 0, one
call per task, zero abstains; oracle equiv_gold offline only; protocol
pre-frozen (`PROTOCOL.json`).

## Primary endpoint (stored-correct stratum, held-out: 2 reuse-harm + 19 safe)

| signal | harm caught | safe retained | false interventions |
|---|---|---|---|
| lexical write-checks (V1) | 2/2 | 17/19 | 2 |
| cross-model agreement | 0/2 | 10/19 | 9 |
| **semantic contract** | **0/2** | 9/19 | 10 |
| oracle equiv_gold | 2/2 | 19/19 | 0 |

## Mechanism (variables: valid / equiv_stored / equiv_gold)

- Contract quality: **Q_contract = P(E_contract ≡ E_gold) = 14/76** under the
  deterministic perturbation-equivalence check (value-coincidence excluded).
- **Both reuse-harm cases received valid contracts that were equivalent to
  the stored computation but NOT equivalent to the gold computation**
  (valid=1, equiv_stored=1, equiv_gold=0) — proven error endorsement.
- All 10 false interventions are contract-error-driven (contract wrong on
  10/10): the signal is dominated by contract error, not stored error.
- Prompt refinement was insufficient to remove the shared convention error
  (two dev rounds, 11/20 → 11/20): the ×100 ratio/percent conflict persists
  as a consistent disagreement between benchmark convention and the model's
  independent reading — scoped to "current model, fixed decoding, two rounds
  of refinement", not a claim about all prompts.
- The deterministic layer is NOT the failure point: on dev stored-correct,
  equiv(contract,stored) ≡ equiv(contract,gold) in 12/12 — whenever the
  contract is right, the proxy IS the oracle. The pipeline decomposes as
  Question→Contract (failure point) → Deterministic Equivalence (validated).

## Unifying finding (with prior evidence)

cross-model agreement ⇏ correctness; LLM value-verifier agreement ⇏
correctness; and now **independent semantic interpretation ⇏ independent
evidence** — all three fail via the same mechanism, shared systematic error:
e_stored^wrong ≈ e_contract^wrong, two independent call paths, non-independent
errors. Across the verifier families evaluated in this study — lexical
checks, cross-model agreement, value verification, and independent semantic
contracts — none provided a reliable deployable proxy for oracle structural
equivalence on the held-out panel.

## Zero-call error decomposition (62 wrong contracts, held-out)

| cause | n | share | cumulative |
|---|---|---|---|
| scale (×100 convention) | 18 | 29% | 29% |
| denominator structure | 15 | 24% | **53%** |
| operand selection | 15 | 24% | 77% |
| other | 8 | 13% | 90% |
| operator set | 6 | 10% | 100% |

Scale + denominator — exactly the typed-arithmetic families — cover 53% of
contract errors; adding grounded operand evidence reaches 77%. This is the
empirical basis for P1b-2 (below): replace the contract SOURCE, keep the
validated deterministic comparison layer.

## Policy replay (held-out, zero workflow calls)

| policy | Q | C (tok) |
|---|---|---|
| Always-Reuse | 0.2632 | 0 |
| Always-Regenerate | 0.2632 | 696 |
| contract gate | 0.2632 | 594 |
| oracle semantic gate | 0.2895 | 640 |
| lexical gate | 0.3026 | 568 |

The lexical gate showed an observed +3.9pp improvement on this small
held-out set; given the very small number of decisive transitions (2
reuse-harm / 3 regen-recover / 4 regen-harm — single tasks move points by
1.3pp), we treat this as an unstable descriptive result rather than evidence
of generalizable superiority. Even the oracle semantic gate caps at +2.6pp
(intervention pool: 3 recoveries vs 4 harms).

## Verifier cost accounting (break-even derivation)

C_V = 468.4 tokens = mean total tokens of the 96 frozen-pass contract calls
(prompt + completion, 'large' model). A verified-gate policy pays C_V/n per
reuse when the contract is stored in the forest and reused n times:
594 / 360 / 220 / 173 tokens at n = 1 / 2 / 5 / 10 (includes action costs at
the measured rates). At n=1 the verification alone costs 2.0× a full
reasoning regeneration (231 tokens), while the gate's measured action-value
is ≈0 — so at n=1 any such verifier must beat a cheaper always-regenerate
policy that itself ties Always-Reuse; amortization n≥2 or a cheaper contract
channel is required for positive value.

## P1b-2 direction (pre-registered): Grounded Semantic Contract

Keep C_sem → Equivalent(C_sem, e_stored) (validated). Replace the contract
source with evidence channels that do not share the generation channel's
conventions: (1) typed arithmetic operators — ratio = a/b and percentage =
100·a/b as distinct typed ops, removing the ×100 decision from free-form LLM
interpretation (first cut: the 29% scale family); (2) units/scale constraints;
(3) execution-trace operand-role evidence (24% operand family); (4) only then
external/stronger models. Methodological claim for the paper: reliable
multi-agent intervention cannot rest on "a second model's opinion"; verification
has information gain only when its evidence channel is independent of the
generation channel IN ERROR MECHANISM, not merely in call path.

Artifacts: `PROTOCOL.json`, `CONTRACTS_dev.json` / `CONTRACTS_dev_v2.json` /
`CONTRACTS_test_v2.json`, `RESULTS.json`, `REQUESTS/RESPONSES.jsonl`,
`graph_forest_v2_p1b_contract.py`, `graph_forest_v2_p1b_analyze.py`.
