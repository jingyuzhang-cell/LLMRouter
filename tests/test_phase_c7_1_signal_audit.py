import json
from pathlib import Path

ROOT = Path("/root")


def test_c7_1_is_diagnostic_and_frozen():
    protocol = json.loads((ROOT / "phase_c7_1/C7_1_PROTOCOL.json").read_text())
    assert protocol["status"] == "FROZEN_BEFORE_C7_1_EXECUTION"
    assert protocol["role"].endswith("no router selection or tuning")
    assert protocol["v3_outcomes_used"] is False


def test_c7_1_reuses_oof_predictions():
    protocol = json.loads((ROOT / "phase_c7_1/C7_1_PROTOCOL.json").read_text())
    assert protocol["prediction_source"] == "phase_c7/C7_OOF_DECISIONS.jsonl"
    assert "advantage MAE" in protocol["metrics"]["routing"]
