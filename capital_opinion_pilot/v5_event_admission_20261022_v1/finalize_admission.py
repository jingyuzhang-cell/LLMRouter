import pathlib,json,hashlib,csv,datetime
b=pathlib.Path(__file__).resolve().parent
p=b/'EVENT_ADMISSION.json';d=json.loads(p.read_text())
for r in d['candidates']:
 if r['issuer']=='海康威视':
  r['development_hit_adjudication']={'classification':'FALSE_POSITIVE_NUMERIC_SUBSTRING','path':'/root/r3_own_pool/pilot_matrix.csv','line':337,'reason':'002415 matched inside decimal 0.00241584; no issuer/event identity match'}
  r['development_exposure']='NO_IDENTITY_HIT_IN_SCOPED_SEARCH_NOT_CERTIFIED_UNSEEN'
 if r['issuer']=='科沃斯':
  r['report']='2024年度募集资金年度存放与使用情况鉴证报告（含公司专项说明）'
  r['parse_warning']='MuPDF emitted cannot find XObject resource n3 warnings; page extraction completed, visual fidelity not certified; visual review required before acceptance.'
p.write_text(json.dumps(d,ensure_ascii=False,indent=2))
rows=d['candidates'];s=[]
s.append('# V5/RL 独立事件逐项准入表\n\n状态：**8个公开来源候选已登记；正式准入0/8；真实执行NO-GO。**\n\n本轮仅做公开原文取证、开发记录限定检索和准入分类。不是已冻结的独立检验事件清单，也没有生成正式Gold。V5、RL及12个公共模块哈希与上一轮冻结值一致；无模型调用、GPU、算法修改或测试重跑。\n')
s.append('|候选ID / 公司|公开文件日期 / 页数|原文及页码索引|开发暴露核查|终端参考 / 判定|\n|---|---|---|---|---|')
for r in rows:
 s.append(f"|{r['event_id']} / {r['issuer']}|{r['source_date_from_disclosure_path']} / {r.get('pdf_pages','?')}页|[PDF]({r.get('raw_path','')}) · [页码索引]({r.get('candidate_evidence_index','')})|限定检索未发现身份匹配；独立性未认证|没有已确认终端参考；**NO-GO**|")
s.append('''
## 每个事件实际缺什么

上述8行分别在 EVENT_ADMISSION.json 中记录完整URL、抓取时间、原PDF SHA256、拟考察维度、曝光检索命中、缺失字段和判定；CSV提供简表。没有用空白“未来事件”凑数，但候选数量8也不等于合格样本8。

1. **独立性**：已查既有候选注册与公开报告，未重用康得新、舜天、欧菲光、宏景、上实或旧20事件池。检索仅覆盖指定项目的开发代码/报告/CSV，避开密封、保留测试、eval、原始响应和复制回归沙箱。来源索引记录实际扫描文件及哈希。完整历史暴露、关联发行人/事件簇及人员知情情况仍未确认；未命中不能升级成独立性PASS。海康代码002415在0.00241584内的命中已明确排除，原命中记录保留。
2. **真实任务与评分**：每行提出的是候选核对方向，不是冻结题目；没有确认必要事实集合、证据跨度、评分分母、关系规则或完整终端Gold。页码关键词索引只能定位材料，不能代替事实核验。不能把数值可提取/来源页齐全解释成完整终端Q可评分。
3. **自然依赖与动作价值**：报告篇幅和财务表数量不能证明任务天然需要多分支DAG。当前没有实际DAG、状态、合法动作效果或运行反馈价值证据；不强拆报告，也不承诺8份材料都会成为合适的联合优化任务。
4. **配对与预算**：输入、缓存/合同版本、能力表、反馈、预算和截止期的同状态配对包尚不存在。当前不能将112当作实际所需请求量；没有当前费率及可执行现金上限，付费执行继续HOLD。本轮没有读取密钥、调用模型端点或核价后擅自发送。

## 来源边界与质量异常

原PDF全部实际保存，具体源URL见JSON；使用披露URL中的日期作为来源日期，尚未对每个日期的董事会日、报告日、披露日语义做正式裁决。首张PDF页包含相应公司简称，不代表报告内所有数据已核验。

科沃斯原件首页实为“募集资金年度存放与使用情况鉴证报告”，不是简单沿用搜索摘要的专项报告标题；登记已按原件修正。MuPDF抽取时出现 `cannot find XObject resource n3` 警告，13页抽取完成，但视觉元素完整性未验收，不能声称原文处理无缺陷。其余材料同样仅完成下载/文本页索引，不声称所有表格视觉语义均已确认。

此次新发现/阅读本身也登记为任务准入接触。后续不得把这些材料宣称完全未被准备者看过；允许的预结果材料建设与算法调参必须分别记录。不得据这些候选改算法后再称其为未见确认集。

## 准入规则与后续边界

仅当8个真实事件逐一具备：历史开发曝光清关、自然依赖与状态决策空间、独立确认的限定终端参考及评分规则，才能冻结正式事件清单。未知项不填Gold、不自动给0、不用代理事实数代替准确率。对候选的淘汰/替换只能依据预结果准入原因，并保留记录；不能按V5是否胜出选择事件。

本轮完成用户要求的逐事件准入表，**没有完成8个事件的正式准入**。下一步必须补上述事实/任务资格；不能继续到真实配对。现阶段没有足以申请付费执行的任务集合，也不应以自动检查代替独立参考确认。未发起真实实验、未启动QS/Router、未修改历史冻结工件或ZCODE。
''')
(b/'EVENT_ADMISSION.md').write_text('\n'.join(s))
with (b/'EVENT_ADMISSION.csv').open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['event_id','issuer','source_date','PDF','pages','development_exposure','terminal_reference','terminal_Q_formula','decision'])
 for r in rows:w.writerow([r['event_id'],r['issuer'],r['source_date_from_disclosure_path'],r.get('raw_path'),r.get('pdf_pages'),r['development_exposure'],r['independent_gold_status'],'UNKNOWN_NOT_DEFINED',r['decision']])
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
assert all(sha(p)==h for p,h in d['algorithm_sha256'].items())
manifest={'date':'2026-10-22 Asia/Shanghai','status':'8_SCREENED_0_ADMITTED_EXECUTION_NO_GO','algorithms_unchanged':True,'model_api_calls':0,'public_pdf_downloads':8,'artifacts':{str(p.relative_to(b)):sha(p) for p in sorted(b.rglob('*')) if p.is_file() and p.name!='MANIFEST.json'}}
(b/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps({'candidates':len(rows),'admitted':0,'pdf_pages':sum(r.get('pdf_pages',0) for r in rows),'algorithms_unchanged':True,'report':str(b/'EVENT_ADMISSION.md')},ensure_ascii=False))
