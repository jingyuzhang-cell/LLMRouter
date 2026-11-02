"""Post-run descriptive analysis only; no regrading, network, or retries."""
import json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parent
P=Path('/root/research_outputs/DYNAMIC_PI_FIXED_CALIBRATION_INPUTS')
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
result=json.loads((R/'RESULT.json').read_text());rows=[]
for original in result['rows']:
 n=original['cell'];req=next((R/'requests').glob(str(n)+'__*/REQUEST.json'))
 acc=json.loads((req.parent/'ACCOUNTING.json').read_text())
 resp=json.loads((req.parent/'RESPONSE.bin').read_text());choice=resp['choices'][0]
 reason=[]
 try:
  parsed=json.loads(choice['message']['content'])
  f=json.loads((P/(original['node']+'.json')).read_text())
  if not isinstance(parsed,dict):reason.append('OUTPUT_NOT_OBJECT')
  elif set(parsed)!=set(f['output_schema']):reason.append('UNEXPECTED_TOP_LEVEL_FIELDS:'+','.join(sorted(set(parsed)-set(f['output_schema']))))
 except (ValueError,TypeError):reason.append('CONTENT_NOT_SINGLE_JSON_OBJECT')
 rows.append(dict(cell=n,node=original['node'],model=original['model'],status=original['status'],
                  original_verdict=original['verdict'],failure_diagnosis=reason,wall_s=acc['wall_s'],
                  input_tokens=acc['usage']['prompt_tokens'],output_tokens=acc['usage']['completion_tokens'],
                  public_price_estimate=acc['public_price_estimate'],actual_cash_settlement=None,
                  request_sha256=h(req),response_sha256=h(req.parent/'RESPONSE.bin'),
                  Q=None,samples=1))
by={}
for row in rows:
 m=by.setdefault(row['model'],dict(calls=0,contract_passes=0,input_tokens=0,output_tokens=0,request_wall_sum_s=0,micro_cny=0,micro_usd=0))
 m['calls']+=1;m['contract_passes']+=row['status']=='CONTRACT_COMMITTED'
 for key in ('input_tokens','output_tokens'):m[key]+=row[key]
 m['request_wall_sum_s']+=row['wall_s']
 for key in ('micro_cny','micro_usd'):m[key]+=row['public_price_estimate'][key]
lock=json.loads((P/'BATCH_LOCK.json').read_text())
unchanged=all(h(Path(path))==digest for path,digest in lock['files'].items())
assert unchanged
analysis=dict(status='CLOSED_COMPLETED_CALIBRATION_ONLY',rows=rows,models=by,
              new_calls=len(rows),completed_static_dynamic_pairs=0,terminal_quality=None,
              dynamic_pi_benefit='NOT_EVALUATED',frozen_files_unchanged=unchanged,
              note='Actual failed-call latency remains observed but is not successful completion latency.')
(R/'ANALYSIS.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2))
lines=['# 独立下游节点校准：真实批次结果','', '**CLOSED：8/8请求完成，无重试、补跑。校准完成；Static/Dynamic配对未启动，算法收益未评价。**','',
'| 节点 | Qwen合同 | Qwen请求耗时(s) | DeepSeek合同 | DeepSeek请求耗时(s) |','|---|---|---:|---|---:|']
for i in range(0,len(rows),2):
 a,b=rows[i:i+2];lines.append(f"| {a['node']} | {a['status']} | {a['wall_s']:.3f} | {b['status']} | {b['wall_s']:.3f} |")
lines += ['', '## 实际计量','']
for model,m in by.items():
 lines.append(f"- {model}：{m['calls']}请求，合同通过{m['contract_passes']}/{m['calls']}；输入{m['input_tokens']}、输出{m['output_tokens']} Token；请求耗时累计{m['request_wall_sum_s']:.3f}秒；估费人民币{m['micro_cny']/1e6:.6f}、美元{m['micro_usd']/1e6:.6f}。")
lines += ['', '总Token 26,350；公开牌价估费¥0.015804和$0.006213，分别低于¥0.20/$0.10程序停止阈值。实际账户结算UNKNOWN。耗时是各独立请求实测墙钟，累计值不是并行DAG Makespan或完整任务时延。','',
'## 失败归因（原始成绩不改判）','',
'- Qwen时间线：一个JSON对象后又附加代码块，严格单JSON解析失败。没有解包、删代码块或自动修补。',
'- Qwen关系：顶层除findings外还返回node_id，违反冻结合同。',
'- Qwen核验：顶层除findings外还返回status，违反冻结合同。',
'- Qwen报告及DeepSeek四节点通过既有结构与引用链检查；这不证明内容语义正确。三个失败也不等于事实内容错误。',
'', '## 已解决与未证明','',
'- 已真实验证：普通模型合同失败后，其他固定输入单元仍继续执行。此前Qwen四类下游缺测现在都有实际请求耗时、usage与输出记录。',
'- Qwen报告节点与DeepSeek报告节点均有合法提交；其他三类Qwen只有失败观测，不能把失败耗时当作合法完成时间。',
'- 这一输入和提示下，DeepSeek四类请求都更快且合同通过；每格仅一个样本，不能估计0.95可靠性或外推总体优势。人民币与美元未换算，不直接断言现金谁更便宜。',
'- 使用历史DeepSeek生成的固定上游输入，存在生成模型风格偏差；不是独立任务，也不是完整上游鲁棒性检验。',
'- 语义Q全部UNKNOWN。不能声称完整终端质量提高、Pareto改善或Dynamic-π有净收益。',
'- 本次新提示不与旧提示混合当作同条件配对，不自动导入冻结调度器，不自动更换任务或追加调用。',
'', '原始请求/响应/计账在requests/，完整输出在CELL_*.json，机器汇总在ANALYSIS.json。冻结代码、配置、输入及历史来源哈希未变，RUN_ONCE.lock保留。所有8次额度已使用，授权结案。']
(R/'BATCH_RESULTS.md').write_text('\n'.join(lines)+'\n')
(R/'CLOSURE.json').write_text(json.dumps({'status':'CLOSED','attempts':8,'remaining_authorized_requests':0,'retry_allowed':False,'supplement_allowed':False,'frozen_files_unchanged':unchanged},indent=2))
print(json.dumps(by,ensure_ascii=False))
