# Supplementary Search Mechanism Review (Q3 deepened, Q4 boundary, Q4b wiring)

Supersedes the corresponding sections of SEARCH_MECHANISM_REVIEW.md (8854abf).

## Q3 REVISED: qNEHVI is an APPROXIMATION, not exact

**Original verdict (PASS) downgraded to PASS_WITH_CAVEAT.**

### What the code actually does

`sa_pgfs_v1/replay_v2.py:202-219`:
1. Fits ONE GP on observed configs' (features, Q)
2. Calls `sur.predict(X[ev])` → archive posterior (mu_a, sg_a)
3. Calls `sur.predict(X[uneval])` → candidate posterior (mu_c, sg_c)
4. Samples `qa = _sample_q(mu_a, sg_a, ...)` and `qc = _sample_q(mu_c, sg_c, ...)`
5. For each MC draw s: builds archive from qa[s], adds candidate from qc[s], computes HV gain

### Why this is NOT exact qNEHVI

`_sample_q()` (acquisition.py:16-18) samples each point INDEPENDENTLY:
```python
z = rng.standard_normal((n, len(mu)))
return np.clip(mu + sigma * z, 0.0, 1.0)
```

- No cross-covariance between archive and candidate points
- No conditioning of candidate samples on archive observations
- True qNEHVI (q=1) would sample from the JOINT posterior: the candidate's
  Q sample should be correlated with archive Q samples through the GP covariance

### What it IS

A valid **independent-marginal EHVI over a re-sampled archive** — the archive
uncertainty is propagated (which distinguishes it from point-archive EHVI), but
the correlation structure is ignored. This tends to OVERESTIMATE improvement
for candidates that are similar (in feature space) to archive points, because
independent sampling can produce "archive is bad, candidate is good" draws
more frequently than the joint posterior would.

### Required action

Label this method as **"approximate qNEHVI"** or **"independent-sampling
EHVI with archive re-sampling"** in the paper. Do NOT claim exact qNEHVI.
The comparison remains fair (all methods get the same information); only the
label needs correction.

---

## Q4 REVISED: C/L boundary — "deterministic" claim is FALSE for the real evaluator

**Original verdict (PASS) downgraded to CONDITIONAL_PASS.**

### What "deterministic C/L" means in each context

| Context | C/L source | Deterministic? | Visible to selector before evaluation? |
|---|---|---|---|
| Replay harness (replay_v2.py) | Frozen table `objs[uneval]` | YES (fixed values) | YES (all methods see same) |
| Real evaluator (evaluator.py) | `sum(r['response']['usage']['total_tokens'])` from actual model calls | **NO** (varies with prompt length, response length, recovery triggering) | **NO** (SearchSession correctly hides) |

### Why C/L are NOT deterministic in the real evaluator

1. **Token count depends on actual response**: completion tokens vary per call
2. **Service latency depends on server state**: queue position, model load
3. **Recovery triggering depends on detection**: if r fails, reroute fires,
   adding calls and tokens; if r succeeds, no recovery cost
4. **Under FULL recovery**: which tasks trigger replay depends on verification
   results — different tasks → different total C and L

### The boundary is correctly maintained in code

- `SearchSession.step()` passes only `candidates` (id/X/Z) and `observations`
- No reference to unrevealed configs' C/L
- BUT: the SEARCH ALGORITHMS (in replay_v2 and six_method_closed_loop)
  assume C/L are known a priori (they pass `cand_obj` with true C/L)
- In the real evaluator, this assumption breaks: the algorithm would need
  to either (a) estimate C/L from config features, or (b) treat them as
  uncertain objectives

### Required action for real experiment

The real SearchSession must:
1. Provide C/L **estimates** (from config structure: model assignments ×
   expected token counts) to the selector, NOT actual values
2. After evaluation, update with actual C/L
3. Document this distinction in the paper: "C/L are estimated a priori from
   config structure and updated with actual measurements post-evaluation"

---

## Q4b NEW FINDING: 48-config space not wired to six methods

### Status

| Component | Space | FULL included? | Features? | Tested with 6 methods? |
|---|---|---|---|---|
| `evaluator.py:space()` | 48 | YES (16 FULL) | **NO** | NO |
| `unified_space.py` | 32 | NO | YES (7 dims) | YES (stub) |
| `replay_v2.py` | 15 | NO | YES (integer codes) | YES (frozen cube) |

### Gap

The production evaluator (`joint_search_v1/evaluator.py`) defines a 48-config
space including FULL recovery. But:
1. Its configs have **no `features` field** — the six search methods require
   a feature array
2. The six-method stub test (`six_method_closed_loop.py`) was run on the
   32-config unified space, NOT the 48-config evaluator space
3. FULL recovery configs have never been selected by any search method in testing

### Required action

Before formal experiment:
1. Add feature extraction to the 48-config space (same 7 structural features
   as unified_space, plus a FULL indicator)
2. Run the six-method closed-loop stub test on the **48-config** space
3. Verify at least one method selects a FULL config in the stub test
4. Verify the evaluator can execute the selected FULL config (already verified
   in test_evaluator.py, but not through the search loop)

---

## Revised summary table

| Question | Original verdict | Revised verdict | Blocking? |
|---|---|---|---|
| Q1: Proposed uses fitted GP + acquisition | PASS | PASS (unchanged) | No |
| Q2: Ablations only remove mechanism | PASS | PASS (unchanged) | No |
| Q3: qNEHVI is real | PASS | **PASS_WITH_CAVEAT** (approximate, not exact) | No (label correction) |
| Q4: No truth leak | PASS | **CONDITIONAL_PASS** (C/L not deterministic in real eval) | No (design decision needed) |
| Q4b: 48-config wiring | Not checked | **GAP_IDENTIFIED** (features missing, stub untested on 48) | **YES — must fix before formal experiment** |
