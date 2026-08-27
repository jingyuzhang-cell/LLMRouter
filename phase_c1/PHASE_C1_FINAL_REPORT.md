# Phase C1 Final Decision

## Methodological status

- v2 is retained only as a distribution-shift diagnostic set.
- C1 used 28 structural features and excluded dataset/task-type identity.
- The target was centered pairwise delta utility.
- Pairwise outputs were aggregated through zero-sum least-squares Bradley–Terry latent scores.
- No FRAR risk term or lambda was used.

## Global structural interaction

- Pairwise sign-accuracy lift over global prior: +3.27 percentage points.
- OOF gap recovery: -40.59%.
- Development-validation gap recovery: -13.15%.
- Validation recovery 95% CI: [-72.07%, 24.00%].
- C1 gate: failed.

## Leave-one-group-out

- TAT-low recovery: +7.42%, unstable.
- TAT-medium recovery: -5.29%.
- Obli-high recovery: +37.73%, 95% CI [18.10%, 54.31%].

The interaction mechanism is strongly group-specific. Only the Obli-high transfer result is stable.

## Group-conditional fallback

- Group-conditional Best Single recovery: -1.14%.
- Group-conditional structural Router recovery: -41.54%.
- Structural Router positive-recovery probability: 4.06%.
- Group-conditional gate: failed.

## Final decision

Stop learned compatibility and FRAR development on the current 209-task target-support pool. Do not collect v3 yet. Expand the outcome-blind target-support development pool first; the current method is not stable enough to freeze for a confirmatory test.
