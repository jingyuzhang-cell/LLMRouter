# 六个QS候选任务：最后一道离线评分验收

**结论：6/6题通过本轮声明范围内的离线评分验收；200/200项定向测试通过。**已完成可执行评分器和逐题参考，不新增任务，不重开V1/V2.1，不读取或改写历史模型标签。0真实API、0GPU，未修改ZCODE。下一步仅是独立授权的一次24格区分度Pilot，当前尚未派发。

## 逐题结果

|任务|必要原子数|全正确F1分母|定向测试|内容边界|
|---|---:|---:|---:|---|
|宏景更正增减额|6|12|28/28|3期间×收入/成本的有符号更正后减更正前|
|宏景毛利与推断|10|20|31/31|3期间×前/后/差9项，加收入下降不能推出净利润等额下降1项|
|上实诉请精度|5|10|34/34|精确本金、约数展示、16.29元显示差、舍入相容、诉请非判赔|
|上实诉讼阶段|8|16|40/40|两公告阶段/当事人地位、生效、最终结果、利润不确定性及复合说法|
|欧菲光流量/余额|7|14|32/32|3年度采购流量、3年末应付余额及口径区分|
|欧菲光声明归属|4|8|35/35|公司立场、独董核查决定、输入未给最终结论、外部真伪不能据此确定|

共40个原子，仍只来自3个已见开发事件，不是6个独立事件。上述分母是全正确响应的2TP+FP+FN，不是错误/遗漏/额外断言下的固定分母。

逐题完整规则与必要/非必要项：[TASK_SCORING_RULES.md](qs_task_scoring_acceptance_v1/TASK_SCORING_RULES.md)。原子Gold、主体/期间/角色、单位、原始跨度、明确等价表达与错误边界均在[GOLD_EVAL_ONLY.json](qs_task_scoring_acceptance_v1/GOLD_EVAL_ONLY.json)。来源参考独立于模型输出，但没有声称已经过双人盲标或模型区分度验证。

## 两个缺口怎样落地

跨页单位不再悬空。欧菲光第3页余额表表头给出三个年末及万元；第4页应付账款行保持同列后才进入下一小节。已保存PDF渲染、文字框及3列对齐检查；宏景第1页元单位对应第2页完整财务表。参考证据包含单位、角色、期间、行和发行人身份，不做“最近单位”猜填。223次跨度核验均与冻结解析原文逐字相符，这是包含重复使用的检查次数，不是223个独立事实。

定性命题只评价来源中的归属、程序和范围。独立董事不是上市公司主体的可替换别名；启动调查不是完成核查；公司否认不是外部证实；输入未提供最终结果不是世界上不存在结果。上实的精确金额明确为投资损失诉请本金，另列律师费不混入。这些范围在新题真实响应产生前定义，没有改原任务或历史参考工件。

## 评分器验证了什么

[score.py](qs_task_scoring_acceptance_v1/score.py)输出Q_objective、TP/FP/FN/UNKNOWN、原生Schema、引用身份、参考跨度覆盖proxy和逐项原始证据。全正确、已证明表达变体、币种别名/精确尺度换算可通过；数量、单位、主体、年份、角色、对手、否定及限定范围变化不被规范化掩盖。遗漏、额外错误、重复正确、含糊额外断言、缺必要身份、非法/越权/不支持事实的证据ID、Schema及JSON错误均有测试。

Contract失败不抹内容Q：裸数组质量投影可得到Q，原生Schema和合同仍失败；证据错而内容独立正确可以Q=1。反之无法理解的转述、缺身份、无法解析JSON或未评分额外断言使Q=null，而不是0或强行补全。测试输出均保留于[ADVERSARIAL_FIXTURES_EVAL_ONLY.json](qs_task_scoring_acceptance_v1/ADVERSARIAL_FIXTURES_EVAL_ONLY.json)。

**本验收不是任意自然语言语义裁决器。**等价层是已证明的有限规则，不含通用模糊匹配。超出规则的真实转述仍可能UNKNOWN。这是明确保留的不确定性，不能把200项夹具通过写成“真实四模型必有Q”。本包Contract也仅为独立测量的结构/引用身份检查，不代表原TypedExecutor全部语义守卫已通过；所有结果downstream_release=false。

## 24格下一步已冻结到何种程度

[REQUEST_MATRIX_PLANNED.json](qs_task_scoring_acceptance_v1/REQUEST_MATRIX_PLANNED.json)含24个同题同messages模板，四模型为qwen-flash、qwen-plus、deepseek-flash、glm-5.3。每题四臂Prompt hash相同，Gold/期望对象/测试夹具未放入请求；所有原始来源按固定400字符切成42段，而非按答案挑选证据。顺序seed=20261016。GLM思考low与其他模型关闭思考的配置差异显式保留，不冒充内部计算预算相同。

草案为24请求、每次最大输出4096 Token、总输出98,304；单次180秒、整批5400秒。输入UTF-8字节代理合计421,240，不是Token估计硬上界。价格、实际费用、估费停止阈值尚待下一次独立费用信封确认；不沿用旧授权，也未提供可直接发请求的新真实启动器。D仍UNKNOWN。详见[PILOT_PLAN.md](qs_task_scoring_acceptance_v1/PILOT_PLAN.md)及[PILOT_BUDGET_PENDING_AUTH.json](qs_task_scoring_acceptance_v1/PILOT_BUDGET_PENDING_AUTH.json)。

单格合同/内容/证据失败或UNKNOWN保留并继续；账户、身份、源文件、费用/请求/Token预算、全局截止或系统安全问题全局停止。后续单元不消费本批输出，不训练Router，不运行真实DAG。24格只作天花板、描述性模型×任务差异与已识别Q/C/L选择空间分析；单次观测与3事件不足以确认稳定交互或自动放行QS-1000。

## 冻结与复现

新包：[qs_task_scoring_acceptance_v1](qs_task_scoring_acceptance_v1/)。冻结身份见FREEZE_SHA256.txt，清单覆盖新评分器、测试证据、来源结构证明、任务/请求/Schema与本报告。VERIFY.py只读复算200个反例结果、同题Prompt一致性及新旧身份，不调用API、不重建旧数据。

```bash
python /root/r3_own_pool/qs_task_scoring_acceptance_v1/VERIFY.py
```

**最终状态：TASK_SCORING_READY；真实Pilot尚未执行，待独立费用授权与受限执行绑定。**本轮评分验收到此封存，不继续改旧模型Prompt/Contract，不新增任务或测量轮次。
