# P2: π真实模型重分配最小设计 V0(草案,待窗口+驾驶舱批准)
背景: MX实验证实恢复策略条件化(recovery_policy_divergence 12/12),但pi_model_assignment_divergence=N/A
——384次确认性实验必须包含真实π维度,否则论文的"Z/R/π联合调度"缺一角。

## 触发规则(最小,不改冻结随机化/统计)
恢复调用时,若注入节点原分配模型为M,则恢复调用以概率性规则切换到异构备用模型M':
  1. S4(格式破坏): 格式修复属轻任务 → 切换到低时延模型(deepseek-chat修复glm输出,或反之)
  2. S3(截断/内容缺失): 重建属重任务 → 切换到备用强模型(glm-air优先,预算护栏内)
  3. 同模型二次恢复失败 → 强制切换(硬规则)
选择依据: MX数据显示FC超时4次均因恢复调用过慢——π切换直接作用于已证实的时延瓶颈。

## 留痕(复用decision_log)
pi.changes = [{"node": X, "from": M, "to": M', "reason": "S4_light_task|S3_heavy_task|second_failure"}]
pi_model_assignment_divergence = 实际发生from→to变化的决策点占比(替换现有policy标签口径)

## 实验纪律
- FC的π保持固定(对照定义不变)
- 模型池不扩容: glm-5.3-flash / glm-air(如预算允许) / deepseek-chat
- 预算影响: 备用模型单价差已计入¥12上限校验
- 先在MX2/MX3任务上用≤8次真实调用做π专项冒烟(预计<¥0.15),验证切换逻辑后并入正式执行器
