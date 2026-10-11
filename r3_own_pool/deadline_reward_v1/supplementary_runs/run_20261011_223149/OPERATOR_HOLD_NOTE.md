# OPERATOR HOLD — run_20261011_223149 is an ABORTED PARTIAL run

The operator's measurement HOLD arrived WHILE this run was already
executing in the background (launched after the runner's preflight pass,
before the hold message was delivered). The run was killed with its
monitoring process tree immediately upon receipt; the GPU model server
died with the process group (port 8128 free, nvidia-smi shows no compute
apps — verified at stop time).

## Accounted spend (append-only ledgers, complete)

- Physical requests: 80 of 1200 cap
- Tokens: 26,462 of 800,000 cap
- Logical calls: 197 (cache hits included), switches: 9, injected faults: 0
- Cells completed: 2 of 10 — clean|SS P=0.3 (6/20), clean|DS P=0.3 (6/20)
- Killed mid clean|SD; STATUS.json absent (no graceful finally)

## Status of the data

QUARANTINED AS DIAGNOSTIC-ONLY. These two cells are NOT the supplementary
measurement: the run is incomplete, its cell order/cache state does not
match any approved execution plan, and it was aborted by operator
intervention. The only sanctioned use: engineering diagnostics (the
natural-failure rate visible in clean cells — facts-as-strings, r
unparseables — is real signal about the panel, to be re-measured properly
under an authorized complete run).

The complete supplementary measurement has NOT run. Real calls are HOLD
per the operator's 2026-10-11 ruling, pending independent verification of
the pushed commits and the boundary conditions below.
