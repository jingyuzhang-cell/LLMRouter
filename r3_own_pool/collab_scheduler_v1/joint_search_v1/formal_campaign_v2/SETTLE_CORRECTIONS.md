# Settle corrections (side-car, parser-safe)

## random_20261009 — erroneous 0/0 settle (2026-10-10)

A settlement script settled the base-dir random_20261009 reservation to 0/0 from an ABSENT ledger, violating the retained-unconfirmed directive (absent ledger proves nothing). The journal event was removed to restore parser compatibility; the erroneous settle REMAINS VISIBLE in the journal history if re-added by audit — for A/B/C accounting, treat random_20261009 base reservation as UNCONFIRMED and conservatively count its 400 requests as spent. Impact check: remaining need (7 cells x 400 = 2800) fits the ceiling even under the conservative counting (6901 - 3495 = 3406).
