# ERRATUM — stage_c_r9_v1 execution EXEC_122256 (in-batch infra fix, no scope change)

**Batch authorization (unchanged):** "授权执行 Stage-C-R9（8-run 最小真实验证），上限 80 次调用、150,000 Token。"
This erratum documents a stop-diagnose-fix-resume cycle INSIDE that authorization.
No frozen file was modified (six_arm_scheduler.py, stage_c_r1.py, silver_v2.json SHA-gated and untouched).

## 1. What happened

The first launch (12:22–12:28) was stopped manually at **26 calls / 43,864 tokens** after both
completed SC-E1-r1 arm runs came back degenerate (`INCOMPLETE_RECOVERY_EXHAUSTED`, 0 terminal facts):

- `Joint(R,pi)` (A_plain): the persistent S2 contract fault at `e1_chk` correctly defeated
  all retries (4 attempts, ledger #11–14) — this arm's outcome is the designed CONTROL and is expected.
- `Joint(Z,R,pi)` (B_split): never reached `e1_chk`. Its `e1_tl` (timeline) node truncated at
  `OUT_CAP=1024` (`stop_reason=max_tokens`, ledger #19, retries #20–22 all re-truncated) →
  fail-closed 'parse' → recovery exhausted on the WRONG node → Z never had a legal candidate
  (Z-space=['KEEP'] every round).

## 2. Root causes (both in the NEW R9 files, not in frozen infrastructure)

- **r9-1 Output truncation:** `MeterR9Adapter.OUT_CAP=1024` is below the v2 timeline-contract
  output volume. Deterministic retry-and-truncate-again burned 3 paid calls (~6K tok) per occurrence.
- **r9-2 Purpose namespace:** arm runs used per-arm `run_id` in call purposes, so the pre-registered
  "arms fork from the identical post-fault snapshot / prefix dedups via Meter" intent was not
  realized — arms re-paid identical prefix prompts (ledger #6–10 duplicate #1–5), and the budget
  arithmetic (≈69 calls needed vs 54 remaining) did not close.

## 3. Fixes (stage_c_r9_chain.py e7e53394, stage_c_r9_exec.py)

1. `OUT_CAP` 1024 → 2048.
2. Recap path: a dedup-replayed record that truncated under the OLD 1024 cap is regenerated once
   at 2048 under a `:recap2048` purpose; fresh calls that still truncate at 2048 fail closed as before.
3. `MeterR9Adapter` gains a purpose `namespace` decoupled from `run_id`; the exec driver points arm
   adapters at the SHARED prefix namespace (`R9B-shared-<tid>-r<rep>`), restoring fork-by-dedup:
   identical prefix calls replay free, arms pay only post-fault suffix calls (retries / split nodes / report).
4. `QuotaMeter` no longer counts dedup replays against per-model call quotas (phantom-call bug,
   caught in review before it could trip glm53 65 mid-batch).

## 4. Zero-call revalidation (after fixes, before resume)

Synthetic contract model, S2 fault at each event's verification node:
- SC-E1: A `INCOMPLETE_RECOVERY_EXHAUSTED` / B `COMPLETE` via `SPLIT_VERIFY` (102 terminal facts)
- SC-E3: A `INCOMPLETE_RECOVERY_EXHAUSTED` / B `COMPLETE` via `SPLIT_VERIFY` (17 terminal facts,
  incl. exchange_ratio 1:0.1339 vs 1:0.1335 → 不一致, matching silver E3-DD-1 direction)

## 5. Spend accounting

- Sunk at stop: 26 calls / 43,864 tok (of which ~6K tok = r9-1 truncation retries, ~7K = r9-2
  duplicate prefix — both defect-attributable, retained in ledger as diagnostic spend).
- Resume estimate: ≈40 further calls / ≈67K tok; fits remaining 54 calls / 106,136 tok with margin.
- Ledger is append-only; dedup guarantees no re-payment of any settled (purpose, prompt_sha256).

## 6. Design semantics reaffirmed (NOT changed)

Persistent contract injection at the verification node is the pre-registered R4 semantics
("the node's merged-scope port contract keeps failing"); only Z=SPLIT_VERIFY (new node ids,
not injected) can escape it. A exhausting retries is the control condition, not a defect.

---

## SUPERSEDED (2026-10-30 12:46)

本文件第三节的 r9-1/r9-2 修复（OUT_CAP 2048 + recap + 命名空间）已被并行代理（Codex 会话）
的 **delta 合同重写**取代（chain 2832121e）：回显溢出的根因在合同层（要求模型逐条回显全部
继承事实），提高上限不可扩展。本文件的价值保留部分：停止取证（26/43,864）、r9-2 前缀重复
付费发现、QuotaMeter 幻影重放修复（在 exec 内生效）、零调用 Z 机制验证。
付费执行未恢复（恢复尝试被 SHA 门拦截，零新增调用）。批次维持 fail-stop，等待操作员裁决，
见 /root/cap_eval_bench_v1/STAGE_C_R9_V1_INTERIM.md（含第五节协同补记）。
