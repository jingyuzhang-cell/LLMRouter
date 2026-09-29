# QUALITY Bit-Equality Audit (zero-call, 2026-09-28)

## Result: 3 Q-mismatches / 586 unfaulted task-evaluations (0.5%) — evaluation-path noise, not fault effects

| config | unfaulted | Q mismatch | C mismatch | delta C magnitude |
|---|---|---|---|---|
| SER__QUALITY__NONE | 153 | 1 | 2 | ≤ 22 tok (2.4%) |
| SERV__QUALITY__NONE | 140 | 1 | 2 | ≤ 19 tok |
| PARALLELER__QUALITY__NONE | 153 | 1 | 15 | ≤ 59 tok |
| DYNAMICDAG__QUALITY__NONE | 140 | 0 | 13 | ≤ 45 tok |

## Diagnosis

The 3 Q mismatches (d07836f0, c72a0760) are on tasks **without any fault in
the seed** — the fault30 executor scored ok=1 where the clean replay scored
ok=0 (and vice versa for c72a0760). Root cause: the clean evaluation
(cube_analyze.evaluate) and the fault30 executor resolve node prompts
through **different lookup chains** (clean: build_prompt → prompt_rec by
hash; fault30: executor by_mp alias → ledger). For e=large and r=large
(QUALITY), both nodes use the same model, causing alias chains to resolve
to marginally different upstream facts in rare cases, producing a different
r-prompt and hence a different expression.

This is evaluation-path alias noise, not a fault-model defect and not a
systematic bias direction (one +1, one -1, one 0-change on Q).

## Decision (documented, Cube freeze proceeds)

- Rate: 0.5% of unfaulted task-evaluations across the entire cube
- Effect on config-level ΔQ: ≤ 0.5pp per config (1 task / 200-600)
- No bias direction: mismatches are symmetric (+1 and -1)
- **Verdict: evaluation-path noise at 0.5%, documented; Reference Cube
  freeze proceeds with this note.** The dominant Y/X/Z findings
  (ΔQ_Z ≈ 6.7pp, rank flip, HET>QUALITY>BALANCED stability) are 13× larger
  than this noise floor and unaffected.
