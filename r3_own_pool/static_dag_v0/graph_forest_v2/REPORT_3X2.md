# Graph Forest v2 — 3×2 Paired Experiment Report (2026-09-26)

**Question**: does write-time validation lift reuse quality, and does reuse beat
regeneration / full rerun on follow-ups? — 74 real model calls (repair retries +
full-rerun arm), everything else from frozen artifacts. Protocol frozen before
generation: `gpu_3x2/PROTOCOL.json`.

## Six-cell result (20 tasks, +10% fact follow-up; Q = exact-value correct)

| write ↓ / follow-up → | A reuse (0 fu-calls) | B regen (40 calls) | C full rerun (60 calls) |
|---|---|---|---|
| **V0 store as-is** | **Q=12/20**, 0 tok | Q=3/20, 7.3k tok | Q=0/20, **87.5k tok** |
| **V1D deployable validate+repair** | Q=11/20, +6 write calls, 1.7k tok | = B | = C |
| **V1O oracle-select + generic repair** | Q=12/20, +8 write calls, 1.8k tok | = B | = C |

(B/C ignore the forest, so V is logically replicated for them.)

## Findings

1. **H1 falsified in both directions — and the mechanism is feedback specificity.**
   - V1O (oracle knows exactly which 8 nodes are wrong, generic "re-derive"
     feedback): **0/8 changed** — at temperature 0 the model reproduces the
     identical expression. Systematic errors are sticky; selection is not the
     bottleneck, the feedback channel is.
   - V1D (deployable flags, specific feedback): 4/6 changed — **1 fixed**
     (`(v0+v1)*100/2 → (v0+v1)/2`, the ×100 was a true-positive percent flag),
     **2 harmed** (both correct pure-sums received a false `rel_div`/`percent`
     flag and got `/100` injected: `v0+..+v3 → (v0+..+v3)/100` twice).
     Net Q: 12 → 11. Write-time intervention is NET NEGATIVE with
     lexical-check precision 0.33.
   - Discriminating variable: the only fix came from a TRUE-positive specific
     check; every harm came from a FALSE-positive check; generic feedback
     changes nothing.

2. **Reuse strictly dominates every alternative** — higher Q (12 vs 3 vs 0) at
   zero follow-up cost. The intuitive "regenerate is safer than trusting
   history" assumption is empirically dead on this scenario: B costs 40 calls
   to drop Q by 9 points; C costs 60 calls and 87.5k tokens to score 0/20
   (9/20 chains fail to parse/execute at all; several more return the
   UNMODIFIED old value — the follow-up phrasing breaks re-extraction and the
   modification does not propagate).

3. **Cross-model agreement is a null result as a write validator** (zero-call
   analysis): 4/8 wrong nodes are unanimous across all three models (same
   `v1-v0`, same spurious `/3`, same `×100`); 3/12 correct nodes are minority
   reports (majority applies ×100 wrongly). Write contamination is
   SYSTEMATIC, not noise — majority/second-opinion signals have no ceiling
   here at 7B scale.

4. **Selective Intervention now unifies three levels** (same signature:
   intervention on healthy state is harmful):
   - task level (frozen200): Always-Dynamic harms 25.3% of surviving Single-correct tasks;
   - node level (this pkg, REUSE_ARM): regenerating a correct stored expression drops
     12→3 correct;
   - write time (this pkg, 3×2): repairing a correct stored expression via
     imprecise checks drops 12→11.

5. **verifier_accept=0/19 correctly re-framed**: accuracy (84%, base-rate) vs
   discriminative utility (rejects all 3 correct values too; zero sensitivity
   on positives). Must be reported as such in the paper.

## Implications for the second paper (SA-PGFS)

- The forest's default follow-up policy is settled: **deterministic reuse
  first**; regeneration only on structural change, gated by expected net value
  V(a|s) — with the empirical constant that regeneration on this distribution
  is 4× worse AND non-free.
- Write-time validation should NOT be sold as a quality lift on this benchmark;
  its honest framing is (a) exec/schema safety (catches unparseable states),
  and (b) a precision-gated selective repair whose value equals check
  precision. Lexical checks are the weak link → motivates learned/semantic
  write validation as the open problem.
- State-dependent Pareto frontier is real: the same graph is (Q, C, L) =
  (0.60, ~2.2k, ~2s) fresh but (0.60, ~0.2k, ~0.4s) on a forest hit — reuse
  changes which graphs are non-dominated per state, which is exactly the
  h-conditioning F(G | x, h) in the method.

## Artifacts

- `graph_forest_v2_write_validation.py` → `WRITE_VALIDATION.json` (validator P/R)
- `graph_forest_v2_3x2_freeze.py` → `gpu_3x2/PROTOCOL.json` (pre-generation freeze)
- `graph_forest_v2_3x2.py` → `gpu_3x2/{REQUESTS,RESPONSES}.jsonl`, `RAW.json` (74 calls)
- `graph_forest_v2_3x2_analyze.py` → `PAIRED_3X2.json` (cells, transitions, hypotheses)
