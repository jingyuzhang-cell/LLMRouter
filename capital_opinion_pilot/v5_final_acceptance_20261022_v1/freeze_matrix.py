"""Freeze synthetic states BEFORE acceptance execution; never calls a model."""
import sys,json,hashlib,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_final_acceptance import fixture
import feedback_detector as detector
from cache_lineage import fingerprint
OUT=Path(__file__).parent


def encode(value):
    if isinstance(value,dict):
        if any(not isinstance(k,str) for k in value):
            return {'__items__':[[encode(k),encode(v)] for k,v in sorted(value.items(),key=lambda kv:str(kv[0]))]}
        return {k:encode(v) for k,v in sorted(value.items())}
    if isinstance(value,set):return {'__set__':sorted(value)}
    if isinstance(value,tuple):return {'__tuple__':[encode(v) for v in value]}
    if isinstance(value,list):return [encode(v) for v in value]
    return value


def decode(value):
    if isinstance(value,list):return [decode(v) for v in value]
    if isinstance(value,dict):
        if '__items__' in value:return {decode(k):decode(v) for k,v in value['__items__']}
        if '__set__' in value:return set(value['__set__'])
        if '__tuple__' in value:return tuple(decode(v) for v in value['__tuple__'])
        return {k:decode(v) for k,v in value.items()}
    return value


def base():
    s=fixture();s['feedback']={};s['feedback_records']=detector.detect({'a':'not-json'}, {'a':'公开材料：a=2'}, {'a':'extract'})
    return s,{'a':999,'b':3,'join':1002,'out':2004}


def build():
    cases=[]
    def add(id_,dimension,s,outputs,inputs=None):
        cases.append({'id':id_,'dimension':dimension,'source_class':'SYNTHETIC_TEST',
                      'state':encode(s),'outputs':outputs,'detector_inputs':inputs,
                      'quality_reference':{'kind':'SYNTHETIC_TERMINAL_EXACT_MATCH','expected_out':10,
                       'source_facts':{'a':2,'b':3},'formula':'2 * (a+b)',
                       'independent_real_gold':False}})
    s,outs=base();s.update(feedback_records=[],missing_outputs=[],cache_model={'a':'cheap','b':'cheap','out':'cheap'})
    add('S00','全部缓存健康／NONE',s,{'a':2,'b':3,'join':5,'out':10})
    s,outs=base();add('S01','上游输出合同失效',s,outs,{'a':'not-json'})
    s,outs=base();s.update(missing_outputs=['join'],cache_model={'a':'cheap','b':'cheap','out':'cheap'},
        feedback_records=detector.detect({'join':'not-json'},{},{'join':'tool'}))
    add('S02','汇合节点自身失效',s,{'a':2,'b':3,'join':999,'out':1998},{'join':'not-json'})
    s,outs=base();old=fingerprint({'source':'b_v1'});new=fingerprint({'source':'b_v2'})
    s.update(missing_outputs=[],feedback_records=[],cache_model={'a':'cheap','b':'cheap','out':'cheap'},
             lineage_valid={'b':old==new},cache_fingerprints={'b':{'stored':old,'current':new}})
    add('S03','独立分支缓存指纹异常',s,{'a':2,'b':30,'join':32,'out':64})
    s,outs=base();s['availability']={'fast':False};add('S04','模型不可用',s,outs)
    s,outs=base();s['token_budget_remaining']=20;add('S05','Token预算紧张但可行',s,outs)
    s,outs=base();s['token_budget_remaining']=19;add('S06','Token预算不足／拒绝',s,outs)
    s,outs=base();s['deadline_remaining_s']=3;add('S07','截止期紧张但可行',s,outs)
    s,outs=base();s['deadline_remaining_s']=1;add('S08','截止期不足／拒绝',s,outs)
    s,outs=base();s['terminal_q_min']=.8;add('S09','质量未知且要求终端质量下限',s,outs)
    s,outs=base();text='官方证据原文：b等于三，数值口径保持一致。'
    raw=json.dumps({'facts':[{'quote':'b等于三，数值口径保持一致'},{'quote':'不存在的句子甲甲甲甲'},{'quote':'不存在的句子乙乙乙乙'}]},ensure_ascii=False)
    s['feedback_records']=detector.detect({'a':'not-json','b':raw},{'a':'公开材料a=2','b':text},{'a':'extract','b':'extract'})
    add('S10','有依据的缓存怀疑／扩大范围候选',s,outs,{'raw_b':raw,'pack_b':text})
    s,outs=base();raw=json.dumps({'verdicts':[{'fact':'b引用待核验','verdict':'UNRESOLVED','doc_id':'SYN:E_B'}]},ensure_ascii=False)
    records=detector.detect({'verify_source':raw},{},{'verify_source':'verify'})
    for r in records:r.update(target='b',evidence_ref='SYN:'+hashlib.sha256(raw.encode()).hexdigest())
    s.update(missing_outputs=[],feedback_records=records,cache_model={'a':'cheap','b':'cheap','out':'cheap'},verification_required=['b'])
    add('S11','有证据VERIFY，不改变健康缓存',s,{'a':2,'b':3,'join':5,'out':10},{'raw_verdict':raw,'target_link':{'verify_source':'b'}})
    s,outs=base();s.pop('feedback_records');s.update(missing_outputs=[],feedback={'verify_targets':['b']},verification_required=['b'],cache_model={'a':'cheap','b':'cheap','out':'cheap'})
    add('S12','无冲突依据的VERIFY请求／拒绝',s,{'a':2,'b':3,'join':5,'out':10})
    return {'version':'final_matrix_v1','source_class':'SYNTHETIC_TEST_ONLY','cases':cases,
            'comparison':{'shared':'prepared state, detector, capabilities, constraints, meter and final fixture',
                          'quality_scope':'no calibrated real-model terminal prediction',
                          'benefit_rule':'no real benefit claim; synthetic Q-known pairs report cost/latency tradeoffs only',
                          'no_post_result_parameter_changes':True}}


if __name__=='__main__':
    data=build();path=OUT/'SCENARIO_MATRIX.json'
    with path.open('x') as f:json.dump(data,f,ensure_ascii=False,indent=2)
    names=['joint_scheduler_v5.py','scheduler_common.py','rule_scheduler_rl.py','v5_executor.py','task_quality.py','feedback_detector.py','cache_lineage.py','test_v5_migration.py']
    code={str(OUT.parent/n):hashlib.sha256((OUT.parent/n).read_bytes()).hexdigest() for n in names}
    code[str(OUT/'test_final_acceptance.py')]=hashlib.sha256((OUT/'test_final_acceptance.py').read_bytes()).hexdigest()
    freeze={'matrix_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'code_sha256':code,'case_count':len(data['cases']),'executed':False}
    with (OUT/'MATRIX_FREEZE.json').open('x') as f:json.dump(freeze,f,ensure_ascii=False,indent=2)
    print('Frozen scenarios',len(data['cases']),freeze['matrix_sha256'])
