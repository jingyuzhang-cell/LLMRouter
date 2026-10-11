# M2_REPORT — SchedulerState observation API, phase-2 milestone M2

Authorization: operator M1 review (2026-10-11) — "M2 GO,仅授权
SchedulerState"。Scope held to M2; M3–M6 NOT started; zero real model calls
(M2 suite 24/24, M1 suite still 21/21 after hardening — no expectation was
relaxed).

## Delivered

| File | Content |
|---|---|
| `scheduler_state.py` | `SchedulerState` observing the M1 engine: per-node PENDING/RUNNING/DONE/FAILED status + current model; occurred-only legal observations (D1/D3/D5/D6 now, D2/D4 reserved for M4); recovery counters (all zero until M4); ruled time口径 — `release_time`, `first_call_time`, `completion_time`, `e2e = release→termination` (incl. queue wait + interleave), `queue_wait_s`, `other_wait_s`, `service_sum_s`, `switch_sum_s`, live `d_remain = D − clock`; budget with `b_remain = allocation − spent` COMPUTED live (never a constant); whitelist-guarded `make_legal_view` (L2 firewall at construction); prefix-exact `snapshot`/`replay`. |
| `detection.py` | Mirrors of the production predicates (stdlib only): facts-empty (D1), value_of error semantics (D3), json_value float-coercion + close `max(1e-4, 1e-4·|b|)` with a-not-None (D5), observable-only task failure (D6, mirrors evaluator.detected_failure). **Parity asserted against the production functions on a probe grid** — two real divergences were found and fixed during development (json_value coercion; close tolerance), which is exactly why the mirror is parity-tested, not trusted. |
| `stub_engine.py` (M2 additions, M1 semantics unchanged) | observer hook (fail-loud), `call_start`/`panel_start`/`session_summary` events, cold-start switches tagged `kind='cold_start'` + session-level index REFERENCES (no re-summing — operator ruling 1), per-(task,node,kind) answer overrides, `n_events` counter; **hardened `load_ledger`: only an unfinished TAIL write is tolerated; mid-file corruption raises `LedgerCorruptionError`** (operator ruling). |
| `test_stub_engine.py` | path now derived from `__file__` (no `/root` hardcode — checkouts run anywhere); +2 hardening regression checks (21/21). |
| `test_scheduler_state.py` | 24 checks: transitions incl. mid-flight RUNNING via prefix replay, ruled-E2E monotonicity, live D_remain, budget conservation across three independent ledgers, legal codes only, LEAK_PROBES rejection, no node outputs in views, prefix-exact snapshot rebuild (by event index — clock-tie safe), no-future snapshots, determinism, production detection parity, zero-call sentinel + stdlib/siblings-only AST, socket-blocked. |

## Time reconciliation sample (3-task panel, v3_compat profile)

| task | release | first_call | completion | E2E | queue | service | switch | other(interleave) |
|---|---|---|---|---|---|---|---|---|
| m1t0 | 0.0 | 3.0 | 10.5 | **10.5** | 0.0 | 0.8 | 8.5 (incl. cold start) | 1.2 |
| m1t1 | 0.0 | 3.4 | 10.7 | **10.7** | 3.4 | 0.8 | 0.0 | 6.5 |
| m1t2 | 0.0 | 3.8 | 10.9 | **10.9** | 3.8 | 0.8 | 0.0 | 6.3 |

E2E = queue + service + attributed switches + other-tasks' interleaved work
— exactly the ruled口径; a bare service sum would have claimed 0.8 s.

## Budget reconciliation sample

12 requests / 1200 tokens spent (identical in: per-task views, session
view, engine `session_summary`, ledger call records) · allocation 4000 ⇒
`b_remain_tokens = 2800` computed at read time.

## Deviation found & fixed during M2 (recorded for review)

- Mid-run snapshot rebuild originally filtered replay by TIME; boundary
  events sharing the snapshot instant (clock is piecewise-constant) leaked
  into the rebuild. Fixed by prefix-BY-INDEX replay (`n_events_before`
  recorded per snapshot). Test `snapshot_prefix_rebuild_equal` now pins it.
- A D1 fault was expected to yield [D1, D6]; the faithful cascade is
  [D1, D3, D6] (empty e-facts make r's `v0` token unevaluable → D3), which
  MATCHES production semantics. Test corrected to assert the faithful
  sequence — the code was right, the first expectation was not.

## Not in M2 (awaiting authorization)

M3 closure/reuse · M4 recovery execution (LOCAL/FULL arms → full T3a/T3b)
· M5 model reassignment (V10 decisive test) · M6 two-stage policy + reward
settlement. No production/Formal/net-benefit file touched; production
imports only inside test files for reference/parity generation.

**Status: M2 complete; paused for operator review.**
