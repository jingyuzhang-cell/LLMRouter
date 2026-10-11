# P3_B2_REPORT — final evidence-gap closure (operator review of 9e3801e)

Authorization: phase-3 final-evidence round (baseline 9e3801e). Exactly
the three approved items; no reward/candidate/filter/profile/golden
changes; zero real model calls.

## 1. Deterministic MIXED scenario (mandated item 1) — added, PASS

The prior regression indeed had cached=0 (reviewer's observation
confirmed: it proved only the injected non-double-count). New boundary-
suite checks (`p3b2_*`) drive a **FULL_DYNAMIC** plan (M5 machinery)
whose ledger provably contains, in ONE run:

| Quantity | Value |
|---|---|
| call events | 7 |
| physical requests | 5 |
| cached (e1, e2 identity-unchanged replays) | 2 |
| injected (r corruption-after-metering) | 1 |

Per-event conservation asserted: **calls field == call events ==
requests + cached**; requests == physical events; cached_calls ==
cached events; injected ⊆ physical; tokens_total == Σ physical usage ==
the task's settled physical spend.

## 2. Audit E1 strengthened (mandated item 2) — direct identity + reverse

`audit_p3a.py` E1 no longer merely excludes the old double-count
pattern; it now checks DIRECT identities against the ledger
(calls == events; requests == physical events; cached_calls == cached
events; injected ⊆ physical; tokens exact) and includes **three reverse
tests** that corrupt counters in different ways — off-by-one `calls`,
the historical `requests+injected` mode, and a `cached+injected` mode —
each of which must FAIL the checker. All pass on the post-fix tree.

## 3. M6_ACCEPTANCE §6 count residue (mandated item 3) — fixed

Section 6 now carries **214/214 as current**, with 199 → 207 → 210 →
214 explicitly labeled as HISTORICAL stage counts and their causes
(M6 errata growth, P3-B additions, P3-B2 mixed-scenario checks). No old
evidence rewritten.

## Full regression (live count, all nine suites ALL PASS)

M1 21/21 · M2 24/24 · M3 37/37 · M4 28/28 · M5 24/24 · M6 24/24 ·
M5+M6 18/18 · phase-3 19/19 · boundary **19/19** = **214/214** (210 +
4 new mixed-scenario checks; nothing removed or relaxed).

## Independent audit re-run on the final tree

**PASS 17 · CONDITIONAL 2 · FAIL 0**; R2/B3/E1 RESOLVED in place. The
two CONDITIONALs are the agreed external-validity boundaries, retained
at sign-off: **B4** (E1 exactness is declared-family-conditional;
synthetic validation ≠ real-model calibration) and **T1** (time
quantities reconcile and are recorded separately; no real-deployment
latency upper bound is claimed).

## Status

Phase-3 evidence complete per the operator's final checklist. Ready
for the unreserved phase-3 sign-off with B4/T1 carried as explicit
external-validity boundaries. Real-model experiments, production
integration, Formal, and net-benefit remain HOLD — this round
authorizes none of them.
