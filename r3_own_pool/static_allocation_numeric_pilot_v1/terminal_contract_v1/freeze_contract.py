"""Freeze bounded terminal scoring; does not read model outputs or dispatch."""
import hashlib
import json
from pathlib import Path

ROOT=Path('/root/r3_own_pool')
OUT=Path(__file__).resolve().parent
PILOT=OUT.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
binding=json.loads((PILOT/'BINDING.json').read_text())
for path,identity in binding['source_hashes'].items():
    assert sha(Path(path))==identity, f'Frozen source changed: {path}'
task=binding['task'];catalog=task['evidence_catalog']
ref_path=ROOT/'qs_candidate_readiness_v1/eval_only/NUMERIC_REFERENCES.json'
ref=json.loads(ref_path.read_text())['QSDEV_OFG_FLOW_BALANCE__NUMERIC_SCOPE_V1']
assert {i['item_id'] for i in ref['items']}=={s['slot_id'] for s in task['slots']}
proof_checks=[]
for item in ref['items']:
    for proof in item['proofs']:
        spans=[e for e in catalog.values() if e['source_id']==proof['doc_id'] and e['page']==proof['page'] and e['source_sha256']==proof['raw_sha256']]
        chars={}
        for e in spans:
            assert len(e['exact_text'])==e['end']-e['start']
            for j,c in enumerate(e['exact_text'],e['start']):
                assert j not in chars or chars[j]==c
                chars[j]=c
        covered=all(j in chars for j in range(proof['start'],proof['end']))
        literal=covered and ''.join(chars[j] for j in range(proof['start'],proof['end']))==proof['quote']
        proof_checks.append({'item_id':item['item_id'],'doc_id':proof['doc_id'],
                             'page':proof['page'],'start':proof['start'],'end':proof['end'],
                             'literal_and_hash_identity':literal})
assert all(p['literal_and_hash_identity'] for p in proof_checks)
contract={
    'id':'STATIC_ALLOCATION_NUMERIC_TERMINAL_CONTRACT_V1',
    'scope':'Six fixed numerical propositions only; not complete opinion analysis.',
    'final_question':task['question'],'task_id':task['task_id'],
    'development_exposure':True,'independent_confirmation_set':False,
    'information_cutoff':task['cutoff'],
    'cutoff_policy':'Only immutable task evidence catalogue; no retrieval or later evidence. Actual source publication-time adjudication is not separately certified by this contract.',
    'necessary_deliverables':task['slots'],'assigned_slots':binding['assigned_slots'],
    'reference':ref,'reference_grade':ref['verification_method'],
    'human_independent_review':False,
    'output_schema_path':str(ROOT/'ab_bounded_numeric_v1/OUTPUT_SCHEMA.json'),
    'original_scorer_path':str(ROOT/'ab_bounded_numeric_v1/score_terminal.py'),
    'content_metric':{'name':'Q_numeric_conditioned','formula':'2*TP/(2*TP+FP+FN), original frozen numeric scorer; not TP/6 accuracy.',
        'denominator':'Variable F1 denominator; the reference contains exactly six required items.',
        'null':'Explicit abstention follows original MISSING semantics, not a guessed answer.',
        'omission':'Absent declared slot is MISSING/FN, whereas unresolved interpretation is UNKNOWN.',
        'unknown':'Preserve original null Q and UNSCORABLE reason; no zero imputation.',
        'extras':'Original scorer extra/unknown policy unchanged; strict delivery rejects foreign IDs.',
        'duplicates':'Original content deduplication unchanged; strict delivery rejects duplicate IDs.'},
    'delivery_metric':{'name':'legal_correct_targets_over_six','denominator':6,
        'formula':'Count MATCH rows from branches passing numeric-lane contract / 6.',
        'missing_branch':'Contributes no legally delivered targets; separate content score may remain UNKNOWN.',
        'not_same_as_content_quality':True},
    'numeric_lane_contract':['Native object schema, no parse repair.','Exact assigned item-ID set, once each.',
        'Evidence IDs resolve within immutable catalogue; full evidence support evaluated separately.',
        'No dependency on Gold values in delivery acceptance.'],
    'evidence_metrics':{'citation_ID_validity':'Valid catalogue IDs / all cited IDs; no citations => UNKNOWN.',
        'source_proof_coverage_proxy':'Original source proof span coverage; not full semantic citation correctness.',
        'citation_semantic_accuracy':None,'reason':'No independent full entailment adjudication beyond bounded numerical source reference.'},
    'merge':'Deterministically concatenate complete raw rows in fixed branch order; never fill Gold, repair values, omit wrong rows or deduplicate.',
    'unscorable_dimensions':['full_opinion_Q','causality','stance','risk_conclusions','full_semantic_contract_success','full_evidence_entailment_accuracy'],
    'source_checks':proof_checks,'source_hashes':binding['source_hashes'],
    'binding_sha256':sha(PILOT/'BINDING.json'),
    'experiment_success_not_certified':True,'paid_execution_authorized':False}
dest=OUT/'TERMINAL_SCORING_CONTRACT.json'
assert not dest.exists(), 'Refuse overwrite'
dest.write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n')
lines=['# 限定数值任务终端评分契约','','只冻结当前一个开发任务的完整限定交付，不扩充10任务机器参考，不重新裁决旧响应。', '',
       '## 最终交付','','2023、2024、2025年度向新思考采购产品和服务发生额，以及对应年末应付账款余额，共6项，单位万元。主体、交易对手、期间与角色由给定slot固定。两个分支分别提交三项，确定性汇合；禁止混用发生额和余额。', '',
       f"信息截止点：`{task['cutoff']}`；仅使用冻结目录。对原参考的24处证明跨度逐项检查，原文字符位置与来源哈希均一致。此为6项×4条依据，并非24个独立事实。", '',
       '## 必须分列的指标','','|指标|含义|','|---|---|',
       '|Q_numeric_conditioned|原冻结评分器的事实行F1：2TP/(2TP+FP+FN)，不是数值准确率|',
       '|合法正确交付覆盖|通过限定数值通道合同的正确目标数/6；与内容Q分列|',
       '|原生Schema|原始输出格式合法；不自动包数组|',
       '|限定通道合同|精确slot集合、无重复/越权slot、证据ID有效；不是完整舆情语义合同|',
       '|证据|引用ID有效率、原有跨度覆盖proxy；语义引用正确率未认证|',
       '|完整舆情Q|UNSCORABLE，不能从六数值推导|','',
       '遗漏/明确弃答按原参考的MISSING处理；无法解释的主张保留UNKNOWN及null Q。不更改冻结F1分母，不把失败响应隐性记为准确率0。合法交付覆盖单独反映未能交付的目标。','',
       '## 证据与结论边界','','参考来自已验收的确定性原文核对，不是双人盲评。当前事件已参与开发，不是独立确认集。合同测试通过只能说明评分入口符合契约，不能宣布模型分配或端到端收益成立。','',
       '同图、同Prompt、同来源、同资源约束的比较方案保持原BINDING；统计上只有一个事件，两次重复不是两个独立事件。当前实验只能检验探索性信号。独立复核之前第1步总体仍未通过。','',
       '付费执行仍关闭；预算上界、实际计费权益与新批次授权未齐备。']
(OUT/'TERMINAL_SCORING_CONTRACT.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'reference_items':len(ref['items']),'literal_proof_checks':len(proof_checks),'all_pass':True,'full_opinion_Q':None,'api_calls':0}))
