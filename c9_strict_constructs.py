"""Outcome-blind operational eligibility predicates for C9 failed strata."""
import re
import hashlib
import json
from pathlib import Path

PASSED = {"simple_extraction", "cross_row_column_table_reasoning", "compliance_regulation_reasoning"}
_snapshot = Path("/root/phase_c9_0/C9_DEV_TASKS_PRE_REBUILD.jsonl")
_frozen = {name: set() for name in PASSED}
if _snapshot.exists():
    for line in _snapshot.read_text().splitlines():
        row = json.loads(line)
        if row["primary_capability"] in PASSED:
            _frozen[row["primary_capability"]].add(row["task_id"])
def task_id(x):
    return "c9_" + hashlib.sha256((x["source"]+"|"+x["source_id"]).encode()).hexdigest()[:20]
def reserved_for_passed(x):
    return any(task_id(x) in values for values in _frozen.values())

def eligible(x, stratum):
    f, q = x["observable_features"], x["question"].lower()
    if stratum in PASSED:
        return task_id(x) in _frozen[stratum]
    if reserved_for_passed(x):
        return False
    if stratum == "long_context_understanding":
        return f["context_token_count"] >= 2000
    if stratum == "ambiguity_negation_exception":
        return bool(re.search(r"\b(?:except|unless|notwithstanding|only if|without|if|whether|not|no)\b", q))
    if stratum == "numerical_arithmetic":
        return bool(re.search(r"\b(?:percent|percentage|ratio|average|sum|total|difference|change|increase|decrease|growth rate|how much)\b|[+*/]", q)) and not q.startswith(("why ", "what affected", "what was the reason"))
    if stratum == "multi_step_numerical_reasoning":
        operation = bool(re.search(r"\b(?:percent|percentage|ratio|average|change|increase|decrease|growth|total|sum)\b", q))
        dependency = bool(re.search(r"\b(?:if|assuming|based on|at the same rate|excluding|combined|as a percentage of|what would|expected)\b", q))
        return operation and dependency
    if stratum == "table_text_hybrid_reasoning":
        numeric = bool(re.search(r"\b(?:percent|percentage|change|increase|decrease|amount|value|how much|which year)\b", q))
        prose = bool(re.search(r"\b(?:why|reason|because|accounted for|led to|explain|according to|based on)\b", q))
        return f["table_cell_count"] > 0 and numeric and prose
    if stratum == "multi_hop_reasoning":
        chain = bool(re.search(r"\b(?:connect|relate|relationship|influence|impact|role|lead to)\b", q))
        return chain and f["paragraph_count"] >= 2 and f["conjunction_count"] >= 1
    if stratum == "evidence_synthesis":
        synthesis = bool(re.search(r"\b(?:compare|combined|both|respectively|and how|and what|across|overall)\b", q))
        return synthesis and f["paragraph_count"] >= 2 and f["evidence_cue_count"] >= 1
    return True
