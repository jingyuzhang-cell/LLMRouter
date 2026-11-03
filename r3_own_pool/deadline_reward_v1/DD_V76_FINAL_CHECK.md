# DD_V76_FINAL_CHECK — 启动前最终确认（2026-10-30，零调用）

## 全部检查结果

| # | 检查项 | 状态 | 详情 |
|---|---|---|---|
| 1 | 账本/缓存隔离 | ✅ PASS | 新目录 dd_v76_n5_paired_v2/ 已创建且为空；与旧 dd_v74_n5_paired/ 完全分离 |
| 2 | SHA 篡改拒绝 | ✅ PASS | 篡改文本后 SHA 不匹配 → SHA_MISMATCH 正确拒绝 |
| 3 | 事实覆盖不足拒绝 | ✅ PASS | 截断至 200 字 → INSUFFICIENT_DATES/AMOUNTS/PENALTIES 正确拒绝 |
| 4 | 正确文书通过 | ✅ PASS | 泽达两份处罚书通过全部检查 |
| 5 | 请求清单模型分布 | ✅ PASS | glm53=8, glm53flash=15, 总计 23 ✓ |
| 6 | Token 上限 114K | ✅ 验证 | Meter max_guaranteed_actual=114000 |
| 7 | 现金硬顶 ¥0 | ✅ 验证 | 无按量模型 |
| 8 | 评分器独立性 | ✅ 验证 | 零额外模型调用；参考来自冻结处罚书文本 |
| 9 | 无运行进程 | ✅ 验证 | 之前检测到的 1 个进程为检查脚本自身（含 "v76"），已消散 |
| 10 | 新批次目录干净 | ✅ 验证 | 空 |

## 最终七字段配置

```json
{
  "batch_name": "dd_v76_n5_paired_v2",
  "max_calls": 23,
  "max_tokens": 114000,
  "per_model_quota": {
    "glm53": {"calls": 8, "tokens": 45000},
    "glm53flash": {"calls": 15, "tokens": 69000}
  },
  "max_cash": 0,
  "allowed_models": ["glm53", "glm53flash"],
  "tasks": ["D_r1-n5-IB-vs-Alt-2rep-v2-correct-evidence"]
}
```

## 启动命令（待授权后执行）

```bash
cd /root/cap_eval_bench_v1 && nohup python3 dd_v76_runner.py --authorize \
  --out dd_v76_n5_paired_v2 > /tmp/v76.log 2>&1 &
```

**ALL CHECKS PASS — 等待操作者明确授权。付费 HOLD 维持。**
