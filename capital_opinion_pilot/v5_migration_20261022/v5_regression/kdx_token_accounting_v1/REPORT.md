# 最小推理Token计量验证准备

TOKEN ACCOUNTING READY / REAL INFERENCE NOT AUTHORIZED。

独立输入：system“ You are a concise assistant.”（实际字面以INPUT.json为准），user“Reply with OK.”。不含康得新资料、Gold或t2输入。相同本地Qwen2.5-7B Tokenizer apply_chat_template渲染一次，共23个完整输入Token；最大输出8，单请求完整预留31。冻结REQUEST.json直接发送整数prompt至/v1/completions，add_special_tokens=false、n=1、stream=false、echo=false、return_token_ids=true。不得重新渲染、截断或发送chat请求。HTTP头与JSON字段不属于模型Prompt；不声称所有网络字节均计为模型Token。

本地vLLM0.11.0 protocol.py CompletionRequest支持list[int]及return_token_ids；serving_completion.py非流式响应570–579行返回prompt_token_ids、token_ids，以len(prompt_token_ids)及len(output.token_ids)建立usage。已冻结实际部署源码哈希。运行时仍须验证服务模型及返回字段，不能以离线源码代替真实请求结果。

对照：提交ID序列与服务端choices[0].prompt_token_ids逐项相等；usage.prompt_tokens=23；usage.completion_tokens=len(choices[0].token_ids)<=8；total_tokens为两者之和。禁止通过重新encode输出文本替代真实输出ID计数（EOS/特殊Token可能不出现在文本中）。缺失输入ID仅COUNT_ONLY，缺失usage保留31并失败。所有ID仍为服务端报告，不能独立证明GPU内部执行序列或Tokenizer全部行为。

资源建议：独立1请求、31Token占额、300秒完整墙钟；加载及非生成健康240秒、推理10秒、清理10秒、余量40秒。请求前必须同时满足剩余Token与请求次数、剩余墙钟至少请求10秒+清理10秒+必要余量。所有POST经StrictMeter先fsync完整预留；超时、断开、未知usage保留31，无重试。生命周期复用已通过真实预检的模型命令、协作锁、RESOURCE_QUARANTINED、独立watchdog及持锁GPU退出确认。驱动异常绝对截止不可保证；失败隔离且不清理其他进程。

真实服务配置与权重/Tokenizer身份沿用PASS_METADATA_ONLY实验；非生成健康与身份检查不占模型生成请求。该预检不能代替本次计量验证。新运行目录需原子创建，缓存/账本独立；新协调窗口与真实推理授权尚未获得。

测试：115/115零调用通过（原105+10），新增ID一致、缺失输入回显、序列错位、usage缺失/错误、输出越界、无包装、非法输入、缺失输出ID、身份错误；原严格预算、超时、重复派发和生命周期测试保留。未加载模型或调用真实HTTP。Tokenizer加载时libgomp提示现有OMP_NUM_THREADS值非法，但离线测量正常完成，未改变系统环境。

仅验证计量，不评分回复内容，不执行t2/DAG、不改历史账本。准备到此停止，须独立批准上述信封后才能发送一次推理请求。
