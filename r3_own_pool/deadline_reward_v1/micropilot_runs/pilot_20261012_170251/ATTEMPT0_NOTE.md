# Attempt 0 — zero-spend gate misfire (2026-10-12 17:02)

The launcher pre-created the run directory; execute() then refused
(mkdir exist_ok=False, "no silent reuse"). Failure occurred BEFORE
budget creation, BEFORE any model server start, BEFORE any request:
0 requests / 0 tokens / 0 s of GPU. Wiring fix: the launcher no longer
pre-creates the directory (execute() owns creation). Disclosed in the
micro-pilot report; the ONE authorized real run follows the fix.
