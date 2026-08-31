import ast
from pathlib import Path


ROOT = Path("/root")


def test_protocol_is_frozen_and_excludes_confirmatory_data():
    import json
    protocol = json.loads((ROOT / "phase_c7/C7_PROTOCOL.json").read_text())
    assert protocol["status"] == "FROZEN_BEFORE_C7_EXECUTION"
    assert protocol["v3_outcomes_used"] is False
    assert "gold_answer" in protocol["forbidden_inputs"]
    assert protocol["quality_target"].startswith("per-task per-model mean quality")


def test_request_text_uses_only_deployable_fields():
    tree = ast.parse((ROOT / "run_phase_c7_soft_performance_router.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "request_text")
    accessed = {
        call.args[0].value
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "task"
        and call.func.attr == "get"
        and call.args
        and isinstance(call.args[0], ast.Constant)
    }
    assert accessed == {"question", "context", "table"}
