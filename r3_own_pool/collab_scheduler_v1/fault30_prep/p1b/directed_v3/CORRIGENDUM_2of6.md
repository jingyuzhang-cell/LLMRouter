# Corrigendum (appended, originals untouched): evidence count 4/6 -> 2/6

Strict recount of the six acceptance booleans in
runs/directed_1791434325_5d67f18b/EVIDENCE_VERDICT.json: only items 5 (v real
response with fence-parsed scoring) and 6 (accounting separated) are true.
Items 1-4 (patch triggered / graph changed / r1,r2 real calls / v prompt
contains real r2.val) were not exercised. The earlier prose "4/6" mistakenly
counted "ledger complete" and "budget clean" — ancillary facts, not among the
six defined items. Root cause unchanged: the pool draw `{"expression":"v3 - v4"}`
is a valid executable expression on this task's 10 extracted facts.
