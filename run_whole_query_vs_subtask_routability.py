#!/usr/bin/env python3
"""Offline scaffold only: validate inputs and emit a preregistered comparison plan."""
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--performance-matrix", type=Path)
    parser.add_argument("--subtask-manifest", type=Path)
    parser.add_argument("--out", type=Path, default=Path("/root/c10_prep/WHOLE_QUERY_VS_SUBTASK_DRY_RUN.json"))
    args = parser.parse_args()
    inputs = {}
    for name, path in (("performance_matrix", args.performance_matrix), ("subtask_manifest", args.subtask_manifest)):
        inputs[name] = {"provided": path is not None, "exists": bool(path and path.exists()), "path": str(path) if path else None}
    report = {
        "status": "DRY_RUN_ONLY",
        "external_api_calls": 0,
        "model_calls": 0,
        "router_training": False,
        "dag_execution": False,
        "inputs": inputs,
        "comparison_unit": "same C10-prep task under whole-query and decomposition-aware subtask policies",
        "frozen_metrics": ["stable semantic oracle gap", "stable reversal rate", "top1-top2 margin"],
        "required_before_analysis": ["complete C9 performance matrix", "frozen input-only decomposition manifest", "matched repeat identifiers"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
