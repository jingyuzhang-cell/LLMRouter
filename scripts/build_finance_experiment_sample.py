"""Build a reproducible, stratified 80-item finance experiment set.

Sources are the official FinQA and TAT-QA training releases plus the project's
manually curated AuditCompliance/FinKG seeds. The output keeps provenance and
never relabels seed examples as public benchmark records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FINQA = ROOT / "data/finance_router/raw/finqa/train.json"
TATQA = ROOT / "data/finance_router/raw/tatqa/train.json"
SEEDS = ROOT / "data/finance_router/samples/finance_seed.jsonl"
OBLIQA = ROOT / "data/finance_router/raw/obliqa/dev.json"
FINREFLECT = ROOT / "data/finance_router/raw/finreflectkg_multihop/evalbench_rows.json"
OUTPUT = ROOT / "data/finance_router/standardized/finance_router_tasks.jsonl"
MANIFEST = ROOT / "data/finance_router/standardized/finance_experiment_manifest.json"
SOURCE_URLS = {
    "FinQA": "https://github.com/czyssrs/FinQA",
    "TAT-QA": "https://github.com/NExTplusplus/TAT-QA",
    "ObliQA": "https://github.com/RegNLP/ObliQADataset",
    "FinReflectKG-EvalBench": "https://huggingface.co/datasets/domyn/FinReflectKG-EvalBench",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def answer_text(value: Any, scale: str = "") -> str:
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value)
    elif isinstance(value, dict):
        text = str(value.get("answer") or value.get("value") or value)
    else:
        text = str(value or "")
    return f"{text} {scale}".strip()


def finqa_records() -> list[dict[str, Any]]:
    records = []
    for report_index, report in enumerate(read_json(FINQA)):
        qa = report.get("qa") or {}
        question = qa.get("question")
        if not question:
            continue
        sample_id = str(qa.get("id") or f"finqa_{report_index:06d}")
        program = qa.get("program") or ""
        first_operation = str(program).split(",", 1)[0].split("(", 1)[0] or "unknown"
        records.append({
            "id": sample_id,
            "domain": "finance",
            "dataset": "FinQA",
            "task_type": "financial_numerical_reasoning",
            "question": question,
            "context": " ".join(report.get("pre_text", []) + report.get("post_text", [])),
            "table": report.get("table") or [],
            "gold_answer": answer_text(qa.get("exe_ans") or qa.get("answer")),
            "evidence": list((qa.get("gold_inds") or {}).values()) + ([program] if program else []),
            "risk_level": "medium",
            "requires_calculation": True,
            "requires_table_reasoning": bool(report.get("table")),
            "requires_kg_reasoning": False,
            "requires_verification": True,
            "stratum": "program:" + first_operation,
            "source_split": "train",
            "source_url": SOURCE_URLS["FinQA"],
            "source_id": sample_id,
            "model_results": {}, "best_model": None,
        })
    return records


def tatqa_records() -> list[dict[str, Any]]:
    records = []
    for report_index, report in enumerate(read_json(TATQA)):
        table = (report.get("table") or {}).get("table") or []
        context = " ".join(str(item.get("text", "")) for item in report.get("paragraphs", []))
        for question_index, qa in enumerate(report.get("questions", [])):
            question = qa.get("question")
            if not question:
                continue
            sample_id = str(qa.get("uid") or f"tatqa_{report_index:06d}_{question_index:02d}")
            answer_type = str(qa.get("answer_type") or "unknown")
            answer_from = str(qa.get("answer_from") or "unknown")
            records.append({
                "id": sample_id,
                "domain": "finance",
                "dataset": "TAT-QA",
                "task_type": "financial_table_text_reasoning",
                "question": question,
                "context": context,
                "table": table,
                "gold_answer": answer_text(qa.get("answer"), str(qa.get("scale") or "")),
                "evidence": ([qa.get("derivation")] if qa.get("derivation") else []) + list(qa.get("rel_paragraphs") or []),
                "risk_level": "medium",
                "requires_calculation": answer_type == "arithmetic" or bool(qa.get("derivation")),
                "requires_table_reasoning": answer_from in {"table", "table-text"},
                "requires_kg_reasoning": False,
                "requires_verification": True,
                "stratum": f"{answer_from}:{answer_type}",
                "source_split": "train",
                "source_url": SOURCE_URLS["TAT-QA"],
                "source_id": sample_id,
                "model_results": {}, "best_model": None,
            })
    return records


def obliqa_records() -> list[dict[str, Any]]:
    records = []
    for item in read_json(OBLIQA):
        passages = item.get("Passages") or []
        sample_id = str(item.get("QuestionID"))
        records.append({
            "id": sample_id, "domain": "finance", "dataset": "ObliQA",
            "task_type": "financial_audit_compliance_qa", "question": str(item.get("Question") or ""),
            "context": "\n".join(str(p.get("Passage") or "") for p in passages), "table": [],
            "gold_answer": "\n".join(str(p.get("Passage") or "") for p in passages),
            "evidence": [{"document_id": p.get("DocumentID"), "passage_id": p.get("PassageID")} for p in passages],
            "risk_level": "high", "requires_calculation": False, "requires_table_reasoning": False,
            "requires_kg_reasoning": False, "requires_verification": True,
            "stratum": f"passages:{len(passages)}", "source_split": "dev",
            "source_url": SOURCE_URLS["ObliQA"], "source_id": sample_id,
            "review_status": "source_validated_nli", "model_results": {}, "best_model": None,
        })
    return records


def finreflect_records() -> list[dict[str, Any]]:
    records, seen = [], set()
    files = sorted(FINREFLECT.parent.glob("evalbench_*.json")) or [FINREFLECT]
    for source_file in files:
        payload = read_json(source_file)
        for wrapped in payload.get("rows", []):
            item = wrapped.get("row") or {}
            if not (item.get("is_faithfulness") and item.get("is_precision") and item.get("is_relevance")):
                continue
            identity = "|".join(str(item.get(key) or "") for key in ("ticker", "source_file", "page_id", "chunk_id", "triplet_id", "entity", "relationship", "target"))
            if identity in seen:
                continue
            seen.add(identity)
            sample_id = "finreflect_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            entity, relation, target = str(item.get("entity")), str(item.get("relationship")), str(item.get("target"))
            normalized_target = re.sub(r"[^a-z0-9]+", "", target.lower())
            normalized_context = re.sub(r"[^a-z0-9]+", "", str(item.get("chunk_text") or "").lower())
            if not normalized_target or normalized_target not in normalized_context:
                continue
            records.append({
                "id": sample_id, "domain": "finance", "dataset": "FinReflectKG-EvalBench-derived",
                "task_type": "financial_kg_grounded_qa",
                "question": f"According to the supplied filing evidence, what target is connected to {entity} by the relation {relation}?",
                "context": str(item.get("chunk_text") or ""), "table": [], "gold_answer": target,
                "evidence": [{"entity": entity, "relationship": relation, "target": target, "ticker": item.get("ticker"), "year": item.get("year"), "source_file": item.get("source_file"), "page_id": item.get("page_id"), "chunk_id": item.get("chunk_id")}],
                "risk_level": "high", "requires_calculation": False, "requires_table_reasoning": False,
                "requires_kg_reasoning": True, "requires_verification": True,
                "stratum": f"ticker:{item.get('ticker')}|relation:{relation}", "source_split": source_file.stem,
                "source_url": SOURCE_URLS["FinReflectKG-EvalBench"], "source_id": str(item.get("triplet_id")),
                "review_status": "source_flags_passed_human_signoff_pending",
                "model_results": {}, "best_model": None,
            })
    return records

def stratified_sample(records: list[dict[str, Any]], size: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        groups[str(item.get("stratum") or "unknown")].append(item)
    for values in groups.values():
        rng.shuffle(values)
    chosen = []
    keys = sorted(groups)
    rng.shuffle(keys)
    while len(chosen) < min(size, len(records)):
        progressed = False
        for key in keys:
            if groups[key] and len(chosen) < size:
                chosen.append(groups[key].pop())
                progressed = True
        if not progressed:
            break
    rng.shuffle(chosen)
    return chosen


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=110)
    parser.add_argument("--seed", type=int, default=20260727)
    args = parser.parse_args()
    if args.size < 4:
        raise SystemExit("--size must be at least 4 to retain the four provenance layers")
    seeds = read_jsonl(SEEDS)
    if args.size < 110:
        public_size = args.size - len(seeds)
        quotas = {"finqa": public_size // 2, "tatqa": public_size - public_size // 2, "obliqa": 0, "finkg": 0}
    else:
        remaining = args.size - len(seeds)
        quotas = {"finqa": 36, "tatqa": 36, "obliqa": 17, "finkg": 17}
        quotas["tatqa"] += remaining - sum(quotas.values())
    selected = stratified_sample(finqa_records(), quotas["finqa"], args.seed)
    selected += stratified_sample(tatqa_records(), quotas["tatqa"], args.seed + 1)
    selected += stratified_sample(obliqa_records(), quotas["obliqa"], args.seed + 2)
    selected += stratified_sample(finreflect_records(), quotas["finkg"], args.seed + 3)
    selected += seeds
    random.Random(args.seed).shuffle(selected)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in selected), encoding="utf-8")
    manifest = {
        "version": 1, "seed": args.seed, "target_size": args.size,
        "actual_size": len(selected), "counts_by_dataset": dict(Counter(item["dataset"] for item in selected)),
        "counts_by_stratum": dict(Counter(str(item.get("stratum") or item.get("task_type")) for item in selected)),
        "sources": [
            {"dataset": "FinQA", "url": SOURCE_URLS["FinQA"], "file": str(FINQA.relative_to(ROOT)), "sha256": sha256(FINQA)},
            {"dataset": "TAT-QA", "url": SOURCE_URLS["TAT-QA"], "file": str(TATQA.relative_to(ROOT)), "sha256": sha256(TATQA)},
            {"dataset": "ObliQA", "url": SOURCE_URLS["ObliQA"], "file": str(OBLIQA.relative_to(ROOT)), "sha256": sha256(OBLIQA)},
            {"dataset": "FinReflectKG-EvalBench-derived", "url": SOURCE_URLS["FinReflectKG-EvalBench"], "file": str(FINREFLECT.relative_to(ROOT)), "sha256": sha256(FINREFLECT), "note": "QA prompts deterministically derived from source-validated triplets; human sign-off pending"},
            {"dataset": "AuditCompliance-seed / FinKG-seed", "file": str(SEEDS.relative_to(ROOT)), "note": "project-curated seeds; not represented as public benchmark samples"},
        ],
        "sample_ids": [item["id"] for item in selected],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), **{k: manifest[k] for k in ("actual_size", "counts_by_dataset")}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
