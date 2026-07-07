"""Convert finance QA datasets into the router training schema.

Supported inputs:
- FinQA-style JSON/JSONL
- TAT-QA-style JSON/JSONL
- Already-normalized generic JSON/JSONL

The script is intentionally tolerant because public dataset dumps often differ
slightly between GitHub, Hugging Face and paper release versions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "finance_router" / "standardized" / "finance_router_tasks.jsonl"
DEFAULT_SEED = ROOT / "data" / "finance_router" / "samples" / "finance_seed.jsonl"


def read_records(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "examples", "items", "questions"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    raise ValueError(f"Unsupported payload in {path}")


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def normalize_table(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        rows = value.get("table") or value.get("rows") or value.get("data")
        return rows if isinstance(rows, list) else [value]
    return []


def first_present(record: Dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return default


def base_sample(
    *,
    sample_id: str,
    dataset: str,
    task_type: str,
    question: str,
    context: str,
    table: List[Any],
    gold_answer: str,
    evidence: List[Any],
    risk_level: str,
    requires_calculation: bool,
    requires_table_reasoning: bool,
    requires_kg_reasoning: bool = False,
) -> Dict[str, Any]:
    return {
        "id": sample_id,
        "domain": "finance",
        "dataset": dataset,
        "task_type": task_type,
        "question": question,
        "context": context,
        "table": table,
        "gold_answer": gold_answer,
        "evidence": evidence,
        "risk_level": risk_level,
        "requires_calculation": requires_calculation,
        "requires_table_reasoning": requires_table_reasoning,
        "requires_kg_reasoning": requires_kg_reasoning,
        "requires_verification": True,
        "model_results": {},
        "best_model": None,
    }


def convert_finqa(record: Dict[str, Any], index: int) -> Dict[str, Any]:
    question = as_text(first_present(record, ("question", "qa_question", "query", "question_text"), ""))
    context = as_text(first_present(record, ("context", "pre_text", "post_text", "paragraph", "text"), ""))
    if isinstance(record.get("pre_text"), list) or isinstance(record.get("post_text"), list):
        pre = " ".join(as_text(item) for item in record.get("pre_text", []))
        post = " ".join(as_text(item) for item in record.get("post_text", []))
        context = f"{pre}\n{post}".strip()
    answer = as_text(first_present(record, ("answer", "gold_answer", "exe_ans", "qa_answer"), ""))
    sample_id = as_text(first_present(record, ("id", "uid", "example_id"), f"finqa_{index:06d}"))
    return base_sample(
        sample_id=sample_id,
        dataset="FinQA",
        task_type="financial_numerical_reasoning",
        question=question,
        context=context,
        table=normalize_table(first_present(record, ("table", "table_ori", "table_retrieved"))),
        gold_answer=answer,
        evidence=first_present(record, ("evidence", "gold_inds", "program", "derivation"), []) or [],
        risk_level="medium",
        requires_calculation=True,
        requires_table_reasoning=bool(first_present(record, ("table", "table_ori", "table_retrieved"), [])),
    )


def convert_tatqa(record: Dict[str, Any], index: int) -> Dict[str, Any]:
    question = as_text(first_present(record, ("question", "query", "question_text"), ""))
    context = as_text(first_present(record, ("context", "paragraphs", "text", "passage"), ""))
    if isinstance(record.get("paragraphs"), list):
        context = " ".join(as_text(item.get("text", item)) if isinstance(item, dict) else as_text(item) for item in record["paragraphs"])
    answer = as_text(first_present(record, ("answer", "gold_answer", "answer_from"), ""))
    if isinstance(record.get("answer"), dict):
        answer = as_text(first_present(record["answer"], ("answer", "value", "text"), record["answer"]))
    sample_id = as_text(first_present(record, ("id", "uid", "question_id"), f"tatqa_{index:06d}"))
    return base_sample(
        sample_id=sample_id,
        dataset="TAT-QA",
        task_type="financial_table_text_reasoning",
        question=question,
        context=context,
        table=normalize_table(first_present(record, ("table", "table_ori", "table_data"))),
        gold_answer=answer,
        evidence=first_present(record, ("evidence", "supporting_facts", "derivation"), []) or [],
        risk_level="medium",
        requires_calculation=True,
        requires_table_reasoning=True,
    )


def convert_generic(record: Dict[str, Any], index: int) -> Dict[str, Any]:
    if record.get("domain") == "finance" and record.get("question"):
        normalized = dict(record)
        normalized.setdefault("id", f"finance_{index:06d}")
        normalized.setdefault("dataset", "generic")
        normalized.setdefault("task_type", "financial_qa")
        normalized.setdefault("context", "")
        normalized.setdefault("table", [])
        normalized.setdefault("gold_answer", "")
        normalized.setdefault("evidence", [])
        normalized.setdefault("risk_level", "medium")
        normalized.setdefault("requires_calculation", False)
        normalized.setdefault("requires_table_reasoning", bool(normalized.get("table")))
        normalized.setdefault("requires_kg_reasoning", False)
        normalized.setdefault("requires_verification", True)
        normalized.setdefault("model_results", {})
        normalized.setdefault("best_model", None)
        return normalized
    return base_sample(
        sample_id=as_text(first_present(record, ("id", "uid"), f"finance_{index:06d}")),
        dataset=as_text(record.get("dataset") or "generic"),
        task_type=as_text(record.get("task_type") or "financial_qa"),
        question=as_text(first_present(record, ("question", "query", "prompt"), "")),
        context=as_text(first_present(record, ("context", "text", "passage"), "")),
        table=normalize_table(record.get("table")),
        gold_answer=as_text(first_present(record, ("gold_answer", "answer", "label"), "")),
        evidence=record.get("evidence") or [],
        risk_level=as_text(record.get("risk_level") or "medium"),
        requires_calculation=bool(record.get("requires_calculation")),
        requires_table_reasoning=bool(record.get("requires_table_reasoning") or record.get("table")),
        requires_kg_reasoning=bool(record.get("requires_kg_reasoning")),
    )


def convert_records(records: List[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    converters = {
        "finqa": convert_finqa,
        "tatqa": convert_tatqa,
        "generic": convert_generic,
    }
    converter = converters[source]
    return [converter(record, index + 1) for index, record in enumerate(records)]


def write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare finance router data.")
    parser.add_argument("--source", choices=["finqa", "tatqa", "generic", "seed"], default="seed")
    parser.add_argument("--input", type=Path, help="Raw input JSON/JSONL file.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--append", action="store_true", help="Append to output instead of overwriting.")
    args = parser.parse_args()

    if args.source == "seed":
        records = read_records(DEFAULT_SEED)
    else:
        if not args.input:
            raise SystemExit("--input is required unless --source seed is used.")
        records = convert_records(read_records(args.input), args.source)

    if args.append and args.output.exists():
        existing = read_records(args.output)
        records = existing + records

    write_jsonl(args.output, records)
    print(f"Wrote {len(records)} records to {args.output}")


if __name__ == "__main__":
    main()
