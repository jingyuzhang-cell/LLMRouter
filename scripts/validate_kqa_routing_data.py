#!/usr/bin/env python3
"""Validate KQAPro per-model routing JSONL files in one pass."""
import argparse, json
from pathlib import Path
from kqa_routing_utils import MODEL_SPECS, validate_file
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data/kqapro/router_data"
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-dir",type=Path,default=DEFAULT_DIR)
    parser.add_argument("--models",nargs="+",default=["deepseek","qwen","zhipu","gemini","qwen-3b-local"],choices=MODEL_SPECS)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args(); reports=[]
    for model in args.models:
        report=validate_file(args.data_dir/MODEL_SPECS[model]["file"]); report["model"]=model; reports.append(report)
    result={"schema":"kqapro-routing-validation-v1","passed":all(r["passed"] for r in reports),"models":reports}
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output: args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(text+"\n",encoding="utf-8")
    print(text)
    raise SystemExit(0 if result["passed"] else 1)
if __name__=="__main__": main()
