# P1b-2: Grounded Semantic Contract — typed grounding does not resolve shared task-interpretation errors (2026-09-27)

116 calls (20 dev schema-design pass + 96 frozen test pass; 'large',
temperature 0). Protocol pre-frozen (`PROTOCOL.json`); primary metrics on the
76 non-overlapping held-out tasks; abstain (12/76, schema-inexpressible)
pre-registered as DO-NOT-INTERVENE; policy replays frozen P0-2 outcomes.

## Three-layer result (held-out, 76)

**Layer 1 — Contract fidelity**: Q_grounded = P(E_contract ≡ E_gold) =
**15/76** vs free-form 14/76 (H1 fails: no lift). Abstain 12/76.

**Layer 2 — Trust discrimination** (2 reuse-harm + 19 safe):

| | grounded (P1b-2) | free-form (P1b-1) | oracle |
|---|---|---|---|
| harm caught | 0/2 | 0/2 | 2/2 |
| safe retained | 10/19 | 9/19 | 19/19 |

H3 fails again — both reuse-harm contracts remain equivalent to the stored
computation (error endorsement persists). H2 improves by exactly one task.

**Layer 3 — Policy utility**: grounded gate Q=0.2632 = Always-Reuse at
573 tok (verifier 473 tok; amortized 236/95/47 at n=2/5/10). No policy gain.

## Mechanism: the shared error lives at the question-READING level

Family selection on held-out: percentage_change 27 + percentage 7 = **34/76
×100-family choices; ratio chosen only 4 times** — while the benchmark's gold
convention is overwhelmingly raw-ratio. Dev confirms this is not disobedience:
two dev questions LITERALLY ask "percentage change" and the gold program is
still the unscaled ratio. Typing fixed WHERE ×100 can appear (operator
semantics are now deterministic) but cannot fix WHEN the model believes the
question asks for a percentage — that belief is shared with the stored
generation channel, so the endorsement failure persists one level up.

The verifier-family null chain is now complete and each link is located:

    lexical checks ............ weak priors (P=0.33)
    cross-model agreement ..... correlated model errors
    LLM value verifier ........ no discriminative power
    free-form contract ........ shared convention (expression level)
    typed/grounded contract ... shared convention (family-selection level)

Independent CALLS, shared READING. On this benchmark the ×100 ratio/percent
convention conflict between natural reading and gold convention is
irreducible for any verifier that reads the question with the same model
family.

## Verdict and what it licenses

- The arithmetic-grounding layer is NOT wasted: it is validated
  infrastructure (deterministic compiler + the 12/12-fidelity comparison
  layer from P1b-1) and it eliminated expression-level scale errors — the
  residual conflict is now precisely isolated at reading/semantics.
- Per the pre-registered escalation ladder, the next evidence class must NOT
  read the question with the same LLM: candidates are (a) units/scale
  constraints propagated from the DATA (table headers, units in facts) rather
  than the question; (b) execution-trace operand-role evidence; (c) external
  solvers. Alternatively — and equally publishable — this chain stands as
  the paper's central mechanism finding: **verification gains information
  only when the evidence channel is independent in ERROR MECHANISM, and
  within one model family, LLM reading is a shared error mechanism**.
- On this benchmark family the state-conditioned Pareto front remains
  Raw-Reuse; every verifier variant evaluated (5 families) is dominated.

Artifacts: `PROTOCOL.json`, `CONTRACTS_dev_v1.json` / `CONTRACTS_test_v1.json`,
`RESULTS.json`, `REQUESTS/RESPONSES.jsonl`, `graph_forest_v2_p1b2_grounded.py`,
`graph_forest_v2_p1b2_analyze.py`.
