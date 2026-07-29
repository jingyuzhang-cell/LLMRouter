"""Context-grounded experiment prompt, signature, sampling and objective grading."""
from __future__ import annotations
import hashlib,json,re,unicodedata,random
from collections import defaultdict
from typing import Any,Dict,List,Optional,Tuple

PROMPT_TEMPLATE_VERSION="context-grounded-v2"
ANSWER_FORMAT_VERSION="task-aware-final-answer-v2"
DATA_VERSION="finance-benchmark-v2-context-grounded"
MAX_INPUT_CHARS=24000
OBJECTIVE_FEASIBILITY_THRESHOLD=0.60
OBJECTIVE_SCORER_VERSION="dataset-aware-objective-v2.2"
RELIABILITY_VERSION="api-availability-times-answer-correctness-v2"

_STOPWORDS={"the","a","an","and","or","of","to","in","for","is","are","be","by","with","that","this","must","should","may","its","their","from","as","on","at"}

def canonical_dataset(task:Dict[str,Any])->str:
    dataset=str(task.get("dataset") or "").lower();kind=str(task.get("task_type") or "")
    if "finqa" in dataset or kind=="financial_numerical_reasoning":return "FinQA"
    if "tat-qa" in dataset or kind=="financial_table_text_reasoning":return "TAT-QA"
    if "obliqa" in dataset or "audit_compliance" in kind:return "AuditCompliance"
    if "kg_" in kind or "finreflectkg" in dataset or "finkg" in dataset:return "FinKG"
    return str(task.get("dataset") or "unknown")

def _serialize(value:Any)->str:
    if value in (None,"",[],{}):return ""
    if isinstance(value,str):return value
    return json.dumps(value,ensure_ascii=False,sort_keys=True)

def answer_format(task:Dict[str,Any])->str:
    kind=str(task.get("task_type") or "")
    if kind in {"financial_numerical_reasoning","financial_table_text_reasoning"}:
        return "先给出必要的计算式和关键取值，最后单独一行输出“最终答案：<数值><单位>”。"
    if "kg_" in kind:
        return "先单独一行输出“最终答案：<实体、关系目标或间接关系>”，再用所给证据作简短说明。"
    if "audit_compliance" in kind:
        return "按“结论—证据依据—合规理由”作答；仅依据所给材料，不补造法规条文。"
    return "直接回答问题，并把最终结论放在“最终答案：”之后。"

def build_prompt(task:Dict[str,Any],max_input_chars:int=MAX_INPUT_CHARS)->Tuple[str,Dict[str,Any]]:
    question=str(task.get("query") or task.get("question") or "").strip()
    context=_serialize(task.get("context")).strip();table=_serialize(task.get("table")).strip();evidence=_serialize(task.get("evidence")).strip()
    sections=[]
    if context:sections.append(("上下文",context))
    if table and table not in context:sections.append(("表格",table))
    if evidence and evidence not in context:sections.append(("证据",evidence))
    source="\n\n".join(f"【{name}】\n{value}" for name,value in sections)
    original_chars=len(source);truncated=False
    if len(source)>max_input_chars:
        source=source[:max_input_chars];truncated=True
    prompt=(f"实验任务类型：{task.get('task_type') or task.get('type') or 'unknown'}\n"
            f"数据集：{canonical_dataset(task)}\n\n"
            f"【问题】\n{question}\n\n"
            f"{source}\n\n"
            f"【回答格式要求】\n{answer_format(task)}\n"
            "只能依据上述上下文、表格和证据作答。如果材料不足，请明确说明；不要声称看到了未提供的信息。")
    audit={"prompt_template_version":PROMPT_TEMPLATE_VERSION,"answer_format_version":ANSWER_FORMAT_VERSION,
           "max_input_chars":max_input_chars,"source_original_chars":original_chars,"source_included_chars":len(source),
           "context_chars":len(context),"table_chars":len(table),"evidence_chars":len(evidence),"context_truncated":truncated,
           "context_sha256":hashlib.sha256(source.encode()).hexdigest(),"gold_answer_field_injected":False}
    return prompt,audit

def signature_payload(*,freeze_id:str,dataset_sha256:Optional[str],models:List[str],tasks:List[Dict[str,Any]],repeats:int,phase:str)->Dict[str,Any]:
    context_hashes=[]
    for task in tasks:
        _,audit=build_prompt(task)
        context_hashes.append({"task_id":task["id"],"context_sha256":audit["context_sha256"]})
    return {"freeze_id":freeze_id,"dataset_sha256":dataset_sha256,"data_version":DATA_VERSION,
            "prompt_template_version":PROMPT_TEMPLATE_VERSION,"answer_format_version":ANSWER_FORMAT_VERSION,
            "max_input_chars":MAX_INPUT_CHARS,"phase":phase,"models":models,"task_ids":[t["id"] for t in tasks],
            "context_hashes":context_hashes,"repeats":repeats,"judge_count":2,"objective_weight":.7,"judge_weight":.3,
            "objective_feasibility_threshold":OBJECTIVE_FEASIBILITY_THRESHOLD,
            "objective_scorer_version":OBJECTIVE_SCORER_VERSION,
            "reliability_version":RELIABILITY_VERSION}

def signature(payload:Dict[str,Any])->str:
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def select_context_pilot(tasks:List[Dict[str,Any]],per_dataset:int=3,seed:int=20260728)->List[Dict[str,Any]]:
    groups=defaultdict(list)
    for task in tasks:groups[canonical_dataset(task)].append(task)
    rng=random.Random(seed);selected=[]
    for name in ("FinQA","TAT-QA","AuditCompliance","FinKG"):
        values=sorted(groups[name],key=lambda x:str(x.get("id")));rng.shuffle(values)
        if len(values)<per_dataset:raise ValueError(f"{name} has only {len(values)} tasks")
        selected.extend(values[:per_dataset])
    return selected

def _norm(text:str)->str:
    text=unicodedata.normalize("NFKC",text or "").lower()
    return re.sub(r"[^a-z0-9%+.-]+"," ",text).strip()

def _numbers(text:str)->List[float]:
    out=[]
    pattern=r"\(\s*\d+(?:,\d{3})*(?:\.\d+)?\s*\)|[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?"
    for raw in re.findall(pattern,text or ""):
        paren=raw.strip().startswith("(");percent=raw.strip().endswith("%")
        clean=raw.strip().strip("()").rstrip("%").replace(",","")
        try:value=float(clean)
        except ValueError:continue
        if paren:value=-value
        out.append(value)
        if percent:out.append(value/100.0)
        elif 0<abs(value)<=1:out.append(value*100.0)
    return out

def _unit_scale(text:str)->float:
    value=(text or "").lower()
    if re.search(r"\b(?:billion|bn)\b|十亿",value):return 1_000_000_000.0
    if re.search(r"\b(?:million|mn)\b|[£€$]\s*m\b|百万",value):return 1_000_000.0
    if re.search(r"\b(?:thousand|000s)\b|千",value):return 1_000.0
    return 1.0

def _numeric_score(gold:str,response:str)->Optional[float]:
    gold_scale=_unit_scale(gold)
    expected=[x*gold_scale for x in _numbers(gold)]
    if not expected:return None
    marker=re.compile(r"(?:final\s+answer|最终答案|答案|result)\s*[:：]",re.I)
    explicit=[]
    for match in marker.finditer(response):
        line=response[match.end():].splitlines()[0].strip()
        if line and not re.search(r"<\s*(?:数值|单位|value|unit)",line,re.I):explicit.append(line)
    candidate="\n".join(explicit) if explicit else response
    candidate_scale=_unit_scale(candidate) if gold_scale!=1.0 else 1.0
    observed=[x*candidate_scale for x in _numbers(candidate)]
    if not observed:return 0.0
    matched=0
    for left in expected:
        if any(abs(left-right)<=max(1e-6,abs(left)*.01) for right in observed):matched+=1
    return round(min(1.0,matched/max(1,len(expected))),3)

def objective_score(task:Dict[str,Any],response:str)->Optional[float]:
    gold=str(task.get("gold_answer") or "").strip()
    if not gold:return None
    kind=str(task.get("task_type") or "")
    if kind in {"financial_numerical_reasoning","financial_table_text_reasoning"}:
        numeric = _numeric_score(gold,response)
        if numeric is not None:
            return numeric
    gold_norm=_norm(gold);response_norm=_norm(response)
    if gold_norm in {"yes", "no"}:
        tail = re.split(r"(?:final\s+answer|最终答案|答案|结论)\s*[:：]", response, flags=re.I)[-1].strip().lower()
        yes = bool(re.search(r"^(?:yes|是|正确|大于|高于)\b", tail))
        no = bool(re.search(r"^(?:no|否|不是|不|小于|低于)", tail)) or any(token in response.lower() for token in ("not greater", "less than", "并不大于", "小于"))
        return 1.0 if (gold_norm == "yes" and yes) or (gold_norm == "no" and no) else 0.0
    if gold_norm and gold_norm in response_norm:return 1.0
    if "kg_" in kind:
        tokens=[x for x in gold_norm.split() if x not in _STOPWORDS]
        if not tokens:return 0.0
        return round(sum(token in response_norm.split() for token in tokens)/len(tokens),3)
    # Compliance: evidence/obligation coverage, tolerant of paraphrase; LLM judges explanation separately.
    if "audit_compliance" in kind or len(gold)>300:
        gt={x for x in gold_norm.split() if len(x)>2 and x not in _STOPWORDS}
        rt=set(response_norm.split())
        if not gt:return None
        recall=len(gt & rt)/len(gt)
        return round(min(1.0,recall/.65),3)
    gt={x for x in gold_norm.split() if x not in _STOPWORDS};rt=set(response_norm.split())
    return round(len(gt & rt)/max(1,len(gt)),3)

def objective_feasible(score:Optional[float],threshold:float=OBJECTIVE_FEASIBILITY_THRESHOLD)->Optional[bool]:
    return None if score is None else bool(score>=threshold)
