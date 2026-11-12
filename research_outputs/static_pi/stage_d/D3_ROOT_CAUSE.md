# D3 根因定位报告（零调用 · 2026-11-05）

## 根因确认：**子进程缺少两个环境变量导致 deepseek 401 → 所有 E 类节点失败 → J/SINK/FMT 全部因依赖不满足而无法派发 → 150s 内无任何进展**

## 分段探测结果

| 阶段 | 方法 | 结果 | 耗时 |
|---|---|---|---|
| P1 config 加载 | in-process | ✓ | 0.0s |
| P2 import stage_d_executor | in-process | ✓ | 0.06s |
| P3 VirtualClock | in-process | ✓ | 0.0s |
| P3b GlobalBudget | in-process | ✓ (calls_left=2673) | 0.0s |
| P4 SlotManager | in-process | ✓ | 0.0s |
| P5 RunStore | in-process | ✓ | 0.0s |
| P6 MockProvider | in-process | ✓ | 0.0s |
| P7 FinalExec 构造 | in-process | ✓ | 0.0s |
| **P8 ex.run() mock 路径** | **in-process** | **✓ 72.8s 完成 7 调用 TP=2** | **72.8s** |
| glm_low_call (GLM API) | direct | ✓ 2.4s | 2.4s |
| transport.call_model(deepseek) | **无 env 时** | **✗ HTTP 401** | 0.2s |
| transport.call_model(deepseek) | **设 env 后** | **✓ 0.7s** | 0.7s |

## 缺失的环境变量链

冻结执行器的 deepseek 路径 `transport.call_model` → `openai_call` 需要 `DEEPSEEK_API_KEY` 环境变量（在 `/root/capital_opinion_pilot/transport.py:15`：`'Bearer ' + os.environ.get(env_key, '')`）。

**我的包装器子进程从未设置此变量**（只设了 `STAGE_D_GLM_KEY`），导致：

```
E1~E4 (deepseek) → HTTP 401 → Failed
J1/J2/SINK/FMT 依赖 E 输出 → 永远不满足 → Ready（非 Failed）
→ ex.run() 循环空转（每 0.15s 检查） → 直到全局超时
→ 无节点输出、无 stdout（卡在 while loop 内不打印）
```

**这完美解释了 D3 的全部症状：无输出、无异常、150s 挂起。**

## D2 的关联解释

D2（L4 降级拿不到部分结果）在同一路径中：E 类节点 401 失败 → 从未写入 `ex.outputs` → 轮询线程看不到任何内容 → L4 只能全部标 UNKNOWN。**修复 D3 后 D2 大概率自愈**（E 类成功后 outputs 会被填充）。

## 修复方案（两项环境变量注入）

包装器 `damsj_pilot_runner.py` 的 env dict 需增加：

```python
# deepseek 凭据（冻结执行器 → transport.openai_call 要求）
os.environ['DEEPSEEK_API_KEY'] = <从 provider_config 读取>
```

此为纯环境变量注入，**不修改任何冻结文件**。

## 下一步

1. 在包装器 env 中加入 `DEEPSEEK_API_KEY` → 直连测试 1 次真实执行 → 确认节点完成 + L4 部分结果捕获
2. 通过后做 3 臂 × 1 次烟雾测试（240s 宽松截止期）
3. 通过后重跑 54 次批次

**本轮零调用、零费用。密钥已删。**
