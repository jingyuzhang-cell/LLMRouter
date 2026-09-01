import json
import subprocess
import sys
from pathlib import Path


def test_analyzer_fails_closed_without_scored_packets(tmp_path):
    result = subprocess.run(
        [sys.executable, "/root/analyze_c9_human_calibration.py", "--reviewer-a", str(tmp_path / "a.jsonl"), "--reviewer-b", str(tmp_path / "b.jsonl")],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "BLOCKED" in result.stderr + result.stdout


def test_analyzer_requires_complete_scores(tmp_path):
    source = Path("/root/phase_c9_0/human_judge_calibration/C9_HUMAN_REVIEWER_A.jsonl")
    rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    for row in rows:
        row["reviewer_confidence"] = "high"
        for candidate in row["candidates"]:
            candidate["score"] = 4
            candidate["reason"] = "supported"
    rows[0]["candidates"][0]["score"] = None
    broken = tmp_path / "broken.jsonl"
    broken.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = subprocess.run(
        [sys.executable, "/root/analyze_c9_human_calibration.py", "--reviewer-a", str(broken), "--reviewer-b", str(broken)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "score must be integer 0..4" in result.stderr
