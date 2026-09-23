# BUG REPORT: json_value fence-parsing defect (found 2026-09-23)

## The bug

`r3_own_pool/static_dag_v0/multidag_dynamic.py`, `json_value()`:

```python
def json_value(ans):
    try: return float(json.loads(ans)['value'])
    except Exception:
        try: return float(json.loads(v.decode(ans))['value'])   # <- BUG
        except Exception: return None
```

The fence fallback applies `json.loads` to the dict that `v.decode()` already
returns, which raises `TypeError` every time. Net effect: **any v-node output
wrapped in a ```json fence was parsed as None**. Plain JSON parsed fine.

The bug is in the code both before and after the Sep-21 refactor commit
(06cd99c); the 120-task base panel ran with it (run 13:40–14:45; refactor
committed 14:56). `multidag_ablation.py` imports `json_value` from
`multidag_dynamic.py`, so the ablation arms (SM/RD) and the FG arm used it too.
No other experiment script in the repo has this pattern (grep-verified).

## Why it mattered

- **All 120 initial v outputs are fenced** (the coder model consistently emits
  ```json fences). So the initial v node scored `None` → wrong on every task,
  and every arm's v-stage recovery fired on ALL 120 tasks:
  base static v-fb = 120, dynamic v-esc = 120, SM v-fb = 120, RD v-esc = 120,
  FG v-rounds = 120.
- The **static arm's final scores were systematically under-counted**: its
  final v outputs (medium model) were fenced in 67 tasks; 18 of those contained
  the correct value but scored wrong. Reported static Q=0.1667; re-scoring the
  same executed outputs with a correct parser gives 0.3167.
- The dynamic/SM/RD/FG arms' FINAL v outputs come from the large model (plain
  JSON), so their reported Q values were unaffected **as scores** — but their
  event structures and costs were driven by the bug (every task paid for a
  v-stage recovery that a correct parser would often skip).
- The ablation retention claim (RD retains 91.7% of the ideal gain) was an
  artifact: the denominator (dynamic − static) was inflated by the static
  under-scoring.

## Fix

`json_value` corrected to `float(v.decode(ans)['value'])` in
`multidag_dynamic.py` (and the copy in `supplementary_analyze.py`, which is
superseded by `corrected_consolidate.py`). Historical executed logs
(RESPONSES/REQUESTS/RAW_TAIL) are untouched.

## Correction method (corrected_replay.py)

The e-stage and r-stage decisions use `parse_facts`/`value_of` only — the bug
does not affect them. The only decisions driven by `json_value` are the v-stage
trigger and the final ok. The corrected replay therefore re-decides ONLY the
v stage on the executed artifacts: for each arm/task it parses the v output
that existed before the v-fb/esc call with the fixed parser, drops that call
(or the whole FG v-round) when the check passes, and keeps it otherwise. All
retained outputs are real executed calls (their prompts are the executed ones
from the REQUESTS log); zero new model calls. This is a **re-analysis of
executed data, not an independent confirmation** (per rule 4).

## Impact summary (corrected vs reported)

| Arm | Reported Q | Corrected Q |
|---|---:|---:|
| static | 0.1667 | 0.3917 |
| dynamic (ideal) | 0.3667 | 0.4250 |
| SM (Static-Matched) | 0.3500 | 0.4167 |
| RD (Dynamic-Real) | 0.3500 | 0.4000 |
| FG (Full-Graph) | 0.3333 | 0.3750 |

- The headline "+20pp dynamic over static" becomes **+3.3pp, not significant**
  (paired CI [−0.025, +0.092], McNemar p=0.39).
- RD retention drops from 0.917 to **0.249**.
- Full corrected tables and the supplementary mechanism analyses:
  `corrected_replay/CORRECTED_CONSOLIDATED.json` + `CORRECTED_REPORT.md`.

## What this does NOT change

- The FG experiment's core comparison survives qualitatively: local recovery
  (RD) vs full-graph re-execution (FG) still shows no significant quality
  difference with large computation savings (corrected: −2.5pp, CI [−5.8, 0.0],
  p=0.25, FG never helps; FG costs +44% tokens, +92% calls vs RD).
- The 14B-GPTQ session nondeterminism finding (38 same-prompt divergences in
  the corrected FG set) still bounds the FG−RD quality gap.
