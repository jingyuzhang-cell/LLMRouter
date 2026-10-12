# 可选角色分组Goal IR零调用实现

新增goal_ir_roles.py：role_schema、normalize_role_ir。generation.py新增goal_input_mode='roles'选项，仅用于planning_mode='goal_ir'，默认flat保留。原Prompt、严格Schema、有限修复、原符号编译器、合同装配、结构校验、语义审查、TypedExecutor及MeteredExecutor链继续使用。无新执行器或搜索入口。

inputs按操作角色分组：extract={}；form_expression={facts:[typed symbols]}；calculate与verify_expression={facts:[typed symbols],expression:[one typed symbol]}；verify_value={value:[one typed symbol]}。必需键、非空列表、角色类型由Schema约束；无额外键。程序仅展开显式声明，原编译器继续验证唯一生产者、单位、环、最终目标与连通性。没有猜测生产者、补符号、补边或删除必要分支。

8项新增测试，287typed+18固定入口=305/305通过。多根、前向引用、输入顺序、3/5节点、旧flat兼容、未知生产者拒绝、历史run02/03/04重放，以及角色模式生成→原装配→原语义审查Stub→原执行器→账本均通过。Stub案例不能计入真实成功率。实际vLLM0.11.0/xgrammar0.1.19新Schema离线编译通过。

历史失败候选分组是显式输入归类的内存诊断，不修改原候选、不生成合法替代图。新增源码导致旧run04入口哈希失效，仅旧结果证据保留。新增协议尚未在真实HTTP上验证。A缺必要表来源属于语义问题，依旧不能由角色合法推导来源完整；需原语义审查与最终执行验证。

未加载模型、未真实请求、未修改固定48配置、冻结数据或评分；未提交推送。下一步离线冻结新诊断版本、实际Tokenizer包络及模型绑定，再取得独立真实调用授权。此阶段不启动正式四题，不宣称优于flat方案。
