"""Post-hoc non-independent source-bound diagnosis. Does not alter frozen scores."""
import json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parent
P=Path('/root/research_outputs/DYNAMIC_PI_FIXED_CALIBRATION_INPUTS')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def response(cell,node):
 p=R/'requests'/f'{cell}__{node}'/'RESPONSE.bin'
 text=json.loads(p.read_bytes())['choices'][0]['message']['content']
 # Inspection only: retain trailing bytes and original failure. Never submit decoded prefix.
 obj,end=json.JSONDecoder().raw_decode(text)
 return p,obj,text[end:]
def input_anchor(node,kind,id):
 p=P/(node+'.json');obj=json.loads(p.read_text())['input']
 x=next(x for x in obj[kind] if x['id']==id)
 return dict(file=str(p),file_sha256=sha(p),item_id=id,source_text=x.get('text',x.get('statement')))
issues=[]
def add(cell,node,item,category,explanation,anchors):
 p,o,trailing=response(cell,node)
 if item=='report':quote=o['report']['text']
 else:quote=next(x['statement'] for x in o['findings'] if x['id']==item)
 issues.append(dict(cell=cell,node=node,item=item,category=category,output_quote=quote,
   response_file=str(p),response_sha256=sha(p),evidence=anchors,explanation=explanation,
   review_level='POST_HOC_ASSISTANT_NONINDEPENDENT_DIAGNOSIS',formal_Q=None,
   original_verdict_unchanged=True))
add(0,'timeline_1','timeline_1:f1','UNSUPPORTED_RELATION_ASSERTION',
 '时间先后有依据；两项独立交易的强断言超出给定材料，不能把缺少直接关系披露推为已证实独立。',
 [input_anchor('timeline_1','claims','extract_1:c10')])
add(2,'relations_1','relations_1:f3','DATE_TYPE_CONFLATION',
 '关系节点把9月5日公告日期写为董事会审议日期；给该节点的c4没有会议日期。核验节点确实拿到原始第2页，其中会议日期是9月3日。',
 [input_anchor('relations_1','claims','extract_1:c4'),input_anchor('relations_1','claims','extract_1:c6'),input_anchor('verify_1','evidence','SUPCON_CAPITAL:2:0')])
add(4,'verify_1','verify_1:v11','UNKNOWN_PROMOTED_TO_NEGATIVE_FACT',
 '输入只说未载明截至截止日是否完成，输出却说增资尚未完成并据此推导年报未体现财务影响。两个判断都不能由这些引文确证。',
 [input_anchor('verify_1','claims','extract_1:c9'),input_anchor('verify_1','claims','extract_1:c8')])
add(4,'verify_1','verify_1:v10','UNSUPPORTED_INDEPENDENCE',
 '没有材料证明交易安排关系，不等于法律主体与审批路径均独立；这句话需要额外证据，不能由收购成本与增资资本处理方式推出。',
 [input_anchor('verify_1','claims','extract_1:c10')])
add(6,'report_1','report','CONTRACT_PASS_NOT_SEMANTIC_PASS',
 '报告虽合同通过，开头将两项安排表述为独立资本运作，但同段又承认具体安排关系未载明。存在过强结论，应保留未决而不是认定独立。',
 [input_anchor('report_1','findings','timeline_1:f8')])
result={'scope':'Targeted review of actual responses; not exhaustive accuracy scoring',
 'issues':issues,'all_formal_Q':'UNKNOWN','gold_adjudication':'NOT_PERFORMED',
 'counterexample_to_overdiagnosis':{'cell':4,'item':'verify_1:v4','finding':'9月3日会议日期在实际输入SUPCON_CAPITAL:2:0中存在，不应误判为幻觉；该项的引用精确性另行区分。'},
 'deepseek':'No specific comparable overclaim selected in this targeted review; this is not a full correctness or completeness verdict.',
 'allocation_implication':'Failed Qwen latencies are not successful completion predictions. The report contract has two successful observations, but no independently established Q. Cannot claim Dynamic-Pi net benefit.'}
(R/'CONTENT_DIAGNOSIS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print('diagnostic_items',len(issues))
