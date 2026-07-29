from copy import deepcopy
from openclaw_router.experiment_protocol import (
    ANSWER_FORMAT_VERSION,DATA_VERSION,MAX_INPUT_CHARS,PROMPT_TEMPLATE_VERSION,
    build_prompt,objective_score,select_context_pilot,signature,signature_payload,
)
from openclaw_router.scoring import utility

def task(kind="financial_numerical_reasoning",**extra):
    base={"id":"t1","query":"What is the result?","type":"专业问答","dataset":"FinQA","task_type":kind,
          "context":"Revenue was 200 and cost was 100.","table":"| Revenue | Cost |\n| 200 | 100 |",
          "evidence":["Revenue 200","Cost 100"],"gold_answer":"SECRET_GOLD_0.5"}
    base.update(extra);return base

def test_prompt_contains_grounding_and_format_but_not_gold_field():
    prompt,audit=build_prompt(task())
    assert "实验任务类型" in prompt and "【问题】" in prompt
    assert "【上下文】" in prompt and "【表格】" in prompt and "【证据】" in prompt
    assert "【回答格式要求】" in prompt and "最终答案" in prompt
    assert "SECRET_GOLD" not in prompt
    assert audit["gold_answer_field_injected"] is False
    assert audit["context_truncated"] is False

def test_context_under_limit_is_not_truncated():
    prompt,audit=build_prompt(task(context="x"*9000))
    assert audit["source_original_chars"]<MAX_INPUT_CHARS
    assert audit["context_truncated"] is False
    assert "x"*100 in prompt

def test_signature_changes_with_context_and_has_required_versions():
    tasks=[task()];p1=signature_payload(freeze_id="f",dataset_sha256="d",models=["m"],tasks=tasks,repeats=1,phase="pilot")
    changed=deepcopy(tasks);changed[0]["context"]="different evidence"
    p2=signature_payload(freeze_id="f",dataset_sha256="d",models=["m"],tasks=changed,repeats=1,phase="pilot")
    assert signature(p1)!=signature(p2)
    assert p1["prompt_template_version"]==PROMPT_TEMPLATE_VERSION
    assert p1["answer_format_version"]==ANSWER_FORMAT_VERSION
    assert p1["data_version"]==DATA_VERSION
    assert p1["max_input_chars"]==MAX_INPUT_CHARS
    assert p1["context_hashes"]

def test_numeric_percent_unit_and_parentheses_normalization():
    assert objective_score(task(gold_answer="0.32803"),"Calculation... 最终答案：32.803%") == 1.0
    tat=task("financial_table_text_reasoning",dataset="TAT-QA",gold_answer="(21) million")
    assert objective_score(tat,"最终答案：-21 million") == 1.0

def test_finkg_entity_normalization():
    kg=task("financial_kg_grounded_qa",dataset="FinReflectKG",gold_answer="Aladdin")
    assert objective_score(kg,"最终答案：ALADDIN。证据表明该平台与BLK相关。") == 1.0

def test_compliance_evidence_coverage_is_objective_but_paraphrase_tolerant():
    gold="An insurer risk management system must address material risks and integrate risk management with business operations."
    comp=task("financial_audit_compliance_qa",dataset="ObliQA",gold_answer=gold)
    good="The insurer must integrate risk management with business operations and address all material risks."
    assert objective_score(comp,good)>=.6

def test_context_pilot_selects_exactly_three_per_dataset():
    tasks=[]
    kinds=[("FinQA","financial_numerical_reasoning"),("TAT-QA","financial_table_text_reasoning"),("ObliQA","financial_audit_compliance_qa"),("FinReflectKG","financial_kg_grounded_qa")]
    for ds,kind in kinds:
        for i in range(5):tasks.append(task(kind,id=f"{kind}-{i}",dataset=ds))
    selected=select_context_pilot(tasks)
    from collections import Counter
    from openclaw_router.experiment_protocol import canonical_dataset
    assert Counter(canonical_dataset(x) for x in selected)=={"FinQA":3,"TAT-QA":3,"AuditCompliance":3,"FinKG":3}

def test_objective_infeasible_answer_gets_zero_utility():
    assert utility({"quality":.9,"cost":0,"latency":0,"reliability":1,"objective_feasible":False})==0.0
    assert utility({"quality":.9,"cost":0,"latency":0,"reliability":1,"objective_feasible":True})>0.0


def test_finqa_yes_no_text_fallback():
    yesno=task(gold_answer="no")
    assert objective_score(yesno,"50.50 is less than 90.50. 最终答案：否") == 1.0
    assert objective_score(yesno,"最终答案：yes") == 0.0


def test_numeric_scoring_ignores_late_template_placeholder():
    item=task(gold_answer="0.34")
    response="最终答案：34.0%\nanalysis mentions format 最终答案：<数值><单位>"
    assert objective_score(item,response)==1.0

def test_numeric_scoring_falls_back_to_full_text_when_only_placeholder_exists():
    item=task("financial_table_text_reasoning",dataset="TAT-QA",gold_answer="2019, 2018, 2017")
    response="The table shows 2019, 2018 and 2017. 最终答案：<数值><单位>"
    assert objective_score(item,response)==1.0

def test_numeric_scoring_uses_later_real_answer_after_placeholder():
    item=task("financial_table_text_reasoning",dataset="TAT-QA",gold_answer="234 thousand")
    response="最终答案：<数值><单位> discussion\n最终答案：234000 dollars"
    assert objective_score(item,response)==1.0
