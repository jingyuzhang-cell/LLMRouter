# Stage D 192 执行启动清单（A 方案：等订阅配额恢复）

**决策**：操作者 2026-11-02 选 **A**——等订阅套餐周/月额度恢复，保留全部冻结语义；标准 API 资源包（19.8M glm-5.3 + 50M glm-5.3-flash）**不用于本次协议**。

**配额恢复时刻**：`2026-11-05 16:36:32`（订阅端点服务端返回的原文）。

---

## 0. 启动前置（每次都要重做，不可跳过）

```bash
# 0.1 受控单次预检（极小 token；失败即停，不连续重试、不换模型、不改端点）
cd /root/capital_opinion_pilot && set -a && source /root/.env && set +a && python3 -c "
import transport
r = transport.call_model('glm53flash', system='只输出JSON。', user='{\"ok\":true}',
                         max_tokens=10, timeout_s=30, temperature=0)
print('GLM 预检 OK', r['lat'], 's')"
```
- [ ] 预检 OK
- [ ] `ps aux | grep -E "st_v1|cap_eval"` 为空（无并行 GLM 消费者）
- [ ] 复核执行器哈希：`sha256sum stage_d_executor.py` ==
      `ef50527e2920b42dd51ffec23e8a9f725a54889bc1033204ee517f8bc8f4c9c2`
      （与 `archive_freeze_ef50527e/stage_d_executor.py` 逐字节一致）
- [ ] `runs_final/` 不存在或为空

## 1. 启动命令（唯一正确形式）

```bash
cd /root/research_outputs/static_pi/stage_d
set -a && source /root/.env && set +a
STAGE_D_REAL_CALLS_AUTHORIZED=1 \
nohup python3 stage_d_executor.py run --real --out runs_final \
  > stage_d_real_run.log 2>&1 &
```

**为什么是这些参数**：
- `--real`：真实 transport（`STAGE_D_REAL_CALLS_AUTHORIZED=1` 是硬闸，缺则拒绝）
- `--out runs_final`：不得用配置默认的 `runs_final_dryrun`（那是 mock 目录）
- 时钟：`make_clock(real=True, …)` → **scale=1.0**（1 真实秒 = 1 虚拟秒）

## 2. 硬上限（配置冻结值，执行器内强制）

| 项 | 上限 |
|---|---|
| 执行次数 | 192（6 臂 × 32） |
| 单执行调用 | 14 |
| 全局调用 | 2,688 |
| 全局费用 | ¥34.56（核算口径） |
| 全局 token | 9,500,000 |
| 截止期 | S0–S4 = 180s；**S5 = 90s** |
| 资源槽 | K_glm=2, K_ds=1 |

## 3. 执行中监控

```bash
tail -f stage_d_real_run.log
ls runs_final/*.json 2>/dev/null | wc -l     # 进度（每执行一记录）
cat runs_final/state/GLOBAL_BUDGET.json       # 实时预算
```
- **不要**并发发起其他 GLM 请求（会污染时延与配额）
- 中断可续：`RunStore.completed()` 按记录存在跳过，已计成本持久化不重复计费

## 4. 执行后（必做）

```bash
python3 stage_d_executor.py build-analysis-input --out runs_final   # → FINAL_RUNS.json
python3 stage_d_final_analysis.py runs_final/FINAL_RUNS.json runs_final/ANALYSIS.json
```
- 分析入口**必须** `from exact_perm import exact_paired_perm`（禁 scipy 作正式 p 值）
- 判定措辞按冻结三条分支：0 倒退=通过 / 1=混合结果（**不得**写"全部确认条件通过"）/ ≥2=不通过
- 报告纪律：**COMPLETE 191/192 口径**、两条 S5 边界差异保留、Makespan 为 S5 主要指标、按时率仅辅助

## 5. 已知边界（随报告一起披露，不得省略）

1. 主检验功效 **0.7719**（整数化、NSIM=20000×3 种子），**<80%，中等功效**
2. L2 联合（主检验∩族门禁）**0.7717**，功效损失 **0.00025**
3. S3 单族功效 **0.1818**——**合并通过不得写成 S3 单独统计确认**
4. S5 为**方向性证据**，不作确认性时延结论；89.9s 为压力测试预测非实测
5. 符号翻转检验的对称性为**假设**；HL/bootstrap CI/LOO 仅为旁证
6. 不宣称 Q/C/L 全局最优

## 6. 若配额未恢复（11-05 16:36 之后仍 429）

1. 记录 429 原文（含 code 与重置时间）
2. **停止**，不做连续重试、不换端点、不换模型
3. 提交 BLOCKED 报告，等操作者裁决（可选项：标准 API 重做计时模型 = 新预注册）
