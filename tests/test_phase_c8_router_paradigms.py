import ast
import json
from pathlib import Path

ROOT = Path("/root")


def test_c8_protocol_freezes_fair_comparison():
    p = json.loads((ROOT/"phase_c8/C8_PROTOCOL.json").read_text())
    assert p["status"] == "FROZEN_BEFORE_C8_EXECUTION"
    assert p["v3_outcomes_used"] is False
    assert set(p["targets"]) == {"hard_classification", "pairwise_preference", "performance_prediction"}


def test_c8_router_input_fields_are_deployable():
    tree = ast.parse((ROOT/"run_phase_c8_router_paradigm_benchmark.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "request_text")
    accessed = {c.args[0].value for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and isinstance(c.func.value, ast.Name) and c.func.value.id == "task" and c.func.attr == "get"
                and c.args and isinstance(c.args[0], ast.Constant)}
    assert accessed == {"question", "context", "table"}
