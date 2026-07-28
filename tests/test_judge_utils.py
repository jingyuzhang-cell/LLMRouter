from openclaw_router.judge_utils import calibrate_score, extract_message_text, parse_judge_payload


def test_extracts_glm_reasoning_when_content_empty():
    result={"choices":[{"message":{"content":"","reasoning_content":"analysis\n{\"score\":0.7,\"reason\":\"ok\"}"}}]}
    text=extract_message_text(result)
    assert '"score":0.7' in text
    assert parse_judge_payload(text)["score"] == 0.7


def test_parses_fenced_and_chinese_judge_json():
    parsed=parse_judge_payload('```json\n{"评分":"80%","维度":{"准确性":0.9},"理由":"通过"}\n```')
    assert parsed["score"] == 0.8
    assert parsed["dimensions"]["accuracy"] == 0.9


def test_finds_json_after_reasoning_text():
    parsed=parse_judge_payload('先分析。最终输出如下： {"overall_score": 65, "reason": "partial"} trailing')
    assert parsed["score"] == 0.65


def test_calibration_is_disabled_by_default_and_clamped_when_enabled():
    cfg={"enabled":False,"models":{"qwen-turbo":{"intercept":-0.1,"slope":0.7}}}
    assert calibrate_score("qwen-turbo",0.8,cfg)==0.8
    cfg["enabled"]=True
    assert calibrate_score("qwen-turbo",0.8,cfg)==0.46
    assert calibrate_score("qwen-turbo",0.0,cfg)==0.0
